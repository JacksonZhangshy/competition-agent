"""知识库导入流水线。"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..llm import llm
from ..models import KnowledgeChunk, KnowledgeDoc
from .chunker import chunk_blocks
from .index import cut, invalidate
from .loader import is_supported, load_any


def _infer_category(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("办法", "规定", "制度", "细则", "政策", "管理")):
        return "政策"
    if any(k in n for k in ("规程", "规则", "赛制", "指南")):
        return "规程"
    if any(k in n for k in ("通知", "公告", "安排")):
        return "通知"
    if any(k in n for k in ("模板", "申请书", "申报书", "表格")):
        return "模板"
    return "其他"


def ingest_file(
    db: Session,
    path: Path,
    category: str | None = None,
    year: int | None = None,
    title: str | None = None,
    overwrite: bool = True,
) -> KnowledgeDoc:
    path = Path(path)
    if not is_supported(path):
        raise ValueError(f"不支持的文件类型：{path.suffix}")
    if not path.exists():
        raise FileNotFoundError(path)

    category = category or _infer_category(path.stem)
    if year is None:
        # 文件名里的年份常常紧贴中文（如“2026年中国国际大学生创新大赛竞赛规程”），
        # 只按空白切分会漏掉，这里直接用正则找。
        m = re.search(r"(19|20)\d{2}", path.stem)
        if m:
            year = int(m.group(0))

    existing = db.query(KnowledgeDoc).filter(KnowledgeDoc.filename == path.name).first()
    if existing:
        if not overwrite:
            return existing
        db.delete(existing)
        db.flush()

    blocks = load_any(path)
    if not blocks:
        raise ValueError(f"未能从 {path.name} 中提取到文本（可能是扫描件或空文件）")

    if year is None:
        # 文件名没有年份时，从正文开头的“（2024 年 3 月修订）”这类表述里取
        head = " ".join(b["text"] for b in blocks)[:600]
        m = re.search(r"((?:19|20)\d{2})\s*年", head)
        if m:
            year = int(m.group(1))

    chunks = chunk_blocks(blocks)
    if not chunks:
        raise ValueError(f"{path.name} 切块结果为空")

    doc = KnowledgeDoc(
        title=(title or path.stem).strip(),
        filename=path.name,
        filetype=path.suffix.lstrip(".").lower(),
        category=category,
        year=year,
        source_path=str(path),
        char_count=sum(len(b["text"]) for b in blocks),
        chunk_count=len(chunks),
        status="已入库",
        meta={"blocks": len(blocks), "ingested_at": dt.datetime.now().isoformat(timespec="seconds")},
    )
    db.add(doc)
    db.flush()

    vectors = llm.embed([c["content"] for c in chunks])
    for i, (c, vec) in enumerate(zip(chunks, vectors)):
        db.add(
            KnowledgeChunk(
                doc_id=doc.id,
                seq=i,
                content=c["content"],
                heading=c["heading"] or "",
                page=c["page"],
                char_count=len(c["content"]),
                vector=vec,
                tokens=" ".join(cut(c["content"]))[:20000],
            )
        )
    db.commit()
    invalidate()
    return doc


def ingest_directory(db: Session, directory: Path | None = None, recursive: bool = True) -> dict:
    directory = Path(directory or settings.KNOWLEDGE_DIR)
    if not directory.exists():
        return {"ok": 0, "failed": 0, "errors": [], "docs": []}

    pattern = "**/*" if recursive else "*"
    ok, failed, errors, docs = 0, 0, [], []
    for p in sorted(directory.glob(pattern)):
        if not p.is_file() or not is_supported(p):
            continue
        try:
            doc = ingest_file(db, p)
            ok += 1
            docs.append({"id": doc.id, "title": doc.title, "chunks": doc.chunk_count})
        except Exception as e:  # 单个文件失败不影响整体
            failed += 1
            errors.append({"file": p.name, "error": str(e)})
    return {"ok": ok, "failed": failed, "errors": errors, "docs": docs}


def delete_doc(db: Session, doc_id: int) -> bool:
    doc = db.get(KnowledgeDoc, doc_id)
    if not doc:
        return False
    db.delete(doc)
    db.commit()
    invalidate()
    return True


def stats(db: Session) -> dict:
    docs = db.query(KnowledgeDoc).all()
    by_category: dict[str, int] = {}
    for d in docs:
        by_category[d.category] = by_category.get(d.category, 0) + 1
    return {
        "doc_count": len(docs),
        "chunk_count": sum(d.chunk_count for d in docs),
        "char_count": sum(d.char_count for d in docs),
        "by_category": by_category,
    }
