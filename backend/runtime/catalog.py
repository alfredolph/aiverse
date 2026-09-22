"""组件清单 —— 本地推理环境需要装什么、多大、从哪下。

设计要点：
  * 所有来源都可替换：国内默认走 ModelScope / 清华 PyPI 镜像，海外可切 HuggingFace。
  * 体积是「下载量」，用于给用户一个诚实的时间预期。
  * 用户可在设置里改镜像源与模型仓库 ID（模型仓库地址会随官方更新变化）。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- 镜像源
MIRRORS: dict[str, dict[str, str]] = {
    "cn": {
        "name": "国内加速（推荐）",
        "pypi": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "torch_index": "https://mirror.sjtu.edu.cn/pytorch-wheels/cu124",
        "models": "modelscope",
        "uv": "https://ghproxy.net/https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip",
        "ffmpeg": "https://ghproxy.net/https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip",
    },
    "global": {
        "name": "海外直连",
        "pypi": "https://pypi.org/simple",
        "torch_index": "https://download.pytorch.org/whl/cu124",
        "models": "huggingface",
        "uv": "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip",
        "ffmpeg": "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip",
    },
}

# ---------------------------------------------------------------- 组件下载候选
# uv / ffmpeg / ComfyUI 的官方发布页都在 GitHub，而某些网络会单独屏蔽 github.com:443
# （实测：api / codeload / uploads 都通，只有 github.com 被丢包）。
# 所以每个组件都准备多个候选，下载器会依次尝试，前一个挂了自动换下一个。
#
# 顺序原则：选中的镜像源排第一，其余按「不依赖 github.com」优先。
_UV_GH = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
_FF_GH = ("https://github.com/GyanD/codexffmpeg/releases/download/7.1/"
          "ffmpeg-7.1-essentials_build.zip")
# ComfyUI 本体与 KJNodes 走源码 zip。
# 为什么不用 comfy-cli：它的 `install` 实际只认 `--skip-manager`，
# `--nvidia` / `--yes` / `install --workspace` 这几个写法在官方文档里都不存在
# （--workspace 还是全局参数，得写在子命令前面），`node install <github-url>` 也无效
# —— 它要的是 Registry ID。与其赌它，不如直接下源码 + 装 requirements.txt，
# 每一步都能自己核对。
_COMFY_GH = "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip"
_KJ_GH = "https://github.com/kijai/ComfyUI-KJNodes/archive/refs/heads/main.zip"

COMPONENT_MIRRORS: dict[str, dict[str, list[str]]] = {
    "uv": {
        "cn": [f"https://ghproxy.net/{_UV_GH}",
               f"https://gh-proxy.com/{_UV_GH}",
               _UV_GH],
        "global": [_UV_GH, f"https://ghproxy.net/{_UV_GH}"],
    },
    "ffmpeg": {
        "cn": [f"https://ghproxy.net/{_FF_GH}",
               f"https://gh-proxy.com/{_FF_GH}",
               _FF_GH],
        "global": [_FF_GH, f"https://ghproxy.net/{_FF_GH}"],
    },
    "comfyui": {
        "cn": [f"https://ghproxy.net/{_COMFY_GH}",
               f"https://gh-proxy.com/{_COMFY_GH}",
               _COMFY_GH],
        "global": [_COMFY_GH, f"https://ghproxy.net/{_COMFY_GH}"],
    },
    "kj-nodes": {
        "cn": [f"https://ghproxy.net/{_KJ_GH}",
               f"https://gh-proxy.com/{_KJ_GH}",
               _KJ_GH],
        "global": [_KJ_GH, f"https://ghproxy.net/{_KJ_GH}"],
    },
}


def component_urls(key: str, mirror: str = "cn") -> list[str]:
    """返回某组件的下载候选列表（去重，保持顺序）。"""
    table = COMPONENT_MIRRORS.get(key) or {}
    urls = list(table.get(mirror) or [])
    primary = (MIRRORS.get(mirror) or {}).get(key)
    if primary:
        urls.insert(0, primary)
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

# ---------------------------------------------------------------- 模型仓库
# 来源：Comfy-Org 为 ComfyUI 重新打包的 H3 权重，目录结构跟 ComfyUI 的 models/ 一一对应
# （diffusion_models / text_encoders / vae / loras），HF 与 ModelScope 同名同结构。
#   https://huggingface.co/Comfy-Org/MiniMax-H3
#   https://www.modelscope.cn/models/Comfy-Org/MiniMax-H3
#
# 为什么不用 MiniMaxAI/MiniMax-H3：那是原始仓库（354 GB，分 FL2VA/ Ref2VA/ 两套目录树，
# 且没有 ComfyUI 需要的单文件格式）。ComfyUI 需要的是这里这些按显存分档切好的单文件。
#
# **体积是照着实测字节数算的，不是估的**：早先这里写「量化版 26.4 GB」是拍脑袋的，
# 真实最小组合 39 GB 起步 —— 光 Qwen3-VL-32B 文本编码器就 14.6 GB，比主模型还难省。
#
# 官方建议：能用 cu130 的 PyTorch 就选 int8_convrot，用不了再退 fp8_scaled。
# 我们默认 cu124（兼容面更广），所以主模型用 fp8_scaled；两条都能跑，文件都在同一仓库。
_MODEL_FILES = {
    "fl2va_int8": "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "fl2va_fp8": "diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
    "fl2va_bf16": "diffusion_models/minimax_h3_fl2va_pruned_bf16.safetensors",
    "ref2va_int8": "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "ref2va_bf16": "diffusion_models/minimax_h3_ref2va_pruned_bf16.safetensors",
    "text_nvfp4": "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "text_bf16": "text_encoders/qwen3vl_32b_minimax_h3_bf16.safetensors",
    "vae_video_int8": "vae/minimax_h3_video_vae_int8_convrot.safetensors",
    "vae_video_fp16": "vae/minimax_h3_video_vae_fp16.safetensors",
    "vae_audio": "vae/minimax_h3_audio_vae_fp32.safetensors",
    "lora_4step": "loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
    "lora_ref2v": "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
}

# 每个文件的真实字节数（取自仓库文件清单，2026-09 核对）。
# 写在这里而不是「估一个 GB 数」：体积会直接显示给用户当时间预期，
# 而且断点续传要靠它判断下载完没完，估错了用户就会白等。
_FILE_BYTES: dict[str, int] = {
    _MODEL_FILES["fl2va_int8"]: 20970379616,
    _MODEL_FILES["fl2va_fp8"]: 20958205608,
    _MODEL_FILES["fl2va_bf16"]: 40225724176,
    _MODEL_FILES["ref2va_int8"]: 20970379616,
    _MODEL_FILES["ref2va_bf16"]: 40225724176,
    _MODEL_FILES["text_nvfp4"]: 15687142551,
    _MODEL_FILES["text_bf16"]: 51506295256,
    _MODEL_FILES["vae_video_int8"]: 2811065184,
    _MODEL_FILES["vae_video_fp16"]: 5207808496,
    _MODEL_FILES["vae_audio"]: 605254808,
    _MODEL_FILES["lora_4step"]: 1956192992,
    _MODEL_FILES["lora_ref2v"]: 1956193000,
}


def _files_size_gb(files: list[str]) -> float:
    return round(sum(_FILE_BYTES.get(f, 0) for f in files) / 1024 ** 3, 1)


MODEL_REPOS: dict[str, dict[str, Any]] = {
    "h3-lite": {
        "name": "H3 精简版（文生 / 图生视频）",
        "repo_hf": "Comfy-Org/MiniMax-H3",
        "repo_modelscope": "Comfy-Org/MiniMax-H3",
        "min_vram": 8,
        "desc": "FL2VA 主模型 + Qwen3-VL 文本编码器 + 视频/音频 VAE + 4 步 Turbo LoRA。"
                "覆盖文生视频、图生视频，原生带音频。8G 显存能跑（慢），12G 舒适。",
        "files": [
            _MODEL_FILES["fl2va_fp8"], _MODEL_FILES["text_nvfp4"],
            _MODEL_FILES["vae_video_int8"], _MODEL_FILES["vae_audio"],
            _MODEL_FILES["lora_4step"],
        ],
    },
    "h3-full": {
        "name": "H3 全能版（再加参考生视频）",
        "repo_hf": "Comfy-Org/MiniMax-H3",
        "repo_modelscope": "Comfy-Org/MiniMax-H3",
        "min_vram": 12,
        "desc": "在精简版基础上多一套 Ref2VA 主模型，可用最多 9 张图 / 3 段视频 / 3 段音频"
                "做参考，角色一致性和世界观最稳。",
        "files": [
            _MODEL_FILES["fl2va_fp8"], _MODEL_FILES["ref2va_int8"],
            _MODEL_FILES["text_nvfp4"], _MODEL_FILES["vae_video_int8"],
            _MODEL_FILES["vae_audio"], _MODEL_FILES["lora_4step"],
            _MODEL_FILES["lora_ref2v"],
        ],
    },
    "h3-bf16": {
        "name": "H3 全精度版（BF16，画质最好）",
        "repo_hf": "Comfy-Org/MiniMax-H3",
        "repo_modelscope": "Comfy-Org/MiniMax-H3",
        "min_vram": 24,
        "desc": "主模型与文本编码器都是 BF16 原精度，画质上限最高，但下载近百 GB、"
                "显存要求高，只建议 24G 显存以上、且硬盘宽裕时选。",
        "files": [
            _MODEL_FILES["fl2va_bf16"], _MODEL_FILES["text_bf16"],
            _MODEL_FILES["vae_video_fp16"], _MODEL_FILES["vae_audio"],
            _MODEL_FILES["lora_4step"],
        ],
    },
}
for _k, _v in MODEL_REPOS.items():
    _v["size_gb"] = _files_size_gb(_v["files"])

# ---------------------------------------------------------------- 运行时依赖
RUNTIME_DEPS = {
    "uv": {
        "name": "uv 运行时管理器",
        "size_gb": 0.04,
        "desc": "单文件 Python 包管理器，用于自动准备 Python 与依赖",
    },
    "python": {
        "name": "Python 3.12（隔离环境）",
        "size_gb": 0.03,
        "desc": "独立的 Python 运行时，不污染系统环境，可整体删除",
    },
    "torch": {
        "name": "PyTorch + CUDA 运行时",
        "size_gb": 2.5,
        "desc": "GPU 推理基础库（cu124）。无独显时自动改装 CPU 版（体积更小但极慢）",
    },
    "comfyui": {
        "name": "ComfyUI 执行引擎",
        "size_gb": 0.04,
        "desc": "底层执行引擎（源码包）。用户界面上完全看不到节点，仅作为 H3 的推理后端",
    },
    "comfyui-deps": {
        "name": "ComfyUI 运行依赖",
        "size_gb": 1.2,
        "desc": "前端包 / aiohttp / transformers 等；含官方 H3 工作流模板",
    },
    "comfy-nodes": {
        "name": "H3 加速节点（KJNodes）",
        "size_gb": 0.02,
        "desc": "可选。提供 H3 专用的采样加速与显存优化节点（SageAttention 需按你的 "
                "torch/CUDA 版本另装 wheel，见部署日志里的说明）",
    },
    "ffmpeg": {
        "name": "FFmpeg 7.1",
        "size_gb": 0.09,
        "desc": "视频合成 / 转码 / 字幕烧录，导出 MP4 必需",
    },
}

# ---------------------------------------------------------------- 显存 → 部署策略
# 依据 H3 官方与社区实测：8G 能跑（会显存/内存交换，慢但不崩），12G 舒适，24G 随便跑。
VRAM_TIERS = [
    (24, {"tier": "旗舰", "model": "h3-bf16", "nodes": True, "ffmpeg": True,
          "note": "可以上 BF16 全精度，画质上限最高（下载近百 GB）"}),
    (16, {"tier": "高", "model": "h3-full", "nodes": True, "ffmpeg": True,
          "note": "全能版：文生 / 图生 / 参考生视频全开，体验流畅"}),
    (12, {"tier": "中", "model": "h3-full", "nodes": True, "ffmpeg": True,
          "note": "全能版，开启 CPU Offload，768p 级稳定出片"}),
    (8, {"tier": "入门", "model": "h3-lite", "nodes": False, "ffmpeg": True,
         "note": "精简版 + CPU Offload。8G 能跑但慢，建议把虚拟内存加到 32G 以上"}),
    (0, {"tier": "无独显", "model": None, "nodes": False, "ffmpeg": True,
         "note": "未检测到可用的 NVIDIA 显卡，无法本地推理。可仅部署 FFmpeg 导出，生成走云端 Provider"}),
]


def tier_for(vram_gb: float) -> dict:
    for threshold, cfg in VRAM_TIERS:
        if vram_gb >= threshold:
            return dict(cfg)
    return dict(VRAM_TIERS[-1][1])


def component(key: str) -> dict:
    if key in RUNTIME_DEPS:
        return dict(RUNTIME_DEPS[key], key=key)
    if key in MODEL_REPOS:
        return dict(MODEL_REPOS[key], key=key)
    return {"key": key, "name": key, "size_gb": 0.0, "desc": ""}
