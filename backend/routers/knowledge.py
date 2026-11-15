"""知识库管理接口：上传、列表、检索测试、重建索引。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import KnowledgeDoc
from ..rag import ingest as ingest_mod
from ..rag.index import get_index, invalidate
from ..rag.loader import is_supported

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


class SearchPayload(BaseModel):
    query: str
    top_k: int = 6
    category: str | None = None
    year: int | None = None


@router.get("/docs")
def list_docs(db: Session = Depends(get_db)) -> dict:
    rows = db.query(KnowledgeDoc).order_by(KnowledgeDoc.created_at.desc()).all()
    return {
        "stats": ingest_mod.stats(db),
        "items": [
            {
                "id": d.id,
                "title": d.title,
                "filename": d.filename,
                "filetype": d.filetype,
                "category": d.category,
                "year": d.year,
                "char_count": d.char_count,
                "chunk_count": d.chunk_count,
                "status": d.status,
                "created_at": d.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for d in rows
        ],
    }


@router.post("/upload")
async def upload(
    files: list[UploadFile] = File(...),
    category: str = Form(""),
    year: str = Form(""),
    db: Session = Depends(get_db),
) -> dict:
    settings.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    ok, failed, docs = 0, 0, []
    errors: list[dict] = []

    year_val = int(year) if str(year).strip().isdigit() else None

    for f in files:
        name = Path(f.filename or "unnamed").name
        suffix = Path(name).suffix.lower()
        if not is_supported(Path(name)):
            failed += 1
            errors.append({"file": name, "error": f"不支持的类型 {suffix}"})
            continue
        dest = settings.KNOWLEDGE_DIR / name
        try:
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            doc = ingest_mod.ingest_file(db, dest, category=category or None, year=year_val)
            ok += 1
            docs.append({"id": doc.id, "title": doc.title, "chunks": doc.chunk_count})
        except Exception as e:
            failed += 1
            errors.append({"file": name, "error": str(e)})
        finally:
            await f.close()

    return {"ok": ok, "failed": failed, "errors": errors, "docs": docs}


@router.post("/ingest-dir")
def ingest_dir(db: Session = Depends(get_db)) -> dict:
    return ingest_mod.ingest_directory(db, settings.KNOWLEDGE_DIR)


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, db: Session = Depends(get_db)) -> dict:
    doc = db.get(KnowledgeDoc, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    src = Path(doc.source_path) if doc.source_path else None
    ok = ingest_mod.delete_doc(db, doc_id)
    if ok and src and src.exists() and settings.KNOWLEDGE_DIR in src.parents:
        try:
            src.unlink()
        except OSError:
            pass
    return {"ok": ok}


@router.post("/search")
def search(payload: SearchPayload, db: Session = Depends(get_db)) -> dict:
    index = get_index(db)
    hits = index.search(payload.query, top_k=payload.top_k, category=payload.category, year=payload.year)
    return {"count": len(hits), "items": [h.citation() for h in hits]}


@router.post("/rebuild")
def rebuild(db: Session = Depends(get_db)) -> dict:
    invalidate()
    index = get_index(db, force=True)
    return {"ok": True, "chunks": index.size}


@router.get("/chunks/{chunk_id}")
def chunk_detail(chunk_id: int, db: Session = Depends(get_db)) -> dict:
    from ..models import KnowledgeChunk

    c = db.get(KnowledgeChunk, chunk_id)
    if not c:
        raise HTTPException(404, "片段不存在")
    doc = db.get(KnowledgeDoc, c.doc_id)
    return {
        "id": c.id,
        "doc_id": c.doc_id,
        "title": doc.title if doc else "",
        "filename": doc.filename if doc else "",
        "heading": c.heading,
        "page": c.page,
        "seq": c.seq,
        "content": c.content,
    }
