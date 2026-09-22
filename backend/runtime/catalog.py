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
# uv / ffmpeg 的官方发布页在 GitHub，而某些网络会单独屏蔽 github.com:443
# （实测：api / codeload / uploads 都通，只有 github.com 被丢包）。
# 所以每个组件都准备多个候选，下载器会依次尝试，前一个挂了自动换下一个。
#
# 顺序原则：选中的镜像源排第一，其余按「不依赖 github.com」优先。
_UV_GH = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
_FF_GH = ("https://github.com/GyanD/codexffmpeg/releases/download/7.1/"
          "ffmpeg-7.1-essentials_build.zip")

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
# H3 开放权重。仓库 ID 会随官方更新变化，用户可在设置里覆盖。
MODEL_REPOS: dict[str, dict[str, Any]] = {
    "h3-base-quant": {
        "name": "MiniMax H3 量化版（推荐）",
        "repo_modelscope": "MiniMax/MiniMax-H3",
        "repo_hf": "MiniMaxAI/MiniMax-H3",
        "subdir": "quantized",
        "size_gb": 26.4,
        "min_vram": 8,
        "desc": "33B 参数视频生成模型，8G 显存即可运行（慢），12G+ 更舒服。原生 768p。",
    },
    "h3-base-bf16": {
        "name": "MiniMax H3 BF16 完整版",
        "repo_modelscope": "MiniMax/MiniMax-H3",
        "repo_hf": "MiniMaxAI/MiniMax-H3",
        "subdir": "",
        "size_gb": 52.0,
        "min_vram": 24,
        "desc": "未量化完整权重，画质最好，仅建议 24G 显存以上使用。",
    },
}

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
        "size_gb": 1.2,
        "desc": "底层执行引擎。用户界面上完全看不到节点，仅作为 H3 的推理后端",
    },
    "comfy-nodes": {
        "name": "H3 加速节点（SageAttention / EasyCache）",
        "size_gb": 0.35,
        "desc": "可选。官方实测可把 15 秒视频从 8 分钟压到约 4 分钟，画质轻微下降",
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
    (24, {"tier": "旗舰", "model": "h3-base-bf16", "nodes": True, "ffmpeg": True,
          "note": "可跑 BF16 完整版 + 全加速节点，1080p 级输出"}),
    (16, {"tier": "高", "model": "h3-base-quant", "nodes": True, "ffmpeg": True,
          "note": "量化版 + 加速节点，体验流畅"}),
    (12, {"tier": "中", "model": "h3-base-quant", "nodes": True, "ffmpeg": True,
          "note": "量化版，开启 CPU Offload，720p 级稳定出片"}),
    (8, {"tier": "入门", "model": "h3-base-quant", "nodes": False, "ffmpeg": True,
         "note": "量化版 + CPU Offload。8G 能跑但慢，建议加大虚拟内存到 32G 以上"}),
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
