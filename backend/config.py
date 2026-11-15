"""集中配置。仅使用标准库，避免因额外依赖导致启动失败。"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key] = value
    return data


# .env 只填补未设置的环境变量，系统环境变量优先
_file_env = _parse_env_file(ROOT_DIR / ".env")
for _k, _v in _file_env.items():
    os.environ.setdefault(_k, _v)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get(key) or default)
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    try:
        return int(float(_get(key) or default))
    except ValueError:
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    val = _get(key).lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _resolve(p: str, default: str) -> Path:
    raw = _get(p) or default
    path = Path(raw)
    if not path.is_absolute():
        path = (ROOT_DIR / path).resolve()
    return path


class Settings:
    # 基础
    APP_NAME: str = _get("APP_NAME", "竞赛辅助服务智能体")
    APP_ENV: str = _get("APP_ENV", "dev")
    HOST: str = _get("HOST", "127.0.0.1")
    PORT: int = _get_int("PORT", 8000)
    ADMIN_TOKEN: str = _get("ADMIN_TOKEN", "admin")

    # 数据库
    DATABASE_URL: str = _get("DATABASE_URL", "sqlite:///./data/app.db")

    # 大模型
    LLM_PROVIDER: str = (_get("LLM_PROVIDER", "mock") or "mock").lower()
    LLM_API_KEY: str = _get("LLM_API_KEY")
    LLM_MODEL: str = _get("LLM_MODEL")
    LLM_BASE_URL: str = _get("LLM_BASE_URL")
    LLM_TEMPERATURE: float = _get_float("LLM_TEMPERATURE", 0.3)
    LLM_MAX_TOKENS: int = _get_int("LLM_MAX_TOKENS", 2048)
    LLM_TIMEOUT: int = _get_int("LLM_TIMEOUT", 60)

    # 检索
    EMBEDDING_MODE: str = (_get("EMBEDDING_MODE", "local") or "local").lower()
    EMBEDDING_MODEL: str = _get("EMBEDDING_MODEL", "text-embedding-v3")
    EMBEDDING_DIM: int = _get_int("EMBEDDING_DIM", 512)
    RETRIEVE_VECTOR_WEIGHT: float = _get_float("RETRIEVE_VECTOR_WEIGHT", 0.5)
    RETRIEVE_BM25_WEIGHT: float = _get_float("RETRIEVE_BM25_WEIGHT", 0.5)
    RETRIEVE_TOP_K: int = _get_int("RETRIEVE_TOP_K", 6)
    RETRIEVE_MIN_SCORE: float = _get_float("RETRIEVE_MIN_SCORE", 0.20)

    # 路径
    KNOWLEDGE_DIR: Path = _resolve("KNOWLEDGE_DIR", "./data/knowledge")
    UPLOAD_DIR: Path = _resolve("UPLOAD_DIR", "./data/uploads")
    OUTPUT_DIR: Path = _resolve("OUTPUT_DIR", "./data/outputs")

    # 厂商默认地址
    PROVIDER_DEFAULTS = {
        "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        "doubao": ("https://ark.cn-beijing.volces.com/api/v3", ""),
        "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
        "ollama": ("http://127.0.0.1:11434/v1", "qwen2.5:7b"),
    }

    def __init__(self) -> None:
        base, model = self.PROVIDER_DEFAULTS.get(self.LLM_PROVIDER, ("", ""))
        self.effective_base_url = self.LLM_BASE_URL or base
        self.effective_model = self.LLM_MODEL or model

        for d in (self.KNOWLEDGE_DIR, self.UPLOAD_DIR, self.OUTPUT_DIR):
            d.mkdir(parents=True, exist_ok=True)

        # SQLite 相对路径兜底：保证 data 目录存在
        m = re.match(r"sqlite:///(.+)", self.DATABASE_URL)
        if m:
            db_path = Path(m.group(1))
            if not db_path.is_absolute():
                db_path = (ROOT_DIR / db_path).resolve()
                self.DATABASE_URL = "sqlite:///" + db_path.as_posix()
            db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def llm_ready(self) -> bool:
        """是否具备真实调用大模型的条件。"""
        if self.LLM_PROVIDER == "mock":
            return False
        if self.LLM_PROVIDER == "ollama":
            return bool(self.effective_base_url)
        return bool(self.LLM_API_KEY and self.effective_base_url and self.effective_model)


settings = Settings()
