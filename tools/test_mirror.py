"""验证「卡死的镜像会被放弃」—— 这是「点了一键部署没反应」的根因防线。

背景（2026-09 实测）：ghproxy.net / gh-proxy.com / github.com 三个源**全都
连得上、也都能返回 206**，但被限速到 12~15 KB/s。uv 才 17 MB，跑了两分半
只下到 2 MB，进度条停在 11% 再也不动 —— 用户看到的是「点了没反应」，
而不是报错。所以只判断「请求是否成功」是远远不够的，必须拿**实测吞吐**当判据。

这里起两个本地 HTTP 服务：一个故意慢慢吐字（约 40 KB/s）、一个全速，
用来把「测速排序」和「下到一半发现太慢就换源」两条路径钉住。
全程本地回环，不联网，所以不标 continue-on-error。

用法：
    python tools/test_mirror.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.runtime import downloader                    # noqa: E402
from backend.runtime.downloader import Downloader          # noqa: E402

# 快源的载荷（1 MB，够触发一个测速窗口）
PAYLOAD = b"aiverse" * (128 * 1024)          # 1 MB
SLOW_TOTAL = 4 * 1024 * 1024
SLOW_CHUNK = 8 * 1024
SLOW_PAUSE = 0.2                              # 8 KB / 0.2s ≈ 40 KB/s

fail: list[str] = []


def need(cond: bool, msg: str, label: str = "") -> None:
    print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
    if not cond:
        fail.append(msg)


class _Handler(BaseHTTPRequestHandler):
    """/slow 慢慢吐，/fast 全速；其余 404。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:                 # noqa: N802
        if self.path.startswith("/slow"):
            self.send_response(200)
            self.send_header("Content-Length", str(SLOW_TOTAL))
            self.end_headers()
            sent = 0
            # 客户端发现太慢会直接断开，这对慢源来说是完全正常的，
            # 别让 socketserver 把整条 traceback 刷到测试输出里。
            try:
                while sent < SLOW_TOTAL:
                    self.wfile.write(b"z" * SLOW_CHUNK)
                    self.wfile.flush()
                    sent += SLOW_CHUNK
                    time.sleep(SLOW_PAUSE)
            except OSError:
                pass
            return
        if self.path.startswith("/fast"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:     # 别往测试输出里刷访问日志
        pass


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        pass                                   # 同上：客户端主动断开不是错误


def serve() -> tuple[str, callable]:
    """起一个本地服务，返回 (base_url, shutdown)。

    慢源和快源必须是**两个**服务：测速结果按域名缓存，
    同一个端口上的 /slow 与 /fast 会被当成同一个源，排序自然无从谈起。
    """
    httpd = _QuietServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    return base, httpd.shutdown


def main() -> int:
    print("\n[1/4] 测速：慢源必须被测出来")
    slow_base, shutdown_slow = serve()
    fast_base, shutdown_fast = serve()
    slow_url, fast_url = f"{slow_base}/slow/x.zip", f"{fast_base}/fast/x.zip"
    try:
        s_slow = downloader.probe_speed(slow_url, nbytes=256 * 1024, budget=4.0)
        s_fast = downloader.probe_speed(fast_url, nbytes=256 * 1024, budget=4.0)
        print(f"    慢源 {s_slow / 1024:.0f} KB/s · 快源 {s_fast / 1024:.0f} KB/s")
        need(s_fast > s_slow * 3, "快源应明显快于慢源", f"快源比慢源快 {s_fast / max(s_slow, 1):.0f} 倍")
        need(0 < s_slow < downloader.MIN_SPEED_BPS,
             f"慢源速度应低于阈值 {downloader.MIN_SPEED_BPS // 1024} KB/s",
             f"慢源 {s_slow / 1024:.0f} KB/s < 阈值")

        print("\n[2/4] 排序：快的排前面")
        downloader._HOST_SPEED.clear()        # 别让上一轮的缓存影响这次
        msgs: list[str] = []
        dl = Downloader(progress=lambda d: msgs.append(d.get("message") or ""))
        ranked = dl.rank_mirrors([slow_url, fast_url])
        need(ranked[0] == fast_url, "快源应排到第一位", f"排序结果：{[u.split('/')[3] for u in ranked]}")
        need(any("排序" in m for m in msgs), "排序结果应通过进度回调告知用户")

        print("\n[3/4] 下载中卡死：必须放弃当前源")
        # 把窗口压到 1.5 秒，否则这条测试要真等 12 秒
        old_window, old_min = downloader.SPEED_WINDOW, downloader.MIN_SPEED_BPS
        downloader.SPEED_WINDOW, downloader.MIN_SPEED_BPS = 1.5, 200 * 1024
        try:
            with tempfile.TemporaryDirectory(prefix="aiverse-mirror-") as td:
                part = Path(td) / "x.zip.part"
                dest = Path(td) / "x.zip"
                try:
                    dl._fetch_one(slow_url, part, dest, "测试包", 0.0)
                    need(False, "慢源应该在观察窗口内就被放弃（抛出 SlowMirror）")
                except downloader.SlowMirror as e:
                    need("太慢" in str(e), "放弃原因应明确写「太慢」", f"放弃原因：{e}")
                    need(part.stat().st_size > 0, "已下的字节应留在 .part 里，供下次续传")

            print("\n    换源恢复：测速时看着还行、真下载才卡死的情况")
            # 手动把慢源的测速结果吹成很快，模拟「测速乐观、实际卡死」——
            # 测速只读 768 KB，遇上「前 1 MB 快、之后限速」的源就会被骗。
            downloader._host_speed_put(downloader._host_of(slow_url), 5 * 1024 * 1024)
            downloader._host_speed_put(downloader._host_of(fast_url), 1 * 1024 * 1024)
            with tempfile.TemporaryDirectory(prefix="aiverse-mirror-") as td:
                dest = Path(td) / "x.zip"
                t0 = time.time()
                got = dl.fetch([slow_url, fast_url], dest, label="测试包")
                dt = time.time() - t0
                need(got == dest and dest.exists(), "应从快源恢复下载成功")
                need(dest.stat().st_size == len(PAYLOAD),
                     f"文件应是快源的 {len(PAYLOAD)} 字节",
                     f"文件大小 {dest.stat().st_size}")
                need(any("太慢" in m for m in msgs),
                     "日志里应写明是因为太慢才换源",
                     "已记录换源原因")
                print(f"    换源耗时 {dt:.1f}s（慢源窗口 {downloader.SPEED_WINDOW}s）")
        finally:
            downloader.SPEED_WINDOW, downloader.MIN_SPEED_BPS = old_window, old_min

        print("\n[4/4] 全是慢源：报错要说人话，不能只说「全部镜像下载失败」")
        downloader._HOST_SPEED.clear()
        downloader.SPEED_WINDOW, downloader.MIN_SPEED_BPS = 1.0, 200 * 1024
        try:
            with tempfile.TemporaryDirectory(prefix="aiverse-mirror-") as td:
                dest = Path(td) / "y.zip"
                try:
                    dl.fetch([slow_url], dest, label="测试包")
                    need(False, "全是慢源时应抛出异常")
                except RuntimeError as e:
                    msg = str(e)
                    need("太慢" in msg, "异常里应说明是「太慢」而不是「失败」",
                         "报错点明了限速")
                    need("离线包" in msg or "镜像" in msg, "异常里应给出下一步建议",
                         "报错给了可操作的建议")
        finally:
            downloader.SPEED_WINDOW, downloader.MIN_SPEED_BPS = old_window, old_min
    finally:
        shutdown_slow()
        shutdown_fast()

    print("\n" + ("─" * 62))
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("  · " + f)
        return 1
    print("✓ 卡死换源 / 测速排序全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
