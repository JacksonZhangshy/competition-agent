"""RAG 包：解析 → 切块 → 向量化 → 入库 → 混合检索。"""
from __future__ import annotations

from .chunker import chunk_blocks
from .index import Hit, RetrievalIndex, get_index, invalidate
from .ingest import delete_doc, ingest_directory, ingest_file
from .loader import SUPPORTED, load_any, is_supported

__all__ = [
    "SUPPORTED",
    "Hit",
    "RetrievalIndex",
    "chunk_blocks",
    "delete_doc",
    "get_index",
    "ingest_directory",
    "ingest_file",
    "invalidate",
    "is_supported",
    "load_any",
]
