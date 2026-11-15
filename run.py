"""启动入口。

    python run.py                 # 开发模式，自动重载
    python run.py --port 9000     # 指定端口
    python run.py --no-browser    # 不自动打开浏览器
    python run.py --init          # 仅初始化数据库与样例数据后退出
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="竞赛辅助服务智能体")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-reload", action="store_true")
    parser.add_argument("--init", action="store_true", help="初始化数据库与样例数据")
    args = parser.parse_args()

    from backend.config import settings

    host = args.host or settings.HOST
    port = args.port or settings.PORT

    if args.init:
        from backend.database import init_db
        from scripts.seed import seed_all

        init_db()
        seed_all()
        print("[OK] 初始化完成")
        return 0

    if port_in_use(host, port):
        print(f"[!] 端口 {port} 已被占用，请换一个：python run.py --port {port + 1}")
        return 1

    url = f"http://{'127.0.0.1' if host in {'0.0.0.0', ''} else host}:{port}"
    print("=" * 62)
    print(f"  {settings.APP_NAME}")
    print(f"  访问地址   {url}")
    print(f"  接口文档   {url}/api/docs")
    print(f"  大模型     {settings.LLM_PROVIDER} / {settings.effective_model or '未配置'}")

    vendor_dir = ROOT / "frontend" / "vendor"
    missing = [n for n in ("vue.global.prod.js", "echarts.min.js") if not (vendor_dir / n).exists()]
    if missing:
        print(f"  [!] 缺少前端依赖：{', '.join(missing)}")
        print("      请执行：python scripts/fetch_vendor.py")
    print("=" * 62)

    if not args.no_browser:
        threading.Thread(
            target=lambda: (time.sleep(1.8), webbrowser.open(url)), daemon=True
        ).start()

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=not args.no_reload,
        reload_dirs=[str(ROOT / "backend")],
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
