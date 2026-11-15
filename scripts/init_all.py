"""一键初始化：建表 → 生成样例数据 → 生成知识库文档 → 导入知识库。

    python scripts/init_all.py           # 完整初始化（已存在数据时跳过）
    python scripts/init_all.py --force   # 清空并重建
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_deps() -> list[str]:
    missing = []
    for mod, pkg in [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn[standard]"),
        ("sqlalchemy", "SQLAlchemy"),
        ("docx", "python-docx"),
        ("openpyxl", "openpyxl"),
        ("pypdf", "pypdf"),
    ]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return missing


def main() -> int:
    force = "--force" in sys.argv
    t0 = time.time()

    print("=" * 60)
    print("  竞赛辅助服务智能体 · 初始化")
    print("=" * 60)

    missing = check_deps()
    if missing:
        print("\n[!] 缺少依赖，请先安装：")
        print(f"    pip install {' '.join(missing)}")
        print("  或直接：pip install -r requirements.txt\n")
        return 1

    from backend.config import settings
    from backend.database import db_session, init_db
    from backend.rag import ingest as ingest_mod

    print(f"\n[1/4] 建表  …  {settings.DATABASE_URL}")
    init_db()

    print("[2/4] 生成样例台账数据 …")
    from scripts.seed import seed_all

    info = seed_all(force=force)
    if info.get("skipped"):
        print(f"      已存在 {info['competitions']} 个赛事，跳过（加 --force 可重建）")
    else:
        for k, v in info.items():
            print(f"      {k:14s} {v}")

    print("[3/4] 生成知识库文档 …")
    from scripts import make_knowledge

    make_knowledge.main()

    print("[4/4] 导入知识库（切块 + 向量化）…")
    with db_session() as db:
        res = ingest_mod.ingest_directory(db, settings.KNOWLEDGE_DIR)
    print(f"      成功 {res['ok']} 份，失败 {res['failed']} 份")
    for err in res["errors"]:
        print(f"      ! {err['file']}: {err['error']}")

    with db_session() as db:
        stats = ingest_mod.stats(db)

    print("\n" + "=" * 60)
    print(f"  初始化完成，用时 {time.time() - t0:.1f}s")
    print(f"  知识库：{stats['doc_count']} 份文档 / {stats['chunk_count']} 个片段")
    print(f"  数据文件：{settings.DATABASE_URL}")
    print("\n  启动服务：python run.py")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
