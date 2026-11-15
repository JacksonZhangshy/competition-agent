"""文本切块：按语义边界切分，保留标题上下文，控制块长。"""
from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 520
DEFAULT_OVERLAP = 90
MIN_CHARS = 60

_SENT_END = re.compile(r"(?<=[。！？；!?;\n])")


def _split_long(text: str, max_chars: int) -> list[str]:
    """超长段落按句号切，句子仍超长则硬切。"""
    sentences = [s for s in _SENT_END.split(text) if s.strip()]
    out: list[str] = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) <= max_chars:
            buf += s
        else:
            if buf:
                out.append(buf)
            if len(s) > max_chars:
                for i in range(0, len(s), max_chars):
                    out.append(s[i : i + max_chars])
                buf = ""
            else:
                buf = s
    if buf:
        out.append(buf)
    return out


def chunk_blocks(
    blocks: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict]:
    """把 loader 输出的块合并/切分为检索单元。

    每个 chunk 保留：content、heading（最近一次标题）、page。
    """
    chunks: list[dict] = []
    current_heading = ""
    buf = ""
    buf_page: int | None = None

    def emit(page: int | None) -> None:
        nonlocal buf, buf_page
        text = buf.strip()
        if len(text) >= MIN_CHARS or (text and not chunks):
            chunks.append({"content": text, "heading": _short(current_heading), "page": page})
        buf = ""
        buf_page = None

    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        if block.get("heading") == "标题":
            current_heading = text
            continue
        if block.get("heading") and block.get("heading") not in {"标题", "表格"}:
            current_heading = block["heading"] or current_heading

        page = block.get("page")
        if len(text) > max_chars:
            if buf:
                emit(buf_page)
            for piece in _split_long(text, max_chars):
                chunks.append(
                    {"content": piece.strip(), "heading": _short(current_heading), "page": page}
                )
            continue

        if len(buf) + len(text) + 1 <= max_chars:
            buf = f"{buf}\n{text}" if buf else text
            buf_page = buf_page or page
        else:
            emit(buf_page)
            buf = text
            buf_page = page

    if buf:
        emit(buf_page)

    # 加重叠：把上一块尾部拼到当前块前面，提升跨块问题的召回
    if overlap > 0 and len(chunks) > 1:
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1]["content"][-overlap:]
            if prev_tail and not chunks[i]["content"].startswith(prev_tail):
                chunks[i]["content"] = f"…{prev_tail}\n{chunks[i]['content']}"

    return [c for c in chunks if c["content"].strip()]


def _short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]
