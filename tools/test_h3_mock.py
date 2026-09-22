"""用「假 ComfyUI」端到端验证 H3 生成链路。

为什么需要它：`H3ComfyUIProvider.generate()` 要真的有一台装了 H3 的 ComfyUI 才能跑，
而开发机通常没有 N 卡。于是这里起一个本地 HTTP 服务，按 ComfyUI 的真实接口约定应答：

    GET  /system_stats     -> 系统信息
    GET  /object_info      -> 节点清单（含 H3 节点，用来验证自动识别）
    POST /prompt           -> 返回 prompt_id
    GET  /history/{id}     -> 前几次「还在跑」，之后返回 outputs
    GET  /view?...         -> 返回 MP4 字节

这样就能把「提交 → 轮询 → 取回文件」整条链路真的走一遍，而不是只测到接口签名。

用法：
    python tools/test_h3_mock.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORT = 18188
FAKE_MP4 = (
    b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    + b"\x00" * 4096
    + b"\x00\x00\x00\x08free"
)

# 一个最小可用的 H3 节点清单：类名刻意做成「跟默认映射不同」，
# 用来验证 autodetect_node_map() 真的在干活，而不是照抄默认值。
OBJECT_INFO = {
    "MiniMaxH3ModelLoader": {"input": {"required": {}}, "output": ["MODEL"]},
    "MiniMaxH3SamplerNode": {"input": {"required": {}}, "output": ["LATENT"]},
    "MiniMaxH3EmptyLatentVideo": {"input": {"required": {}}, "output": ["LATENT"]},
    "CLIPTextEncode": {"input": {"required": {}}, "output": ["CONDITIONING"]},
    "VAEDecode": {"input": {"required": {}}, "output": ["IMAGE"]},
    "SaveVideo": {"input": {"required": {}}, "output": []},
    "LoadImage": {"input": {"required": {}}, "output": ["IMAGE"]},
    "MiniMaxH3SageAttentionPatch": {"input": {"required": {}}, "output": ["MODEL"]},
    "MiniMaxH3EasyCache": {"input": {"required": {}}, "output": ["MODEL"]},
}

_state = {"submitted": [], "history_hits": 0, "downloaded": 0}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def _json(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/system_stats":
            return self._json({"system": {"os": "nt", "comfyui_version": "0.3.99",
                                          "python_version": "3.12.0"}})
        if path == "/object_info":
            return self._json(OBJECT_INFO)
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[-1]
            _state["history_hits"] += 1
            seen = _state.setdefault("hits_by_id", {})
            seen[pid] = seen.get(pid, 0) + 1
            # 每个任务前两次假装还在跑，第三次给结果 —— 覆盖真实的轮询行为
            if seen[pid] <= 2:
                return self._json({})
            return self._json({pid: {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "outputs": {"7": {"gifs": [
                    {"filename": "aiverse_h3_00001_.mp4", "subfolder": "aiverse", "type": "output"}
                ]}},
            }})
        if path == "/view":
            _state["downloaded"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(FAKE_MP4)))
            self.end_headers()
            self.wfile.write(FAKE_MP4)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode() or "{}")
        if urllib.parse.urlparse(self.path).path == "/prompt":
            _state["submitted"].append(body)
            _state["n"] = _state.get("n", 0) + 1
            return self._json({"prompt_id": f"mock-prompt-{_state['n']}",
                               "number": _state["n"], "node_errors": {}})
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> int:
    from backend.providers.media import H3ComfyUIProvider, _PORT_CACHE
    from backend.providers.h3_workflows import DEFAULT_NODE_MAP

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)
    _PORT_CACHE.clear()   # 别让之前的负缓存影响判断

    url = f"http://127.0.0.1:{PORT}"
    p = H3ComfyUIProvider(base_url=url, meta={"steps": 8, "fps": 24})
    fail: list[str] = []

    def need(cond, msg, label=""):
        print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
        if not cond:
            fail.append(msg)

    print("\n[1/7] 健康检查")
    h = p.health()
    need(h.get("ok") is True, f"health 应就绪，实际 {h}",
         f"就绪 · 加速节点 sage_attention={h.get('acceleration', {}).get('sage_attention')} "
         f"easy_cache={h.get('acceleration', {}).get('easy_cache')}")

    print("\n[2/7] 节点自动识别（清单里的类名与默认映射不同）")
    nm = p.node_map()
    need(nm.get("model_loader") == "MiniMaxH3ModelLoader",
         f"model_loader 识别失败：{nm.get('model_loader')}",
         f"model_loader → {nm.get('model_loader')}")
    need(nm.get("sampler") == "MiniMaxH3SamplerNode",
         f"sampler 识别失败：{nm.get('sampler')}",
         f"sampler → {nm.get('sampler')}")
    need(nm.get("latent_video") == "MiniMaxH3EmptyLatentVideo",
         f"latent_video 识别失败：{nm.get('latent_video')}（中间插词类名没兜住）",
         f"latent_video → {nm.get('latent_video')}")
    need(nm.get("video_output") == "SaveVideo",
         f"video_output 识别失败：{nm.get('video_output')}",
         f"video_output → {nm.get('video_output')}")
    need(nm != DEFAULT_NODE_MAP, "识别结果不应等于默认映射（说明没真的读 /object_info）",
         "识别结果与默认映射不同（确认真的读了 /object_info）")

    print("\n[3/7] ensure_ready（端口已开，不应尝试拉起）")
    t0 = time.time()
    need(p.ensure_ready() is True, "ensure_ready 应返回 True")
    need(time.time() - t0 < 5, f"不该等待超时（耗时 {time.time()-t0:.1f}s）")

    print("\n[4/7] 生成（提交 → 轮询 → 取回 MP4）")
    t0 = time.time()
    res = p.generate("一个雨夜的药铺，掌柜在柜台后抬眼", seconds=4.0, aspect="16:9",
                     resolution="720p", seed=12345)
    dt = time.time() - t0
    need(bool(res.get("path")), f"应返回本地文件路径，实际 {res}")
    local = Path(res["path"]) if res.get("path") else None
    need(local and local.exists(), "下载的文件应真实存在",
         f"MP4 已落到 {local}")
    need(local and local.stat().st_size == len(FAKE_MP4),
         f"文件大小应为 {len(FAKE_MP4)}，实际 {local.stat().st_size if local else 0}",
         f"文件大小 {local.stat().st_size} B，与 /view 返回一致")
    need(_state["downloaded"] == 1, f"/view 应被调用 1 次，实际 {_state['downloaded']}")
    need(_state["history_hits"] >= 3,
         f"应轮询到第 3 次才拿到结果，实际 {_state['history_hits']} 次",
         f"轮询 {_state['history_hits']} 次后拿到结果（前两次正确判为「还在跑」）")
    print(f"     生成耗时 {dt:.1f}s")

    print("\n[5/7] 提交给 ComfyUI 的图是否合法")
    need(len(_state["submitted"]) == 1, "应只提交 1 次")
    graph = _state["submitted"][0].get("prompt", {}) if _state["submitted"] else {}
    need(len(graph) >= 6, f"工作流节点数偏少：{len(graph)}", f"工作流共 {len(graph)} 个节点")
    classes = {v.get("class_type") for v in graph.values()}
    need("MiniMaxH3ModelLoader" in classes,
         f"工作流里没有识别出的 loader 节点：{classes}",
         "工作流用的是识别出来的真实类名（不是硬编码）")
    need("SaveVideo" in classes, "工作流里没有保存节点", "含视频保存节点")
    sizes = [v for v in graph.values() if "width" in (v.get("inputs") or {})]
    if sizes:
        w = sizes[0]["inputs"]["width"]
        hh = sizes[0]["inputs"]["height"]
        need(w % 32 == 0 and hh % 32 == 0, f"宽高应为 32 的倍数，实际 {w}x{hh}",
             f"分辨率 {w}x{hh}（32 的倍数）")

    print("\n[6/7] manifest 内容")
    m = res.get("manifest", {})
    need(m.get("backend") == "comfyui", "manifest.backend 应为 comfyui")
    need(m.get("prompt_id") == "mock-prompt-1", "manifest.prompt_id 应记录")
    need(m.get("status") == "rendered", "manifest.status 应为 rendered")
    need(m.get("seed") == 12345, f"seed 应透传，实际 {m.get('seed')}")
    need(m.get("variant") == "fl2va", f"无参考图时应走 fl2va，实际 {m.get('variant')}",
         "无参考图 → 走 fl2va 变体")

    print("\n[7/7] 带参考图（ref2va 变体）")
    ref = Path(tempfile.gettempdir()) / "aiverse_h3_ref_test.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    res2 = p.generate("同一个掌柜，推近景", reference=str(ref), seconds=3.0,
                      aspect="9:16", resolution="720p", seed=777)
    need(res2.get("manifest", {}).get("variant") == "ref2va",
         f"带参考图时应走 ref2va，实际 {res2.get('manifest', {}).get('variant')}",
         "带参考图 → 走 ref2va 变体")
    graph2 = _state["submitted"][1].get("prompt", {}) if len(_state["submitted"]) > 1 else {}
    loaders = [v for v in graph2.values() if "image" in str(v.get("class_type", "")).lower()]
    need(bool(loaders), "ref2va 工作流里应包含图片加载节点",
         f"ref2va 工作流含 {len(loaders)} 个图片节点")
    w2 = next((v["inputs"]["width"] for v in graph2.values()
               if "width" in (v.get("inputs") or {})), 0)
    h2 = next((v["inputs"]["height"] for v in graph2.values()
               if "height" in (v.get("inputs") or {})), 0)
    need(h2 > w2, f"9:16 竖屏应满足高>宽，实际 {w2}x{h2}", f"9:16 竖屏 → {w2}x{h2}")
    ref.unlink(missing_ok=True)

    srv.shutdown()

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("✓ H3 生成链路端到端通过（假 ComfyUI）")
    print(f"  临时文件：{local}")
    print("  真实环境里把 base_url 指向装了 H3 的 ComfyUI 即可，逻辑完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
