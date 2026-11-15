"""下载前端依赖（Vue 3 与 ECharts）到 frontend/vendor。

首次启动时若检测到 vendor 缺失会自动调用；也可手动运行：
    python scripts/fetch_vendor.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "frontend" / "vendor"

TARGETS = [
    (
        "vue.global.prod.js",
        [
            "https://unpkg.com/vue@3.5.13/dist/vue.global.prod.js",
            "https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.prod.js",
            "https://registry.npmmirror.com/vue/3.5.13/files/dist/vue.global.prod.js",
            "https://cdn.staticfile.net/vue/3.5.13/vue.global.prod.min.js",
        ],
        60_000,
    ),
    (
        "echarts.min.js",
        [
            "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
            "https://unpkg.com/echarts@5.5.1/dist/echarts.min.js",
            "https://registry.npmmirror.com/echarts/5.5.1/files/dist/echarts.min.js",
            "https://cdn.staticfile.net/echarts/5.5.1/echarts.min.js",
        ],
        800_000,
    ),
]


def fetch(name: str, urls: list[str], min_size: int) -> bool:
    dest = VENDOR / name
    if dest.exists() and dest.stat().st_size >= min_size:
        print(f"[skip] {name} 已存在（{dest.stat().st_size / 1024:.0f} KB）")
        return True

    VENDOR.mkdir(parents=True, exist_ok=True)
    for url in urls:
        try:
            print(f"[..] 尝试 {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            if len(data) < min_size:
                print(f"     文件过小（{len(data)} 字节），跳过")
                continue
            dest.write_bytes(data)
            print(f"[ok] {name}  {len(data) / 1024:.0f} KB")
            return True
        except Exception as e:
            print(f"     失败：{type(e).__name__}: {e}")
    return False


def ensure_vendor(quiet: bool = False) -> bool:
    ok = True
    for name, urls, min_size in TARGETS:
        dest = VENDOR / name
        if dest.exists() and dest.stat().st_size >= min_size:
            continue
        if quiet:
            print(f"[!] 缺少 frontend/vendor/{name}，正在尝试自动下载…")
        if not fetch(name, urls, min_size):
            ok = False
    return ok


def main() -> int:
    print("=" * 56)
    print("  下载前端依赖到 frontend/vendor")
    print("=" * 56)
    ok = ensure_vendor()
    if ok:
        print("\n完成。")
        return 0
    print(
        "\n[!] 下载失败。可手动获取以下文件放入 frontend/vendor/：\n"
        "    - vue.global.prod.js  (Vue 3 完整版，含模板编译器)\n"
        "    - echarts.min.js\n"
        "    或在使用时联网（页面会自动回落到 CDN）。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
