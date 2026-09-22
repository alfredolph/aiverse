"""部署计划生成 —— 按硬件决定装什么。

核心逻辑：
  1. 读 GPU / 显存 / 内存 / 磁盘
  2. 按显存档位挑模型变体与加速节点（catalog.VRAM_TIERS）
  3. 生成一串可顺序执行的步骤，给出诚实的总体积与耗时预估
"""
from __future__ import annotations

from typing import Any

from ..core.config import RUNTIME_DIR
from ..gpu import detector as gpu
from . import catalog


def _size_human(gb: float) -> str:
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{gb * 1024:.0f} MB"


def build_plan(mirror: str = "cn", model_key: str | None = None,
               include_nodes: bool | None = None, include_ffmpeg: bool = True) -> dict[str, Any]:
    info = gpu.detect()
    top = info["gpus"][0]
    vram = float(top.get("vram_gb") or 0)
    tier = catalog.tier_for(vram)

    m = catalog.MIRRORS.get(mirror) or catalog.MIRRORS["cn"]
    model_key = model_key or tier["model"]
    # 未知的模型版本要在这里挡掉：往下走是 catalog.MODEL_REPOS[key]，
    # 直接 KeyError 的话用户看到的是 500 + 一坨 traceback，而不是「你写错了」。
    if model_key and model_key not in catalog.MODEL_REPOS:
        raise ValueError(
            f"没有这个模型版本：{model_key}。可选："
            + "、".join(f"{k}（{v['name']}）" for k, v in catalog.MODEL_REPOS.items())
        )
    if include_nodes is None:
        include_nodes = bool(tier["nodes"])

    rt = RUNTIME_DIR
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    def step(key: str, name: str, desc: str, kind: str, size_gb: float,
             cmd: list[str] | None = None, optional: bool = False,
             needs_gpu: bool = False, cwd: str | None = None,
             marker: str = "") -> None:
        steps.append({
            "key": key, "name": name, "desc": desc, "kind": kind,
            "size_gb": round(size_gb, 3), "size_human": _size_human(size_gb),
            "cmd": cmd or [], "optional": optional, "needs_gpu": needs_gpu,
            "cwd": cwd or str(rt), "done": False,
            # marker：这一步跑完后写下的「完工标记」文件（相对 RUNTIME_DIR）。
            # 幂等判断用它，而不是去猜某个包有没有装上 —— 猜错的代价是每次重跑都重装。
            "marker": marker,
        })

    # ---- 1. uv -----------------------------------------------------
    step("uv", "准备 uv 运行时管理器",
         "单文件 Python 包管理器，用来隔离安装，不污染系统 Python",
         "download_zip", 0.04,
         cmd=[str(rt / "uv" / "uv.exe"), "--version"])

    # ---- 2. Python -------------------------------------------------
    step("python", "安装 Python 3.12 隔离运行时",
         "独立运行时，卸载时整体删除即可，不影响系统环境",
         "exec", 0.03,
         cmd=[str(rt / "uv" / "uv.exe"), "python", "install", "3.12"])

    # ---- 3. 虚拟环境 -----------------------------------------------
    step("venv", "创建项目虚拟环境",
         "所有推理依赖装在这里，与系统完全隔离",
         "exec", 0.0,
         cmd=[str(rt / "uv" / "uv.exe"), "venv", str(rt / "venv"), "--python", "3.12"])

    # ---- 4. PyTorch ------------------------------------------------
    if vram >= 1:
        torch_cmd = [str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                     "torch", "torchvision", "torchaudio",
                     "--index-url", m["torch_index"]]
        torch_size = 2.5
    else:
        torch_cmd = [str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                     "torch", "torchvision", "torchaudio"]
        torch_size = 0.9
        warnings.append("未检测到 NVIDIA 显卡，将安装 CPU 版 PyTorch（可运行但极慢）")
    step("torch", "安装 PyTorch + CUDA 运行时",
         "GPU 推理基础库（cu124）。这是本地出片的算力底座",
         "exec", torch_size, cmd=torch_cmd, needs_gpu=True)

    # ---- 5. ComfyUI ------------------------------------------------
    # 直接装源码：comfy-cli 的 install 只认 --skip-manager，
    # --nvidia / --yes / install --workspace 这几个写法官方文档里没有，
    # 赌它不如自己下 zip + 装 requirements.txt，每一步都能核对。
    step("comfyui", "部署 ComfyUI 执行引擎",
         "底层推理后端（源码包）。界面上完全看不到节点，只作为 H3 的运行时",
         "download_zip", 0.04)
    step("comfyui-deps", "安装 ComfyUI 运行依赖",
         "前端包 / aiohttp / transformers 等，含官方 H3 工作流模板",
         "install_reqs", 1.2,
         cmd=[str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
              "-r", str(rt / "comfyui" / "requirements.txt")],
         marker="comfyui/.aiverse-deps-ok")

    # ---- 6. 加速节点（可选）----------------------------------------
    if include_nodes:
        step("comfy-nodes", "安装 H3 加速节点（KJNodes）",
             "提供 H3 专用采样加速与显存优化节点。装完在 ComfyUI 里可搜到 "
             "「MiniMax H3」加速节点；SageAttention 需按 torch/CUDA 版本另装 wheel",
             "download_zip", 0.02, optional=True, needs_gpu=True)
        steps[-1]["unzip_to"] = str(rt / "comfyui" / "custom_nodes" / "ComfyUI-KJNodes")
        step("comfy-nodes-deps", "安装加速节点依赖",
             "KJNodes 的 requirements（没有就跳过）",
             "install_reqs", 0.1,
             cmd=[str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                  "-r", str(rt / "comfyui" / "custom_nodes" / "ComfyUI-KJNodes"
                            / "requirements.txt")],
             optional=True, needs_gpu=True,
             marker="comfyui/custom_nodes/ComfyUI-KJNodes/.aiverse-deps-ok")

    # ---- 7. H3 权重 ------------------------------------------------
    # 落到 comfyui/models/：Comfy-Org 的仓库目录结构（diffusion_models /
    # text_encoders / vae / loras）跟 ComfyUI 的 models/ 一一对应，
    # 所以 local_dir 指到 comfyui/models，文件就会自动落到正确位置。
    models_dir = rt / "comfyui" / "models"
    if model_key:
        md = catalog.MODEL_REPOS[model_key]
        repo = md["repo_modelscope"] if m["models"] == "modelscope" else md["repo_hf"]
        tool = "modelscope" if m["models"] == "modelscope" else "huggingface_hub"
        step("model-tool", f"安装模型下载工具（{tool}）",
             "用于从国内/海外镜像拉取 H3 权重，支持断点续传",
             "exec", 0.02,
             cmd=[str(rt / "uv" / "uv.exe"), "pip", "install", "--python", str(rt / "venv"),
                  "modelscope", "huggingface_hub"])
        step("h3-weights", f"下载 {md['name']}",
             f"{md['desc']} 共 {len(md['files'])} 个文件，来自 {repo}",
             "model_download", md["size_gb"],
             needs_gpu=True)
        steps[-1]["repo"] = repo
        steps[-1]["files"] = list(md["files"])
        steps[-1]["backend"] = m["models"]
        steps[-1]["target"] = str(models_dir)
        if md["min_vram"] > vram > 0:
            warnings.append(
                f"当前显存 {vram:.0f}GB 低于该版本的推荐值 {md['min_vram']}GB，"
                f"会自动在显存/内存间交换，不会崩但速度慢"
            )
    else:
        warnings.append("跳过模型下载（无可用 GPU）。生成将走云端 Provider")

    # ---- 8. FFmpeg -------------------------------------------------
    # FFmpeg 是「导出成片」的**唯一**硬依赖，跟有没有显卡毫无关系。
    # 从 v1.0.6 起它随程序一起发（安装目录 / 绿色版 exe 内置），
    # 所以这里默认不再排这一步 —— 用户装完就能导出，不用等 43 GB 的部署。
    # 只有「找不到自带的那份」时才回退到下载，比如直接从源码跑、或用户手动删了。
    from ..media import ffmpeg as _ffmpeg
    ffmpeg_now = _ffmpeg.detect()
    if include_ffmpeg and not ffmpeg_now.get("available"):
        step("ffmpeg", "部署 FFmpeg 7.1",
             "视频合成 / 转码 / 字幕烧录，导出 MP4 必需",
             "download_zip", 0.09)

    # ---- 9. 写入 H3 工作流与 Provider 配置 --------------------------
    step("wire", "接入 H3 工作流并注册 Provider",
         "写入 FL2VA / Ref2VA 工作流模板，把 H3 注册为视频 Provider",
         "wire", 0.0)

    total = sum(s["size_gb"] for s in steps)
    disk_free = float(info["system"].get("disk_free_gb") or 0)
    if disk_free and disk_free < total + 10:
        warnings.append(
            f"磁盘可用 {disk_free:.0f}GB，部署需要约 {total:.1f}GB + 运行余量 10GB，建议清理空间"
        )
    if float(info["system"].get("ram_gb") or 0) < 32 and vram and vram < 16:
        warnings.append(
            f"内存 {info['system']['ram_gb']}GB。低显存跑 H3 会大量使用内存做交换，"
            f"建议 32GB+，或在系统里把虚拟内存设到 64GB"
        )

    # 粗略耗时：按 12 MB/s 估算下载时间
    dl_minutes = total * 1024 / 12 / 60

    return {
        "ok": True,
        "runtime_dir": str(rt),
        "mirror": mirror,
        "mirror_name": m["name"],
        "gpu": {"name": top["name"], "vram_gb": vram, "driver": top.get("driver", "")},
        "system": info["system"],
        "tier": tier,
        "model": model_key,
        "model_name": catalog.MODEL_REPOS[model_key]["name"] if model_key else "（不下载）",
        "steps": steps,
        "total_download_gb": round(total, 2),
        "total_download_human": _size_human(total),
        "estimated_minutes": round(dl_minutes, 1),
        "warnings": warnings,
        "can_local": vram >= 8,
    }
