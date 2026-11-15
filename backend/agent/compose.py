"""回答组织：引用格式化、核心词提取与抽取式回答（无大模型时的降级路径）。

本模块只依赖标准库与 llm 模块，不触碰数据库，便于单独测试。
核心原则：降级路径只重组检索到的原句，绝不生成原文中不存在的事实。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..llm import llm, tokenize

if TYPE_CHECKING:  # pragma: no cover
    from ..rag.index import Hit

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])")

#: 疑问词与虚词用字。用于从问题中剥离"什么时候""哪些"这类不承载检索意义的成分。
_STOP_CHARS = set(
    "的了和与及是在有要请问一下什么怎如何哪些哪个多少为候吗呢啊请可是否以及这个那个"
    "我们你我他需能会就该把被从对于之其些样条项种呗呀嘛咯哦吧哈么么样"
)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip()) >= 8]


def meaningful_tokens(text: str) -> set[str]:
    """提取承载检索意义的词元（去掉纯虚词/疑问词构成的词元）。

    tokenize 产出的是"英文词 + 中文单字 + 中文二元组"，因此像"什么""时候""哪些"
    会以二元组形式出现，逐字符判断可否全部归入停用字即可过滤。
    """
    out: set[str] = set()
    for tok in tokenize(text):
        if not tok:
            continue
        if all(ch in _STOP_CHARS for ch in tok):
            continue
        out.add(tok)
    return out


def core_coverage(question: str, hits: list, limit: int = 3) -> float:
    """问题核心词在检索片段中的覆盖比例，用于判断"到底有没有答得上"。"""
    q = meaningful_tokens(question)
    if not q:
        return 0.0
    corpus = " ".join(h.chunk.content for h in hits[:limit])
    return len(q & meaningful_tokens(corpus)) / len(q)


def hits_to_context(hits: list, limit: int = 6) -> str:
    """把检索片段拼成给大模型的上下文，带编号与出处。"""
    parts = []
    for i, h in enumerate(hits[:limit], start=1):
        c = h.chunk
        loc = f"{c.doc_title}"
        if c.page:
            loc += f" 第{c.page}页"
        if c.heading:
            loc += f" · {c.heading}"
        parts.append(f"[{i}] 来源：{loc}\n{c.content.strip()}")
    return "\n\n".join(parts)


def build_citations(hits: list, limit: int = 6) -> list[dict]:
    return [h.citation() for h in hits[:limit]]


def llm_or_none(messages: list[dict], **kwargs) -> str | None:
    return llm.try_chat(messages, **kwargs)


#: 最佳句子的核心词覆盖率低于此值，视为"检索到了但答不上"。
ANSWER_MIN_COVERAGE = 0.4


def extractive_answer(question: str, hits: list) -> str:
    """抽取式回答：按核心词覆盖率挑出原文句子重组，不改写、不补全。"""
    if not hits:
        return ""

    q_all = set(tokenize(question))
    q_core = meaningful_tokens(question) or q_all
    scored: list[tuple[float, str, int, float]] = []

    for idx, h in enumerate(hits[:6], start=1):
        for sent in split_sentences(h.chunk.content):
            s_tokens = set(tokenize(sent))
            if not s_tokens:
                continue
            cov = len(q_core & s_tokens) / (len(q_core) or 1)
            soft = len(q_all & s_tokens) / (len(q_all) or 1)
            if cov <= 0 and soft < 0.15:
                continue
            score = cov * 0.72 + soft * 0.12 + h.score * 0.16
            scored.append((score, sent, idx, cov))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_cov = scored[0][3] if scored else 0.0

    picked: list[tuple[str, int]] = []
    seen: set[str] = set()
    for _score, sent, idx, _cov in scored:
        key = re.sub(r"\s+", "", sent)[:40]
        if key in seen:
            continue
        seen.add(key)
        picked.append((sent, idx))
        if len(picked) >= 4:
            break

    if not picked or best_cov < ANSWER_MIN_COVERAGE:
        top = hits[0]
        return (
            "结论：知识库中检索到与问题相关的片段，但未包含可直接回答的内容。\n\n"
            "依据（命中的最相关片段）：\n"
            f"- [1] {top.chunk.content[:200]}…\n\n"
            f"补充：该内容出自《{top.chunk.doc_title}》。如果这不是你想要的，"
            "建议换用更具体的赛事名称或文件条款表述重新提问。"
        )

    conclusion = picked[0][0]
    if len(conclusion) > 110:
        conclusion = conclusion[:110] + "…"

    # 结论句本身不再重复列进“依据”，避免同一句话出现两次
    lines = [f"结论：{conclusion}", "", "依据："]
    for sent, idx in picked[1:]:
        s = sent if len(sent) <= 150 else sent[:150] + "…"
        lines.append(f"- {s} [{idx}]")
    src_hit = hits[picked[0][1] - 1] if 0 <= picked[0][1] - 1 < len(hits) else hits[0]
    lines.append(f"- 结论出处：《{src_hit.chunk.doc_title}》 [{picked[0][1]}]")
    lines.append("")
    lines.append(
        "补充：以上内容由知识库原文片段抽取而成，未经过模型改写，可直接对照原文核实。"
        f"（命中 {len(hits)} 个片段，最高相关度 {hits[0].score:.2f}）"
    )
    return "\n".join(lines)
