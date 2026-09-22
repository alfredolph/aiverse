"""MiniMax H3 的 ComfyUI 工作流模板与节点自动识别。

已核实（2026-09）：
  * ComfyUI **原生支持** MiniMax H3，需要 ComfyUI ≥ 0.30.0，官方工作流模板在
    Comfy-Org/workflow_templates 的 templates/video_minimax_h3_{t2v,i2v,r2v}.json
  * 节点类名就是 ComfyUI 内置的那几个（UNETLoader / CLIPLoader / VAELoader /
    MiniMaxH3ImageToVideo / SamplerCustomAdvanced …），**不是**某个社区节点包自创的名字。
    本文件早先写的 MiniMaxH3Loader / MiniMaxH3Sampler / EmptyMiniMaxH3LatentVideo
    都是猜的，装上也不存在 —— 这一版换成从官方模板里读出来的真名。
  * 权重来自 Comfy-Org/MiniMax-H3（按 ComfyUI 的 models/ 结构切好的单文件）：
      diffusion_models/minimax_h3_{fl2va,ref2va}_pruned_{int8_convrot,fp8_scaled,bf16}.safetensors
      text_encoders/qwen3vl_32b_minimax_h3_{nvfp4_awq,int8_convrot,bf16}.safetensors
      vae/minimax_h3_video_vae_{int8_convrot,fp16}.safetensors
      vae/minimax_h3_audio_vae_fp32.safetensors
      loras/minimax_h3_{fl2v,ref2v}_turbo_*step_*.safetensors
  * 帧数有硬约束：24fps 下必须是 `17k+5` 栅格，官方模板的换算式是
      max(5, round(seconds * 24)) + (5 - (max(5, round(seconds*24)) % 17)) % 17
    宽高要是 32 的倍数。

仍然保留「可覆盖的节点映射 + 自动识别」：ComfyUI 大版本更新时类名可能变，
或者用户装了带 H3 的整合包，所以不把映射写死到无法调整。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 默认节点映射
# 键 = 逻辑角色，值 = ComfyUI 节点 class_type。可用 autodetect 覆盖。
# 这些名字取自 ComfyUI 官方 H3 模板（video_minimax_h3_i2v.json），不是猜的。
DEFAULT_NODE_MAP: dict[str, str] = {
    "model_loader": "UNETLoader",          # 扩散模型（widget: unet_name, weight_dtype）
    "text_encode": "CLIPLoader",           # 文本编码器（widget: clip_name, type=minimax）
    "vae_video": "VAELoader",              # 视频 VAE
    "vae_audio": "VAELoader",              # 音频 VAE（同一个类，两个实例）
    # H3 有**两个**核心节点，别混用：
    #   MiniMaxH3ImageToVideo      —— 首/尾帧驱动（仓库里的 FL2VA），输入 first_frame / last_frame
    #   MiniMaxH3ReferenceToVideo  —— 参考图/参考视频驱动（仓库里的 Ref2VA），输入 ref_image_0..N
    # 早先只映射了一个，ref2va 也走 ImageToVideo 并塞了个不存在的 reference_images，
    # 结果被 reconcile 静默删掉 —— 看着出片了，其实参考图根本没生效。
    "h3_core": "MiniMaxH3ImageToVideo",        # 首尾帧驱动（FL2VA）
    "h3_core_ref": "MiniMaxH3ReferenceToVideo",  # 参考驱动（Ref2VA）
    "sampler_select": "KSamplerSelect",
    "scheduler": "BasicScheduler",
    "guider": "BasicGuider",
    "sampler": "SamplerCustomAdvanced",
    "noise": "RandomNoise",
    "vae_decode": "VAEDecode",
    "audio_decode": "VAEDecodeAudio",
    "video_output": "SaveVideo",
    "video_assemble": "CreateVideo",
    "load_image": "LoadImage",
    "lora": "LoraLoaderModelOnly",
}

# 自动识别时按优先级匹配的关键词（越靠前越优先）
# 注意：h3_core 这里**不能**放泛化的 "minimaxh3" 兜底 ——
# MiniMaxH3SageAttentionPatch / MiniMaxH3EasyCache 这些名字里也带，
# 一兜底就会把加速补丁节点当成核心生成节点，然后报「H3 就绪」却生成不出东西。
NODE_HINTS: dict[str, list[str]] = {
    # 注意顺序：h3_core 里**不能**放 referencetovideo，否则自动识别会把参考节点
    # 当成首尾帧节点（两者都能生成，但输入名完全不同）。
    "h3_core": ["minimaxh3imagetovideo", "minimaxh3fl2v", "minimaxh3texttovideo",
                "minimaxh3vace", "minimaxh3generate"],
    "h3_core_ref": ["minimaxh3referencetovideo", "minimaxh3ref2v", "minimaxh3reference2video"],
    "model_loader": ["unetloader", "minimaxh3loader", "h3loader", "modelloader"],
    "text_encode": ["cliploader", "minimaxh3textencoderloader", "textencoderloader"],
    "vae_video": ["vaeloader"],
    "vae_audio": ["vaeloader"],
    "sampler": ["samplercustomadvanced", "minimaxh3sampler", "h3sampler"],
    "sampler_select": ["ksamplerselect"],
    "scheduler": ["basicscheduler"],
    "guider": ["basicguider"],
    "noise": ["randomnoise"],
    "video_output": ["savevideo", "createvideo", "vhs_videocombine", "savewebm"],
    "video_assemble": ["createvideo"],
    "load_image": ["loadimage"],
    "vae_decode": ["vaedecode"],
    "audio_decode": ["vaedecodeaudio"],
    "lora": ["loraloadermodelonly"],
}

# 关键词兜底：不同 ComfyUI 版本 / 整合包的类名会「中间插词」，
# 例如 MiniMaxH3EmptyLatentVideo —— 单纯子串匹配永远命中不了
# `minimaxh3latentvideo`，所以再给一层「必须满足 + 加权加分」的规则。
#   must     : 必须全部出现
#   must_any : 至少出现一个
#   any      : 出现越多分越高（用来在多个候选里挑最像的）
NODE_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "h3_core": {"must_any": ["imagetovideo", "texttovideo"],
                "any": ["minimax", "h3", "fl2v"]},
    "h3_core_ref": {"must_any": ["referencetovideo", "ref2v", "reference2video"],
                    "any": ["minimax", "h3"]},
    "model_loader": {"must": ["loader"], "any": ["minimax", "h3", "unet", "model"]},
    "text_encode": {"must": ["loader"], "any": ["clip", "text", "encoder", "minimax", "h3"]},
    "vae_video": {"must": ["vaeloader"], "any": ["video", "minimax", "h3"]},
    "vae_audio": {"must": ["vaeloader"], "any": ["audio", "minimax", "h3"]},
    "sampler": {"must_any": ["samplercustom", "sampler"], "any": ["minimax", "h3", "advanced"]},
    "sampler_select": {"must": ["sampler"], "any": ["select"]},
    "scheduler": {"must": ["scheduler"]},
    "guider": {"must": ["guider"]},
    "noise": {"must": ["noise"]},
    "video_output": {"must_any": ["savevideo", "createvideo",
                                  "videocombine", "savewebm", "saveanimated"]},
    "video_assemble": {"must_any": ["createvideo", "videocombine"]},
    "load_image": {"must": ["loadimage"]},
    "vae_decode": {"must": ["vaedecode"], "any": []},
    "audio_decode": {"must_any": ["vaedecodeaudio", "audioddecode"]},
    "lora": {"must": ["lora"], "any": ["modelonly", "model"]},
}


def _best_by_keywords(lower: dict[str, str], kw: dict[str, list[str]]) -> str | None:
    must = kw.get("must") or []
    must_any = kw.get("must_any") or []
    any_ = kw.get("any") or []
    best, best_score = None, -1
    for low, orig in lower.items():
        if must and not all(m in low for m in must):
            continue
        if must_any and not any(m in low for m in must_any):
            continue
        score = sum(1 for a in any_ if a in low)
        if any_ and score == 0:
            continue
        if score > best_score:
            best, best_score = orig, score
    return best


def autodetect_node_map(object_info: dict[str, Any],
                        current: dict[str, str] | None = None) -> dict[str, str]:
    """从 ComfyUI /object_info 的节点清单里推断节点映射。

    两级策略：先精确/子串匹配（快且准），命中不了再用关键词兜底，
    这样面对各种命名风格的 H3 节点包都能接上，而不是直接崩在「节点不存在」。
    """
    mapping = dict(current or DEFAULT_NODE_MAP)
    lower = {n.lower(): n for n in object_info.keys()}

    for role, hints in NODE_HINTS.items():
        hit = None
        for hint in hints:
            if hint in lower:
                hit = lower[hint]
                break
            hit = next((orig for low, orig in lower.items() if hint in low), None)
            if hit:
                break
        if not hit:
            hit = _best_by_keywords(lower, NODE_KEYWORDS.get(role) or {})
        if hit:
            mapping[role] = hit
    return mapping


def h3_available(object_info: dict[str, Any]) -> dict[str, Any]:
    """检查当前 ComfyUI 是否具备跑 H3 的节点。

    判据是「有没有 H3 的**生成**节点」，而不是「有没有哪个节点名字里带 h3」——
    后者会把 MiniMaxH3SageAttentionPatch / MarkdownNote 之类误判成就绪。
    所以这里除了看识别结果，还要再核一遍名字里确实有生成语义。
    """
    nm = autodetect_node_map(object_info)
    lower = {n.lower(): n for n in object_info.keys()}
    core = nm.get("h3_core") or ""
    ref_core = nm.get("h3_core_ref") or ""
    gen_kw = ("imagetovideo", "texttovideo", "referencetovideo", "generate")
    core_ok = bool(core) and core in object_info and any(k in core.lower() for k in gen_kw)
    # 参考节点是「加分项」：没有它也能出片，只是参考图用不了 —— 要如实报出来
    ref_ok = (bool(ref_core) and ref_core in object_info
              and any(k in ref_core.lower() for k in gen_kw)
              and ref_core != core)
    accel = {
        "sage_attention": any("sageattention" in n or "sage_attn" in n for n in lower),
        "easy_cache": any("easycache" in n for n in lower),
        "kj_nodes": any("kj" in n for n in lower),
    }
    related = sorted({n for n in object_info.keys()
                      if "h3" in n.lower() or "minimax" in n.lower()})
    return {"available": core_ok, "core_node": core if core_ok else None,
            "ref_core_node": ref_core if ref_ok else None,
            "reference_capable": ref_ok,
            "acceleration": accel, "related_nodes": related[:40],
            "comfyui_nodes": len(object_info)}


# ---------------------------------------------------------------- 权重识别
# 同一角色可能有多个精度版本共存，按「能用就行」的顺序挑：
# int8_convrot（官方首选，需 cu130）→ fp8_scaled（cu124 可用）→ pruned_bf16 → bf16
_PRECISION_ORDER = ["int8_convrot", "fp8_scaled", "pruned_bf16", "bf16", "fp16", "nvfp4_awq"]


def _pick(dirpath: Path, *must: str) -> str | None:
    if not dirpath.exists():
        return None
    cands = [f.name for f in dirpath.glob("*.safetensors")]
    for want in _PRECISION_ORDER:
        for name in cands:
            low = name.lower()
            if all(m in low for m in must) and want in low:
                return name
    for name in cands:                       # 精度认不出来就随便挑一个能用的
        if all(m in name.lower() for m in must):
            return name
    return None


def detect_model_files(models_dir: Path) -> dict[str, str]:
    """扫描 ComfyUI 的 models/，把已下载的 H3 权重按角色归类（值是文件名）。

    H3 的图必须按**文件名**去 UNETLoader / CLIPLoader / VAELoader 里选，
    名字对不上 ComfyUI 会直接判节点校验失败。所以部署完先扫一遍存进 Provider。
    """
    out: dict[str, str] = {}
    pairs = [
        ("unet_fl2va", "diffusion_models", ("fl2va",)),
        ("unet_ref2va", "diffusion_models", ("ref2va",)),
        ("text_encoder", "text_encoders", ("qwen3vl",)),
        ("vae_video", "vae", ("video_vae",)),
        ("vae_audio", "vae", ("audio_vae",)),
        ("lora_fl2v", "loras", ("fl2v", "turbo")),
        ("lora_ref2v", "loras", ("ref2v", "turbo")),
    ]
    for role, sub, must in pairs:
        name = _pick(models_dir / sub, *must)
        if name:
            out[role] = name
    return out


def frames_for_seconds(seconds: float, fps: int = 24) -> int:
    """把秒数换算成 H3 能接受的帧数。

    H3 的帧数必须落在 `17k+5` 栅格上，官方模板的式子是：
        max(5, round(seconds * fps)) + (5 - (max(5, round(seconds*fps)) % 17)) % 17
    不按这个来的话，ComfyUI 会在采样阶段报形状不匹配。
    """
    n = max(5, round(float(seconds) * int(fps)))
    return int(n + (5 - (n % 17)) % 17)


def steps_for_lora(lora_name: str | None, no_lora_steps: int = 20) -> int:
    """Turbo LoRA 是「几步版」就配几步 —— 这是 LoRA 自己定的，不是随便填的。

    官方仓库里 fl2v 有 4step 与 8step 两个 Turbo LoRA，文件名里就写着步数。
    用 4step 的 LoRA 却跑 8 步，画面会过曝/糊；不带 LoRA 则要 20 步左右。
    """
    if not lora_name:
        return int(no_lora_steps)
    low = lora_name.lower()
    for n in (2, 4, 6, 8):
        if f"{n}step" in low:
            return n
    return 8                       # 认不出来就按官方模板 turbo 档的 8 步


# ---------------------------------------------------------------- 图构建
def build_graph(kind: str = "fl2va", params: dict[str, Any] | None = None,
                node_map: dict[str, str] | None = None) -> dict[str, Any]:
    """生成 ComfyUI **API 格式**的工作流图（可以直接 POST /prompt）。

    拓扑照抄 ComfyUI 官方模板 video_minimax_h3_i2v.json 里的子图：
        UNETLoader ─┬─(LoraLoaderModelOnly)─→ BasicScheduler / BasicGuider
                    └──────────────────────→ BasicGuider
        CLIPLoader ─→ MiniMaxH3ImageToVideo ─→ BasicGuider / SamplerCustomAdvanced
        VAELoader(视频) / VAELoader(音频) ─→ VAEDecode / VAEDecodeAudio
        SamplerCustomAdvanced ─→ VAEDecode + VAEDecodeAudio ─→ CreateVideo ─→ SaveVideo

    params:
        prompt, width, height, frames, fps, steps, seed, sampler, scheduler,
        model_files（detect_model_files 的结果）、references（参考图路径列表）、
        use_lora, filename_prefix
    """
    p = params or {}
    nm = {**DEFAULT_NODE_MAP, **(node_map or {})}
    mf = p.get("model_files") or {}

    width = int(p.get("width") or 832)
    height = int(p.get("height") or 480)
    frames = int(p.get("frames") or frames_for_seconds(p.get("seconds") or 5))
    fps = int(p.get("fps") or 24)
    seed = int(p.get("seed") or 0)
    prompt = p.get("prompt") or ""
    sampler = p.get("sampler") or "res_multistep"
    scheduler = p.get("scheduler") or "simple"
    prefix = p.get("filename_prefix") or "aiverse/h3"
    use_lora = bool(p.get("use_lora")) and bool(mf.get("lora_fl2v") or mf.get("lora_ref2v"))
    lora_name = mf.get("lora_ref2v") if kind == "ref2va" else mf.get("lora_fl2v")
    if kind == "ref2va" and not mf.get("lora_ref2v"):
        lora_name = mf.get("lora_fl2v")
    use_lora = use_lora and bool(lora_name)
    # 步数：用户显式给了就听用户的，否则按 LoRA 的「几步版」走
    steps = int(p.get("steps") or 0) or steps_for_lora(lora_name if use_lora else None)

    # 宽高对齐到 32 的倍数（H3 的 VAE 有 32 倍下采样）
    width = max(256, width // 32 * 32)
    height = max(256, height // 32 * 32)

    graph: dict[str, Any] = {}

    graph["1"] = {
        "inputs": {"unet_name": mf.get("unet_ref2va" if kind == "ref2va" else "unet_fl2va")
                   or "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
                   "weight_dtype": "default"},
        "class_type": nm["model_loader"],
        "_meta": {"title": "H3 扩散模型"},
    }
    graph["2"] = {
        "inputs": {"clip_name": mf.get("text_encoder")
                   or "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                   "type": "minimax", "device": "default"},
        "class_type": nm["text_encode"],
        "_meta": {"title": "H3 文本编码器（Qwen3-VL）"},
    }
    graph["3"] = {
        "inputs": {"vae_name": mf.get("vae_video")
                   or "minimax_h3_video_vae_int8_convrot.safetensors"},
        "class_type": nm["vae_video"],
        "_meta": {"title": "视频 VAE"},
    }
    graph["4"] = {
        "inputs": {"vae_name": mf.get("vae_audio")
                   or "minimax_h3_audio_vae_fp32.safetensors"},
        "class_type": nm["vae_audio"],
        "_meta": {"title": "音频 VAE"},
    }

    # 模型可以经 Turbo LoRA 再进调度器/引导器（官方模板就是这么接的）
    model_ref: list = ["1", 0]
    if use_lora:
        graph["5"] = {
            "inputs": {"model": ["1", 0], "lora_name": lora_name,
                       "strength_model": float(p.get("lora_strength") or 1.0)},
            "class_type": nm["lora"],
            "_meta": {"title": "Turbo LoRA（加速）"},
        }
        model_ref = ["5", 0]

    # 核心节点：两种驱动方式用**不同的节点类**，输入名也不一样
    #   fl2va → MiniMaxH3ImageToVideo     ：first_frame / last_frame（可选）
    #   ref2va → MiniMaxH3ReferenceToVideo：ref_image_0 / ref_image_1 …（autogrow，可选）
    # 这两个类都**没有** noise_seed / audio_vae 输入 —— 种子归 RandomNoise 管，
    # 音频 VAE 归 VAEDecodeAudio 管。多塞进去 ComfyUI 会判校验失败。
    refs = list(p.get("references") or ([p["reference"]] if p.get("reference") else []))
    core_class = nm["h3_core"]
    core_inputs: dict[str, Any] = {"prompt": prompt, "width": width,
                                   "height": height, "length": frames}
    if kind == "ref2va":
        core_class = nm.get("h3_core_ref") or nm["h3_core"]
        # 参考节点的 vae / audio_vae 是可选输入；给上更稳（不给也行）
        core_inputs.update({"clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0]})
        for i, ref in enumerate(refs[:10]):
            nid = str(20 + i)
            graph[nid] = {
                "inputs": {"image": ref, "upload": "image"},
                "class_type": nm["load_image"],
                "_meta": {"title": f"参考图 {i + 1}"},
            }
            core_inputs[f"ref_image_{i}"] = [nid, 0]
    else:
        # 首尾帧节点：clip / vae 必填；first_frame / last_frame 可选
        core_inputs.update({"clip": ["2", 0], "vae": ["3", 0]})
        img_nodes: list[list] = []
        for i, ref in enumerate(refs[:2]):
            nid = str(20 + i)
            graph[nid] = {
                "inputs": {"image": ref, "upload": "image"},
                "class_type": nm["load_image"],
                "_meta": {"title": ("首帧" if i == 0 else "尾帧")},
            }
            img_nodes.append([nid, 0])
        if img_nodes:
            core_inputs["first_frame"] = img_nodes[0]
        if len(img_nodes) > 1:
            core_inputs["last_frame"] = img_nodes[1]
    graph["6"] = {
        "inputs": core_inputs,
        "class_type": core_class,
        "_meta": {"title": "H3 核心（出片 + 原生音频）"},
    }

    graph["7"] = {"inputs": {"sampler_name": sampler},
                  "class_type": nm["sampler_select"],
                  "_meta": {"title": "采样器"}}
    graph["8"] = {"inputs": {"model": model_ref, "scheduler": scheduler,
                             "steps": steps, "denoise": 1.0},
                  "class_type": nm["scheduler"], "_meta": {"title": "调度器"}}
    graph["9"] = {"inputs": {"model": model_ref, "conditioning": ["6", 0]},
                  "class_type": nm["guider"], "_meta": {"title": "引导器"}}
    graph["10"] = {"inputs": {"noise_seed": seed},
                   "class_type": nm["noise"], "_meta": {"title": "噪声"}}
    graph["11"] = {
        "inputs": {"noise": ["10", 0], "guider": ["9", 0], "sampler": ["7", 0],
                   "sigmas": ["8", 0], "latent_image": ["6", 1]},
        "class_type": nm["sampler"], "_meta": {"title": "采样"},
    }
    graph["12"] = {"inputs": {"samples": ["11", 0], "vae": ["3", 0]},
                   "class_type": nm["vae_decode"], "_meta": {"title": "视频解码"}}
    graph["13"] = {"inputs": {"samples": ["11", 0], "vae": ["4", 0]},
                   "class_type": nm["audio_decode"], "_meta": {"title": "音频解码"}}
    graph["14"] = {"inputs": {"images": ["12", 0], "audio": ["13", 0],
                              "fps": fps, "bit_depth": 8},
                   "class_type": nm["video_assemble"], "_meta": {"title": "合成音视频"}}
    graph["15"] = {"inputs": {"video": ["14", 0], "filename_prefix": prefix,
                              "format": "auto", "codec": "auto"},
                   "class_type": nm["video_output"], "_meta": {"title": "保存视频"}}
    return graph


# 这些输入一旦被 ComfyUI 判为「不认识」而删掉，出的片子和用户要的不是一回事
# （参考图/首尾帧直接失效、模型或 VAE 换默认）。必须报错，不能静默降级。
_MEANINGFUL_INPUTS = frozenset({
    "prompt", "width", "height", "length", "clip", "vae", "audio_vae",
    "first_frame", "last_frame", "lora_name", "strength_model", "model",
    "unet_name", "clip_name", "vae_name", "images", "audio", "fps", "video",
    "samples", "conditioning", "latent_image", "sigmas", "noise", "guider",
    "sampler", "scheduler", "steps", "sampler_name", "filename_prefix",
})


def _is_meaningful_input(name: str) -> bool:
    low = (name or "").lower()
    return low.startswith("ref_") or low in _MEANINGFUL_INPUTS


def reconcile_graph(graph: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """按 ComfyUI 实际节点定义校正图：删掉对方不认识的输入，并报告缺什么。

    为什么必须有这一步：ComfyUI 在 /prompt 阶段会严格校验输入名，多一个不存在
    的参数就直接拒单。而节点输入名会随 ComfyUI 版本变（H3 是 0.30 才进的），
    我们不可能把所有版本都背下来 —— 所以提交前拿 /object_info 对一遍。

    **但是「删掉」不能是静默的**：像 reference_images / first_frame / vae 这类输入
    一旦被删，ComfyUI 照样能出片，只是出的不是你想要的（参考图根本没生效）。
    所以这类输入被删时直接判不 ok，让上层报错，而不是给用户一个「看着成功了」的假结果。

    返回 {"ok": bool, "dropped": [...], "silent_risk": [...],
          "missing_class": [...], "missing_required": [...]}
    """
    report: dict[str, Any] = {"dropped": [], "silent_risk": [], "missing_class": [],
                              "missing_required": [], "ok": False}
    for node in graph.values():
        ct = node.get("class_type")
        spec = object_info.get(ct)
        if not spec:
            report["missing_class"].append(ct)
            continue
        inp = spec.get("input") or {}
        required = inp.get("required") or spec.get("required") or {}
        optional = inp.get("optional") or spec.get("optional") or {}
        allowed = set(required) | set(optional)
        if not allowed:
            continue                                   # 拿不到定义就别乱删
        given = node.get("inputs") or {}
        for k in list(given):
            if k not in allowed:
                given.pop(k)
                report["dropped"].append(f"{ct}.{k}")
                if _is_meaningful_input(k):
                    report["silent_risk"].append(f"{ct}.{k}")
        for k, v in required.items():
            if k in given:
                continue
            # required 项带 default 的，不给也能跑
            if (isinstance(v, (list, tuple)) and len(v) > 1
                    and isinstance(v[1], dict) and "default" in v[1]):
                continue
            report["missing_required"].append(f"{ct}.{k}")
    report["ok"] = (not report["missing_class"] and not report["missing_required"]
                    and not report["silent_risk"])
    return report


def ui_workflow(kind: str, graph: dict[str, Any]) -> dict[str, Any]:
    """把 API 图包一层，导出成可在 ComfyUI 里直接打开的文件。"""
    return {
        "last_node_id": max((int(k) for k in graph if k.isdigit()), default=0),
        "last_link_id": 0,
        "nodes": [
            {"id": int(nid), "type": n["class_type"], "title": n.get("_meta", {}).get("title", ""),
             "widgets_values": list(n["inputs"].values()), "inputs": [], "outputs": [],
             "pos": [200 + (i % 4) * 320, 120 + (i // 4) * 240], "size": [280, 120],
             "flags": {}, "order": i, "mode": 0}
            for i, (nid, n) in enumerate(graph.items())
        ],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {"aiverse": {"kind": kind, "note": "由 AIVerse 自动生成，可在此微调节点"}},
        "version": 0.4,
    }


def export_templates(target: Path) -> list[Path]:
    """把 FL2VA / Ref2VA 两套模板写到 ComfyUI 的 workflows 目录。

    同时留一份 **API 格式**的图（api_graph）：ComfyUI 里打开的 UI 文件是给人看的，
    而 AIVerse 提交任务用的是 api_graph，两者都放进来便于对照排查。
    """
    target.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    demo_files = {
        "unet_fl2va": "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
        "unet_ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        "text_encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "vae_video": "minimax_h3_video_vae_int8_convrot.safetensors",
        "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
        "lora_fl2v": "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
        "lora_ref2v": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
    }
    for kind, name in (("fl2va", "H3-文生视频-FL2VA"), ("ref2va", "H3-参考生视频-Ref2VA")):
        graph = build_graph(kind, {
            "prompt": "在此填写提示词", "seconds": 5, "fps": 24,
            "width": 864, "height": 480, "steps": 20,
            "model_files": demo_files, "use_lora": True,
        })
        payload = {
            "aiverse_template": True,
            "kind": kind,
            "node_map": DEFAULT_NODE_MAP,
            "api_graph": graph,
            "ui_workflow": ui_workflow(kind, graph),
            "usage": [
                "1. 本模板的节点类名取自 ComfyUI 官方 H3 模板（需 ComfyUI ≥ 0.30.0）",
                "2. 首尾帧驱动 = MiniMaxH3ImageToVideo；参考图驱动 = MiniMaxH3ReferenceToVideo",
                "   两者是**不同节点**，输入名也不同（first_frame / ref_image_0）",
                "3. 若你的 ComfyUI 版本类名不同，在 AIVerse「环境部署 → 检测 H3 环境」里自动识别",
                "4. 权重放在 ComfyUI/models 下：diffusion_models / text_encoders / vae / loras",
                "5. 帧数必须落在 17k+5 栅格（24fps 下 5 秒 = 124 帧），宽高需为 32 的倍数",
                "6. 原生输出 768p 级、自带音频轨；中文口播不稳，建议台词走 TTS 后期配音",
            ],
        }
        f = target / f"{name}.json"
        f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(f)
    return out
