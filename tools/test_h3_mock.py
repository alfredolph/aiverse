"""用「假 ComfyUI」端到端验证 H3 生成链路。

为什么需要它：`H3ComfyUIProvider.generate()` 要真的有一台装了 H3 的 ComfyUI 才能跑，
而开发机通常没有 N 卡。于是这里起一个本地 HTTP 服务，按 ComfyUI 的真实接口约定应答：

    GET  /system_stats     -> 系统信息
    GET  /object_info      -> 节点清单（**含真实的 H3 节点定义与输入名**）
    POST /prompt           -> 返回 prompt_id
    GET  /history/{id}     -> 前几次「还在跑」，之后返回 outputs
    GET  /view?...         -> 返回 MP4 字节

这样就能把「提交 → 轮询 → 取回文件」整条链路真的走一遍，而不是只测到接口签名。

节点定义照着 ComfyUI 源码 comfy_extras/nodes_minimax_h3.py 与官方模板
（Comfy-Org/workflow_templates 的 video_minimax_h3_i2v.json）写：UNETLoader /
CLIPLoader / VAELoader / MiniMaxH3ImageToVideo / MiniMaxH3ReferenceToVideo /
SamplerCustomAdvanced / VAEDecodeAudio / CreateVideo … 输入名也照抄，
这样 `reconcile_graph()` 的「删掉不认识的输入」「报告缺的必需输入」
「删到要紧输入就报错」三条分支都能真的被走到。

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

# 真实的 H3 节点清单（类名 + 输入名都照 ComfyUI 源码 comfy_extras/nodes_minimax_h3.py）。
# 每个 required 都写成 [类型, 选项] 的 ComfyUI 格式。
def _req(*names: str) -> dict:
    return {n: [["*"], {}] for n in names}


# 首尾帧驱动节点（官方源码里的 MiniMaxH3ImageToVideo）：
#   required = clip / vae / prompt / width / height / length
#   optional = first_frame / last_frame
# 注意它**没有** noise_seed、audio_vae —— 种子归 RandomNoise，音频归 VAEDecodeAudio。
_H3_I2V = {
    "input": {
        "required": _req("clip", "vae", "prompt", "width", "height", "length"),
        "optional": _req("first_frame", "last_frame"),
    },
    "output": ["CONDITIONING", "LATENT"],
}

# 参考驱动节点（MiniMaxH3ReferenceToVideo）：参考图是 Autogrow，展开成 ref_image_0..9
_H3_REF = {
    "input": {
        "required": _req("clip", "prompt", "width", "height", "length"),
        "optional": {**_req("vae", "audio_vae", "ref_image_size"),
                     **_req(*[f"ref_image_{i}" for i in range(10)])},
    },
    "output": ["CONDITIONING", "LATENT"],
}

OBJECT_INFO: dict = {
    "UNETLoader": {"input": {"required": _req("unet_name", "weight_dtype")},
                   "output": ["MODEL"]},
    "CLIPLoader": {"input": {"required": _req("clip_name", "type", "device")},
                   "output": ["CLIP"]},
    "VAELoader": {"input": {"required": _req("vae_name")}, "output": ["VAE"]},
    "MiniMaxH3ImageToVideo": _H3_I2V,
    "MiniMaxH3ReferenceToVideo": _H3_REF,
    "KSamplerSelect": {"input": {"required": _req("sampler_name")}, "output": ["SAMPLER"]},
    "BasicScheduler": {"input": {"required": _req("model", "scheduler", "steps", "denoise")},
                       "output": ["SIGMAS"]},
    "BasicGuider": {"input": {"required": _req("model", "conditioning")}, "output": ["GUIDER"]},
    "RandomNoise": {"input": {"required": _req("noise_seed")}, "output": ["NOISE"]},
    "SamplerCustomAdvanced": {
        "input": {"required": _req("noise", "guider", "sampler", "sigmas", "latent_image")},
        "output": ["LATENT"],
    },
    "VAEDecode": {"input": {"required": _req("samples", "vae")}, "output": ["IMAGE"]},
    "VAEDecodeAudio": {"input": {"required": _req("samples", "vae")}, "output": ["AUDIO"]},
    "CreateVideo": {"input": {"required": _req("images", "fps"),
                              "optional": _req("audio", "bit_depth")},
                    "output": ["VIDEO"]},
    "SaveVideo": {"input": {"required": _req("video", "filename_prefix", "format", "codec")},
                  "output": []},
    "LoadImage": {"input": {"required": _req("image", "upload")}, "output": ["IMAGE"]},
    "LoraLoaderModelOnly": {"input": {"required": _req("model", "lora_name", "strength_model")},
                            "output": ["MODEL"]},
    # 干扰项：名字里带 H3 / MiniMax，但它不是核心生成节点。
    # 「H3 是否就绪」不该被这种东西骗过去。
    "MiniMaxH3SageAttentionPatch": {"input": {"required": _req("model")}, "output": ["MODEL"]},
    "MiniMaxH3EasyCache": {"input": {"required": _req("model")}, "output": ["MODEL"]},
}

# 老一版 ComfyUI：有参考节点，但参考图输入名还是旧的（没有 ref_image_*）。
# 这种情况必须**报错**，不能默默出片 —— 否则用户以为参考图生效了。
OBJECT_INFO_OLD_REF: dict = {
    **OBJECT_INFO,
    "MiniMaxH3ReferenceToVideo": {
        "input": {"required": _req("clip", "prompt", "width", "height", "length"),
                  "optional": _req("vae", "audio_vae", "ref_image_size")},
        "output": ["CONDITIONING", "LATENT"],
    },
}

_state: dict = {"submitted": [], "history_hits": 0, "downloaded": 0, "hits_by_id": {}}


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
            seen = _state["hits_by_id"]
            seen[pid] = seen.get(pid, 0) + 1
            # 每个任务前两次假装还在跑，第三次给结果 —— 覆盖真实的轮询行为
            if seen[pid] <= 2:
                return self._json({})
            # 从提交的图里找出真正的 SaveVideo 节点 id，别写死
            save_id = _state.get("save_node_id") or "15"
            return self._json({pid: {
                "status": {"status_str": "success", "completed": True, "messages": []},
                "outputs": {save_id: {"gifs": [
                    {"filename": "aiverse_h3_00001_.mp4", "subfolder": "aiverse",
                     "type": "output"}
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
            graph = body.get("prompt") or {}
            for nid, node in graph.items():
                if node.get("class_type") == "SaveVideo":
                    _state["save_node_id"] = nid
            _state["n"] = _state.get("n", 0) + 1
            return self._json({"prompt_id": f"mock-prompt-{_state['n']}",
                               "number": _state["n"], "node_errors": {}})
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> int:
    from backend.providers.h3_workflows import (
        DEFAULT_NODE_MAP, autodetect_node_map, build_graph, detect_model_files,
        frames_for_seconds, h3_available, reconcile_graph, steps_for_lora,
    )
    from backend.providers.media import H3ComfyUIProvider, _PORT_CACHE

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)
    _PORT_CACHE.clear()   # 别让之前的负缓存影响判断

    url = f"http://127.0.0.1:{PORT}"
    fail: list[str] = []

    def need(cond, msg, label=""):
        print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
        if not cond:
            fail.append(msg)

    # 假 ComfyUI 的 models/ 目录，用来验证「现场扫权重」
    tmp = Path(tempfile.mkdtemp(prefix="aiverse_h3_"))
    for sub, names in (
        ("diffusion_models", ["minimax_h3_fl2va_pruned_fp8_scaled.safetensors"]),
        ("text_encoders", ["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"]),
        ("vae", ["minimax_h3_video_vae_int8_convrot.safetensors",
                 "minimax_h3_audio_vae_fp32.safetensors"]),
        ("loras", ["minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"]),
    ):
        d = tmp / sub
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"\x00" * 16)

    print("\n[1/9] 权重文件名识别（决定 ComfyUI 从哪加载）")
    mf = detect_model_files(tmp)
    need(mf.get("unet_fl2va") == "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
         f"unet_fl2va 识别失败：{mf.get('unet_fl2va')}",
         f"unet_fl2va → {mf.get('unet_fl2va')}")
    need(mf.get("text_encoder") == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
         f"text_encoder 识别失败：{mf.get('text_encoder')}",
         f"text_encoder → {mf.get('text_encoder')}")
    need(mf.get("vae_video", "").endswith("video_vae_int8_convrot.safetensors"),
         f"vae_video 认错文件（两个 VAE 同名容易串）：{mf.get('vae_video')}",
         f"vae_video → {mf.get('vae_video')}")
    need(mf.get("vae_audio", "").endswith("audio_vae_fp32.safetensors"),
         f"vae_audio 认错文件：{mf.get('vae_audio')}",
         f"vae_audio → {mf.get('vae_audio')}")
    need(bool(mf.get("lora_fl2v")), "Turbo LoRA 没被识别出来")

    print("\n[2/9] 帧数换算（H3 要求落在 17k+5 栅格）")
    for sec, want in ((5.0, 124), (4.0, 107), (6.0, 141), (1.0, 39)):
        got = frames_for_seconds(sec, 24)
        need(got % 17 == 5, f"{sec}s → {got} 帧，不在 17k+5 栅格上",
             f"{sec}s → {got} 帧（{got % 17} = 5 ✓）")

    print("\n[3/9] 健康检查 / 节点识别")
    p = H3ComfyUIProvider(base_url=url, meta={"steps": 8, "fps": 24,
                                              "model_files": mf})
    h = p.health()
    need(h.get("ok") is True, f"health 应就绪，实际 {h}",
         f"就绪 · 核心节点 {h.get('core_node')} · "
         f"sage_attention={h.get('acceleration', {}).get('sage_attention')} "
         f"easy_cache={h.get('acceleration', {}).get('easy_cache')}")
    need(h.get("core_node") == "MiniMaxH3ImageToVideo",
         f"核心节点识别失败：{h.get('core_node')}",
         "核心节点 → MiniMaxH3ImageToVideo")
    nm = p.node_map()
    need(nm.get("model_loader") == "UNETLoader",
         f"model_loader 识别失败：{nm.get('model_loader')}",
         f"model_loader → {nm.get('model_loader')}")
    need(nm.get("text_encode") == "CLIPLoader",
         f"text_encode 识别失败：{nm.get('text_encode')}",
         f"text_encode → {nm.get('text_encode')}")
    need(nm.get("audio_decode") == "VAEDecodeAudio",
         f"audio_decode 识别失败：{nm.get('audio_decode')}",
         f"audio_decode → {nm.get('audio_decode')}")
    # 两种驱动方式是**两个不同的节点类**，不能识别成同一个
    need(h.get("ref_core_node") == "MiniMaxH3ReferenceToVideo",
         f"参考节点识别失败：{h.get('ref_core_node')}",
         f"参考驱动节点 → {h.get('ref_core_node')}（与首尾帧节点不同类）")
    need(nm.get("h3_core_ref") == "MiniMaxH3ReferenceToVideo"
         and nm.get("h3_core") == "MiniMaxH3ImageToVideo",
         f"h3_core / h3_core_ref 混了：{nm.get('h3_core')} / {nm.get('h3_core_ref')}",
         "h3_core=ImageToVideo、h3_core_ref=ReferenceToVideo，各归各的")
    # 怎么证明「真的读了 /object_info」而不是照抄默认值：
    # 把核心节点改名成另一个合法名字，看识别结果跟不跟着变。
    renamed = {("MiniMaxH3TextToVideo" if k == "MiniMaxH3ImageToVideo" else k): v
               for k, v in OBJECT_INFO.items()}
    nm2 = autodetect_node_map(renamed)
    need(nm2.get("h3_core") == "MiniMaxH3TextToVideo",
         f"改名后没跟着变，说明没真读清单：{nm2.get('h3_core')}",
         "核心节点改名后识别结果跟着变（确认真的读了 /object_info）")
    need(p.meta.get("object_info_count") == len(OBJECT_INFO),
         f"没记录清单规模：{p.meta.get('object_info_count')}",
         f"读到 {p.meta.get('object_info_count')} 个节点定义")

    print("\n[4/9] reconcile：多传的输入会被删掉，缺必需输入会被报出来")
    bogus = {"1": {"inputs": {"unet_name": "a.safetensors",
                              "weight_dtype": "default", "不存在的参数": 1},
                   "class_type": "UNETLoader"}}
    rep = reconcile_graph(bogus, OBJECT_INFO)
    need(rep["dropped"] == ["UNETLoader.不存在的参数"],
         f"多余输入没被删掉：{rep['dropped']}",
         f"删掉了多余的输入：{rep['dropped']}")
    need(rep["ok"] is True, f"删完应该算通过，实际 {rep}",
         "删完多余输入后判定通过")
    missing = reconcile_graph({"1": {"inputs": {}, "class_type": "UNETLoader"}}, OBJECT_INFO)
    need(not missing["ok"] and "UNETLoader.unet_name" in missing["missing_required"],
         f"缺必需输入没被报出来：{missing}",
         f"缺必需输入被报出：{missing['missing_required'][:3]}")
    gone = reconcile_graph({"1": {"inputs": {}, "class_type": "NotInstalledNode"}}, OBJECT_INFO)
    need(not gone["ok"] and "NotInstalledNode" in gone["missing_class"],
         f"缺节点没被报出来：{gone}", "缺节点被报出：NotInstalledNode")
    # 最要命的一条：输入被删掉时 ComfyUI 照样出片，只是出的不是你想要的。
    # 老版 ComfyUI 没有 ref_image_* 时，必须判不 ok，而不是默默生成一个「没有参考图」的片子。
    _ref_mf = {"unet_ref2va": "u.safetensors", "text_encoder": "c.safetensors",
               "vae_video": "vv.safetensors", "vae_audio": "va.safetensors"}
    _ref_nm = {"h3_core_ref": "MiniMaxH3ReferenceToVideo"}
    _ref_params = {"prompt": "p", "seconds": 2, "model_files": _ref_mf,
                   "references": ["ref.png"]}
    rep_old = reconcile_graph(build_graph("ref2va", _ref_params, _ref_nm),
                              OBJECT_INFO_OLD_REF)
    need(rep_old["silent_risk"] and not rep_old["ok"],
         f"参考图输入被删掉了却还判通过（会静默出一版没参考图的片）：{rep_old}",
         f"参考图输入被删 → 判失败并点出 {rep_old['silent_risk']}")
    # 反过来：输入名对得上时不该误报
    rep_new = reconcile_graph(build_graph("ref2va", _ref_params, _ref_nm), OBJECT_INFO)
    need(rep_new["ok"] and not rep_new["silent_risk"] and not rep_new["dropped"],
         f"输入名对得上却误报：{rep_new}", "ref_image_0 被正确接受，不误报")

    print("\n[5/9] H3 就绪判定不会被「名字里带 h3」的干扰节点骗到")
    without_core = {k: v for k, v in OBJECT_INFO.items()
                    if k != "MiniMaxH3ImageToVideo"}
    av = h3_available(without_core)
    need(av["available"] is False,
         f"没有核心节点却报就绪：{av.get('core_node')}",
         f"缺核心节点时如实报未就绪（干扰节点 {len(av['related_nodes'])} 个没骗过它）")
    need(h3_available(OBJECT_INFO)["available"] is True, "有核心节点时应报就绪")

    print("\n[6/9] 生成（提交 → 轮询 → 取回 MP4）")
    t0 = time.time()
    res = p.generate("一个雨夜的药铺，掌柜在柜台后抬眼", seconds=4.0, aspect="16:9",
                     resolution="720p", seed=12345)
    dt = time.time() - t0
    need(bool(res.get("path")), f"应返回本地文件路径，实际 {res}")
    local = Path(res["path"]) if res.get("path") else None
    need(bool(local and local.exists()), "下载的文件应真实存在", f"MP4 已落到 {local}")
    need(bool(local) and local.stat().st_size == len(FAKE_MP4),
         f"文件大小应为 {len(FAKE_MP4)}，实际 {local.stat().st_size if local else 0}",
         f"文件大小 {local.stat().st_size} B，与 /view 返回一致")
    need(_state["downloaded"] == 1, f"/view 应被调用 1 次，实际 {_state['downloaded']}")
    need(_state["history_hits"] >= 3,
         f"应轮询到第 3 次才拿到结果，实际 {_state['history_hits']} 次",
         f"轮询 {_state['history_hits']} 次后拿到结果（前两次正确判为「还在跑」）")
    print(f"     生成耗时 {dt:.1f}s")

    print("\n[7/9] 提交给 ComfyUI 的图是否合法")
    need(len(_state["submitted"]) == 1, "应只提交 1 次")
    graph = _state["submitted"][0].get("prompt", {}) if _state["submitted"] else {}
    need(len(graph) >= 14, f"工作流节点数偏少：{len(graph)}",
         f"工作流共 {len(graph)} 个节点")
    classes = {v.get("class_type") for v in graph.values()}
    for want in ("UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3ImageToVideo",
                 "SamplerCustomAdvanced", "VAEDecode", "VAEDecodeAudio",
                 "CreateVideo", "SaveVideo"):
        need(want in classes, f"工作流里缺少节点 {want}（现有 {sorted(classes)}）",
             f"含节点 {want}")
    need(classes <= set(OBJECT_INFO),
         f"工作流用了假 ComfyUI 里不存在的节点：{sorted(classes - set(OBJECT_INFO))}",
         "工作流只用真实存在的节点类名")
    # 权重文件名必须进图，不然 ComfyUI 找不到模型
    unet = next((v["inputs"]["unet_name"] for v in graph.values()
                 if v.get("class_type") == "UNETLoader"), "")
    need(unet == "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
         f"UNETLoader 没用识别出来的权重：{unet}",
         f"UNETLoader → {unet}")
    core = next((v for v in graph.values()
                 if v.get("class_type") == "MiniMaxH3ImageToVideo"), {})
    need(core.get("inputs", {}).get("length", 0) % 17 == 5,
         f"帧数不在 17k+5 栅格：{core.get('inputs', {}).get('length')}",
         f"帧数 {core.get('inputs', {}).get('length')}（4 秒 @24fps）")
    need(core.get("inputs", {}).get("width", 0) % 32 == 0
         and core.get("inputs", {}).get("height", 0) % 32 == 0,
         f"宽高应为 32 的倍数，实际 "
         f"{core.get('inputs', {}).get('width')}x{core.get('inputs', {}).get('height')}",
         f"分辨率 {core['inputs']['width']}x{core['inputs']['height']}（32 的倍数）")
    # 图上不该出现官方节点不认识的输入 —— 有的话说明我们是靠 reconcile「擦屁股」
    # 才提交成功的，哪天 reconcile 放宽就直接被 ComfyUI 拒单。
    # 这里直接查 build_graph 的原始产物，绕开 media.py 里那道 reconcile。
    raw = build_graph("fl2va", {"prompt": "p", "seconds": 4, "model_files": mf,
                                "use_lora": True, "seed": 1})
    need(reconcile_graph(raw, OBJECT_INFO)["dropped"] == [],
         f"build_graph 产出的图里有官方节点不认识的输入："
         f"{reconcile_graph(raw, OBJECT_INFO)['dropped']}",
         "build_graph 产出的图零多余输入（不靠 reconcile 兜底）")
    # 步数要跟 Turbo LoRA 的「几步版」对上：仓库里这个是 4step 版。
    # 用 raw（没显式指定 steps）来看默认推导结果。
    sched = next(v["inputs"] for v in raw.values()
                 if v.get("class_type") == "BasicScheduler")
    need(sched.get("steps") == steps_for_lora(mf.get("lora_fl2v")) == 4,
         f"步数与 LoRA 版本不匹配：steps={sched.get('steps')} "
         f"lora={mf.get('lora_fl2v')}",
         f"步数 {sched.get('steps')} 与 LoRA（4step 版）自动匹配")
    # 不带 LoRA 时回到 20 步
    no_lora = build_graph("fl2va", {"prompt": "p", "seconds": 4, "model_files": mf,
                                    "use_lora": False})
    sched2 = next(v["inputs"] for v in no_lora.values()
                  if v.get("class_type") == "BasicScheduler")
    need(sched2.get("steps") == 20, f"不带 LoRA 应为 20 步，实际 {sched2.get('steps')}",
         "不带 LoRA → 20 步")

    print("\n[8/9] manifest 内容")
    m = res.get("manifest", {})
    need(m.get("backend") == "comfyui", "manifest.backend 应为 comfyui")
    need(m.get("prompt_id") == "mock-prompt-1", "manifest.prompt_id 应记录")
    need(m.get("status") == "rendered", "manifest.status 应为 rendered")
    need(m.get("seed") == 12345, f"seed 应透传，实际 {m.get('seed')}")
    need(m.get("variant") == "fl2va", f"无参考图时应走 fl2va，实际 {m.get('variant')}",
         "无参考图 → 走 fl2va 变体")
    need(bool(m.get("model_files")), "manifest 应记下用了哪些权重文件",
         f"manifest 记下权重：{list((m.get('model_files') or {}))[:3]}…")

    print("\n[9/9] 带参考图（ref2va 变体）+ 权重缺失时的报错是否可读")
    ref = Path(tempfile.gettempdir()) / "aiverse_h3_ref_test.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    p2 = H3ComfyUIProvider(base_url=url, meta={
        "steps": 8, "fps": 24, "model_files": mf})
    res2 = p2.generate("同一个掌柜，推近景", reference=str(ref), seconds=3.0,
                       aspect="9:16", resolution="720p", seed=777)
    need(res2.get("manifest", {}).get("variant") == "ref2va",
         f"带参考图时应走 ref2va，实际 {res2.get('manifest', {}).get('variant')}",
         "带参考图 → 走 ref2va 变体")
    graph2 = _state["submitted"][1].get("prompt", {}) if len(_state["submitted"]) > 1 else {}
    loaders = [v for v in graph2.values() if v.get("class_type") == "LoadImage"]
    need(bool(loaders), "ref2va 工作流里应包含图片加载节点",
         f"ref2va 工作流含 {len(loaders)} 个图片节点")
    # 参考驱动必须用 MiniMaxH3ReferenceToVideo，而不是首尾帧那个节点
    need("MiniMaxH3ReferenceToVideo" in {v.get("class_type") for v in graph2.values()},
         f"ref2va 没走参考节点，实际节点："
         f"{sorted({v.get('class_type') for v in graph2.values()})}",
         "ref2va → 用的是 MiniMaxH3ReferenceToVideo（不是 ImageToVideo）")
    core2 = next((v for v in graph2.values()
                  if v.get("class_type") == "MiniMaxH3ReferenceToVideo"), {})
    need(any(k.startswith("ref_image_") for k in (core2.get("inputs") or {})),
         f"参考图没接到参考输入上（会静默生成一版没参考图的片）："
         f"{sorted((core2.get('inputs') or {}))}",
         f"参考图接在 ref_image_0 上（官方 Autogrow 命名）")
    need(core2.get("inputs", {}).get("height", 0) > core2.get("inputs", {}).get("width", 0),
         f"9:16 竖屏应满足高>宽，实际 {core2.get('inputs', {}).get('width')}"
         f"x{core2.get('inputs', {}).get('height')}",
         f"9:16 竖屏 → {core2['inputs']['width']}x{core2['inputs']['height']}")

    # 权重一个都没有 → 报错必须说清「去环境部署里下」，而不是丢个 KeyError
    p3 = H3ComfyUIProvider(base_url=url, meta={"model_dir": str(tmp / "empty")})
    try:
        p3.generate("测试", seconds=2.0)
        need(False, "没有权重时应该报错")
    except RuntimeError as e:
        need("环境部署" in str(e), f"权重缺失的报错不够可读：{e}",
             f"权重缺失 → 「{str(e)[:36]}…」")
    except Exception as e:
        need(False, f"权重缺失时应抛 RuntimeError，实际 {type(e).__name__}: {e}")

    ref.unlink(missing_ok=True)
    srv.shutdown()

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("✓ H3 生成链路端到端通过（假 ComfyUI，节点名与输入名照官方模板）")
    print(f"  临时文件：{local}")
    print("  真实环境里把 base_url 指向装了 H3 的 ComfyUI 即可，逻辑完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
