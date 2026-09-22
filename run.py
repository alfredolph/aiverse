"""AIVerse 一键启动器（文档 §35：用户不需要手动运行任何命令）。

用法：
    python run.py              # 默认 127.0.0.1:8770
    python run.py 9000         # 指定端口
    python run.py --no-open    # 不自动打开浏览器

打包后：双击 AIVerse.exe 即可，行为完全一致。
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

# 源码运行时把项目根目录加入 sys.path；打包后 backend 已在 bundle 内
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.app import serve                                    # noqa: E402
from backend.core.config import (APP_CODE, APP_NAME, DATA_DIR,   # noqa: E402
                                 HOST, PORT, RUNTIME_DIR, VERSION)
from backend.core.console import setup_console                   # noqa: E402
from backend.gpu import detector as gpu                          # noqa: E402
from backend.media import ffmpeg                                 # noqa: E402

setup_console()

BANNER = r"""
   _   _____   __     __
  /_\ |_   _|  \ \   / /__ _ _ ___ ___
 / _ \  | |     \ \ / / -_) '_/ -_|_-<
/_/ \_\ |_|      \_V_/\___|_| \___/__/
"""


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, want: int) -> int:
    for p in range(want, want + 20):
        if port_free(host, p):
            return p
    return want


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} · {APP_CODE}")
    ap.add_argument("port", nargs="?", type=int, default=PORT, help="监听端口")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--host", default=HOST, help="监听地址（局域网用 0.0.0.0）")
    ap.add_argument("--setup", action="store_true",
                    help="启动后直接进入「环境部署」页（安装包首次运行用）")
    args = ap.parse_args()

    port = pick_port(args.host, args.port)

    try:
        info = gpu.detect()
        top = info["gpus"][0]
        rec = info["recommend"]
        ff = ffmpeg.detect()
    except Exception as e:  # 硬件检测失败不应阻塞启动
        print(f"  [warn] 硬件检测失败：{e}")
        top, rec, ff = {"name": "未知", "vram_gb": 0}, {"precision": "-", "resolution": "-", "offload": False}, {"available": False, "hint": "-"}

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{port}"
    open_url = url + ("/?view=runtime" if args.setup else "")

    print(BANNER)
    print(f"  {APP_NAME} · {APP_CODE}  v{VERSION}")
    print("  " + "─" * 56)
    print(f"  数据目录 : {DATA_DIR}")
    print(f"  运行时   : {RUNTIME_DIR}")
    print(f"  GPU      : {top['name']}  ({top['vram_gb']} GB)   模式：{info.get('mode', '-') if isinstance(info, dict) else '-'}")
    print(f"  推荐配置 : {rec['precision']} / {rec['resolution']} / CPU Offload {'开' if rec['offload'] else '关'}")
    print(f"  FFmpeg   : {'已就绪' if ff['available'] else '未安装（可在「环境部署」里一键装）'}")
    print("  " + "─" * 56)
    print(f"  控制台   : {url}")
    if args.setup:
        print("  已进入   : 环境部署页（一键装本地推理环境）")
    print(f"  手机控制 : 局域网访问 http://<本机IP>:{port}")
    print("  退出     : 按 Ctrl+C 或直接关闭本窗口\n")

    httpd = serve(args.host, port)
    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(open_url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已退出。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
