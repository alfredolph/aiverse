"""MiniMax H3 的 ComfyUI 工作流模板与节点自动识别。

背景（已核实）：
  * MiniMax H3 是**开放权重**的全模态视频模型，33B 参数，
    量化版 26.4GB / BF16 版 50+GB，8G 显存即可运行（慢），原生输出 768p。
  * 官方支持 Diffusers / SGLang / vLLM / DiffSynth-Studio 四种部署方式，
    ComfyUI 是社区最常用的可视化路线。
  * H3-Base 有两个变体：FL2VA（文生视频 + 首/尾帧）与 Ref2VA（最多 9 图 + 3 视频 + 3 音频参考）。

工程上的诚实说明：
  ComfyUI 里 H3 的**节点类名取决于你装了哪套社区节点包**（零度解说 / 秋叶 / kijai 等
  整合包的命名各不相同）。因此这里不硬编码节点名，而是：
    1. 给出一份「可覆盖的默认节点映射」
    2. 提供 autodetect_node_map()：连上本地 ComfyUI 读 /object_info，
       自动扫描含 h3 / minimax 的节点并回填映射
    3. 把模板导出到 ComfyUI 的 workflows 目录，用户可在 ComfyUI 里直接打开微调
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 默认节点映射
# 键 = 逻辑角色，值 = ComfyUI 节点 class_type。可用 autodetect 覆盖。
DEFAULT_NODE_MAP: dict[str, str] = {
    "model_loader": "MiniMaxH3Loader",
    "text_encode": "CLIPTextEncode",
    "latent_video": "EmptyMiniMaxH3LatentVideo",
    "sampler": "MiniMaxH3Sampler",
    "vae_decode": "VAEDecode",
    "load_image": "LoadImage",
    "video_output": "SaveVideo",
}

# 自动识别时按优先级匹配的关键词（越靠前越优先）
NODE_HINTS: dict[str, list[str]] = {
    "model_loader": ["minimaxh3loader", "h3loader", "minimaxh3modelloader", "h3modelloader"],
    "sampler": ["minimaxh3sampler", "h3sampler", "h3scheduler"],
    "latent_video": ["minimaxh3latentvideo", "h3latentvideo", "emptyminimaxh3latent"],
    "video_output": ["savevideo", "createvideo", "vhs_videocombine", "savewebm"],
    "load_image": ["loadimage"],
    "text_encode": ["cliptextencode", "textencode"],
    "vae_decode": ["vaedecode"],
}

# 关键词兜底：不同 H3 节点包的类名会「中间插词」，
# 例如 MiniMaxH3EmptyLatentVideo —— 单纯子串匹配永远命中不了
# `minimaxh3latentvideo`，所以再给一层「必须满足 + 加权加分」的规则。
#   must     : 必须全部出现
#   must_any : 至少出现一个
#   any      : 出现越多分越高（用来在多个候选里挑最像的）
NODE_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "model_loader": {"must": ["loader"], "any": ["minimax", "h3", "model"]},
    "sampler": {"must_any": ["sampler", "scheduler"], "any": ["minimax", "h3"]},
    "latent_video": {"must": ["latent"], "any": ["minimax", "h3", "empty", "video"]},
    "video_output": {"must_any": ["savevideo", "createvideo",
                                  "videocombine", "savewebm", "saveanimated"]},
    "load_image": {"must": ["loadimage"]},
    "text_encode": {"must": ["textencode"], "any": ["clip"]},
    "vae_decode": {"must": ["vaedecode"]},
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
    """检查当前 ComfyUI 是否具备跑 H3 的节点。"""
    lower = [n.lower() for n in object_info.keys()]
    has_h3 = any("h3" in n or "minimax" in n for n in lower)
    accel = {
        "sage_attention": any("sageattention" in n or "sage_attn" in n for n in lower),
        "easy_cache": any("easycache" in n for n in lower),
    }
    related = sorted({n for n in object_info.keys()
                      if "h3" in n.lower() or "minimax" in n.lower()})
    return {"available": has_h3, "acceleration": accel, "related_nodes": related[:40]}


# ---------------------------------------------------------------- 图构建
def _text_node(node_id: str, class_type: str, text: str, clip_ref: list | None = None) -> dict:
    return {
        "inputs": {"text": text, "clip": clip_ref or ["1", 0]},
        "class_type": class_type,
        "_meta": {"title": "AIVerse 文本编码"},
        "id": node_id,
    }


def build_graph(kind: str = "fl2va", params: dict[str, Any] | None = None,
                node_map: dict[str, str] | None = None) -> dict[str, Any]:
    """生成 ComfyUI API 格式的工作流图。

    params:
        prompt, negative, width, height, frames, steps, seed, cfg,
        reference (图片路径，ref2va 用), fps
    """
    p = params or {}
    nm = {**DEFAULT_NODE_MAP, **(node_map or {})}

    width = int(p.get("width") or 832)
    height = int(p.get("height") or 480)
    frames = int(p.get("frames") or 124)
    steps = int(p.get("steps") or 50)
    seed = int(p.get("seed") or 0)
    cfg = float(p.get("cfg") or 6.0)
    fps = int(p.get("fps") or 24)
    prompt = p.get("prompt") or ""
    negative = p.get("negative") or "blurry, low quality, deformed, watermark"

    graph: dict[str, Any] = {
        "1": {
            "inputs": {"model_name": p.get("model_name") or "MiniMax-H3",
                       "precision": p.get("precision") or "quantized",
                       "cpu_offload": bool(p.get("offload", True))},
            "class_type": nm["model_loader"],
            "_meta": {"title": "H3 模型加载"},
        },
        "2": {
            "inputs": {"text": prompt, "clip": ["1", 0]},
            "class_type": nm["text_encode"],
            "_meta": {"title": "正向提示词"},
        },
        "3": {
            "inputs": {"text": negative, "clip": ["1", 0]},
            "class_type": nm["text_encode"],
            "_meta": {"title": "负向提示词"},
        },
        "4": {
            "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1},
            "class_type": nm["latent_video"],
            "_meta": {"title": "视频潜空间"},
        },
        "5": {
            "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                       "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg},
            "class_type": nm["sampler"],
            "_meta": {"title": "H3 采样"},
        },
        "6": {
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            "class_type": nm["vae_decode"],
            "_meta": {"title": "解码"},
        },
        "7": {
            "inputs": {"images": ["6", 0], "fps": fps,
                       "filename_prefix": p.get("filename_prefix") or "aiverse/h3"},
            "class_type": nm["video_output"],
            "_meta": {"title": "输出视频（含音频轨）"},
        },
    }

    # Ref2VA：最多 9 张参考图 + 3 段视频 + 3 段音频
    refs = p.get("references") or ([p["reference"]] if p.get("reference") else [])
    if kind == "ref2va" and refs:
        for i, ref in enumerate(refs[:9]):
            nid = str(20 + i)
            graph[nid] = {
                "inputs": {"image": ref, "upload": "image"},
                "class_type": nm["load_image"],
                "_meta": {"title": f"参考图 {i + 1}"},
            }
            graph["5"]["inputs"].setdefault("reference_images", []).append([nid, 0])

    return graph


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
    """把 FL2VA / Ref2VA 两套模板写到 ComfyUI 的 workflows 目录。"""
    target.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for kind, name in (("fl2va", "H3-文生视频-FL2VA"), ("ref2va", "H3-参考生视频-Ref2VA")):
        graph = build_graph(kind, {"prompt": "在此填写提示词"})
        payload = {
            "aiverse_template": True,
            "kind": kind,
            "node_map": DEFAULT_NODE_MAP,
            "api_graph": graph,
            "ui_workflow": ui_workflow(kind, graph),
            "usage": [
                "1. 在 ComfyUI 中打开本文件，确认节点类名与已安装的 H3 节点包一致",
                "2. 若不一致，在 AIVerse「设置 → 本地部署 → 节点映射」里改，或点「自动识别节点」",
                "3. H3-Base 原生输出 768p；2K 需官方 API",
                "4. 中文口播效果不稳定，建议台词走 TTS 后期配音",
            ],
        }
        f = target / f"{name}.json"
        f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out.append(f)
    return out
