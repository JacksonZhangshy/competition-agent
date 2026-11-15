"""大模型客户端。

设计要点：
1. 只用标准库 urllib 发请求，不引入 openai SDK 等额外依赖；
2. 兼容 DeepSeek / Qwen(DashScope) / 豆包(Ark) / OpenAI / Ollama 等 OpenAI 协议服务；
3. 未配置 API Key 时自动降级（try_chat 返回 None），由上层走抽取式回答，保证系统离线可演示。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Iterable

from .config import settings

_CJK = re.compile(r"[\u4e00-\u9fa5]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")


class LLMError(RuntimeError):
    pass


def tokenize(text: str) -> list[str]:
    """轻量分词：中文取单字 + 二元组，英文/数字取词。

    不依赖 jieba 也能工作；若已安装 jieba 则由调用方优先使用 jieba。
    """
    tokens: list[str] = []
    for w in _WORD.findall(text.lower()):
        tokens.append(w)
    cjk_seq = "".join(_CJK.findall(text))
    for ch in cjk_seq:
        tokens.append(ch)
    for i in range(len(cjk_seq) - 1):
        tokens.append(cjk_seq[i : i + 2])
    return tokens


def local_embed(text: str, dim: int) -> list[float]:
    """本地 hashing 向量。离线、确定、无需模型，用于混合检索的语义通道兜底。"""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    for tok, cnt in counts.items():
        h = hashlib.md5(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign * (1.0 + math.log(cnt))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a = list(a)
    b = list(b)
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.LLM_PROVIDER
        self.base_url = settings.effective_base_url.rstrip("/")
        self.model = settings.effective_model
        self.api_key = settings.LLM_API_KEY
        self.timeout = settings.LLM_TIMEOUT
        self._last_error: str = ""
        self._ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------ 状态
    @property
    def available(self) -> bool:
        return settings.llm_ready

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model or "(未配置)",
            "base_url": self.base_url or "(未配置)",
            "available": self.available,
            "embedding_mode": settings.EMBEDDING_MODE,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------ HTTP
    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            self._last_error = f"HTTP {e.code}: {detail}"
            raise LLMError(self._last_error) from e
        except Exception as e:  # 网络/超时/证书
            self._last_error = f"{type(e).__name__}: {e}"
            raise LLMError(self._last_error) from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            self._last_error = f"响应非 JSON: {raw[:200]}"
            raise LLMError(self._last_error) from e

    # ------------------------------------------------------------ 对话
    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> str:
        if not self.available:
            raise LLMError("未配置可用的大模型服务")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
            "stream": False,
        }
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                data = self._post("/chat/completions", payload)
                return (data["choices"][0]["message"]["content"] or "").strip()
            except LLMError as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(1.2 * (attempt + 1))
        raise last_exc or LLMError("调用失败")

    def try_chat(self, messages: list[dict], **kwargs) -> str | None:
        """调用失败或未配置时返回 None，让上层走规则分支，不中断流程。"""
        if not self.available:
            return None
        try:
            out = self.chat(messages, **kwargs)
            return out or None
        except LLMError:
            return None

    def chat_json(self, messages: list[dict], **kwargs) -> dict | None:
        """要求模型输出 JSON，做宽松解析。"""
        raw = self.try_chat(messages, **kwargs)
        if not raw:
            return None
        return parse_json_loose(raw)

    # ------------------------------------------------------------ 向量
    def embed(self, texts: list[str]) -> list[list[float]]:
        if settings.EMBEDDING_MODE == "api" and self.available:
            try:
                return self._embed_api(texts)
            except Exception:
                pass  # 失败自动落到本地向量，保证检索链路不断
        return [local_embed(t, settings.EMBEDDING_DIM) for t in texts]

    def _embed_api(self, texts: list[str]) -> list[list[float]]:
        # DashScope 兼容模式单次最多 25 条，分批处理
        out: list[list[float]] = []
        for i in range(0, len(texts), 25):
            batch = texts[i : i + 25]
            data = self._post("/embeddings", {"model": settings.EMBEDDING_MODEL, "input": batch})
            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            out.extend([it["embedding"] for it in items])
        if len(out) != len(texts):
            raise LLMError("embedding 返回数量不匹配")
        return out


def parse_json_loose(raw: str) -> dict | None:
    """从模型输出中尽力抽取 JSON 对象。"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


llm = LLMClient()


def extract_json_block(text: str) -> Any:
    return parse_json_loose(text)
