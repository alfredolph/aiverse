"""渲染辅助：把 Provider 产物落盘到项目目录。

统一处理「真实 Provider 失败 → 回退内置占位 Provider」，保证任何环境下都有可查看产物。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..core import store
from ..providers.media import (PlaceholderImageProvider, PlaceholderVideoProvider,
                               OfflineTTSProvider, save_wav)


def _fallback_image():
    return PlaceholderImageProvider()


def _fallback_video():
    return PlaceholderVideoProvider()


def render_image(ctx, rel_path: str, prompt: str, size: str = "768x1024",
                 negative: str = "", reference: str | None = None,
                 seed: int | None = None) -> dict[str, Any]:
    prov = ctx.image()
    fallback_used = False
    note = ""
    try:
        res = prov.generate(prompt, negative=negative, size=size, reference=reference, seed=seed)
    except Exception as e:
        fallback_used = True
        note = str(e)
        prov = _fallback_image()
        res = prov.generate(prompt, negative=negative, size=size, reference=reference, seed=seed)

    if res.get("svg"):
        store.write_text(ctx.pid, rel_path, res["svg"])
        path = rel_path
    else:
        path = res.get("path") or rel_path

    return {"path": path, "seed": res.get("seed"), "provider": prov.name,
            "fallback": fallback_used, "note": note, "prompt": prompt}


def render_video(ctx, rel_dir: str, shot_no: int, prompt: str, reference: str | None = None,
                 seconds: float = 4.0, resolution: str = "720p", aspect: str = "16:9",
                 lock: list[str] | None = None, seed: int | None = None) -> dict[str, Any]:
    prov = ctx.video()
    fallback_used = False
    note = ""
    try:
        res = prov.generate(prompt, reference=reference, seconds=seconds, resolution=resolution,
                            aspect=aspect, lock=lock, seed=seed)
    except Exception as e:
        fallback_used = True
        note = str(e)
        prov = _fallback_video()
        res = prov.generate(prompt, reference=reference, seconds=seconds, resolution=resolution,
                            aspect=aspect, lock=lock, seed=seed)

    poster_rel = f"{rel_dir}/S{shot_no:03d}_poster.svg"
    manifest_rel = f"{rel_dir}/S{shot_no:03d}.json"
    manifest = dict(res.get("manifest") or {"prompt": prompt, "provider": prov.name})

    # 真实 Provider 产出的视频：拷进项目目录
    video_rel = None
    src = res.get("video_path") or (res.get("path") if not res.get("svg") else None)
    if src and not fallback_used:
        ext = os.path.splitext(str(src))[1] or ".mp4"
        video_rel = f"{rel_dir}/S{shot_no:03d}{ext}"
        try:
            dst = store.resolve(ctx.pid) / video_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            manifest["video"] = video_rel
            manifest["status"] = "rendered"
            # 用 ffmpeg 抽一帧做封面，失败就退回占位海报
            if not extract_poster(dst, store.resolve(ctx.pid) / poster_rel):
                _placeholder_poster(ctx, poster_rel, prompt, resolution, aspect, seconds,
                                    res.get("seed") or 0, tag="已渲染 · 封面提取失败")
        except Exception as e:
            note = (note + f" / 拷贝视频失败：{e}").strip(" /")
            video_rel = None

    if not video_rel and res.get("svg"):
        store.write_text(ctx.pid, poster_rel, res["svg"])

    manifest.setdefault("poster", poster_rel)
    manifest["fallback"] = fallback_used
    if note:
        manifest["note"] = note
    store.write_json(ctx.pid, manifest_rel, manifest)

    return {"poster": poster_rel, "manifest": manifest_rel, "video": video_rel,
            "seed": res.get("seed"), "provider": prov.name, "fallback": fallback_used,
            "note": note, "status": manifest.get("status", "placeholder")}


def extract_poster(video: Path, dest: Path) -> bool:
    """用 ffmpeg 从视频抽第 1 帧做封面。没有 ffmpeg 就返回 False。"""
    from ..media import ffmpeg as ff
    exe = ff.ffmpeg_path()
    if not exe or not video.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [str(exe), "-y", "-ss", "0.5", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=1024:-2", str(dest.with_suffix(".png"))],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode == 0 and dest.with_suffix(".png").exists():
            dest.with_suffix(".png").replace(dest)
            return True
    except Exception:
        pass
    return False


def _placeholder_poster(ctx, rel: str, prompt: str, resolution: str, aspect: str,
                        seconds: float, seed: int, tag: str) -> None:
    from ..providers.media import PlaceholderVideoProvider
    res = PlaceholderVideoProvider().generate(prompt, seconds=seconds,
                                              resolution=resolution, aspect=aspect, seed=seed)
    svg = (res.get("svg") or "").replace("分镜海报（待渲染）", tag)
    if svg:
        store.write_text(ctx.pid, rel, svg)


def render_voice(ctx, rel_path: str, text: str, voice: str = "default") -> dict[str, Any]:
    prov = ctx.tts()
    fallback_used = False
    note = ""
    try:
        res = prov.speak(text, voice=voice)
    except Exception as e:
        fallback_used = True
        note = str(e)
        prov = OfflineTTSProvider()
        res = prov.speak(text, voice=voice)

    if res.get("wav_bytes"):
        from ..core import store as _s
        p = _s.resolve(ctx.pid) / rel_path
        save_wav(p, res["wav_bytes"], res["sample_rate"])
    return {"path": rel_path, "duration": res.get("duration", 0), "provider": prov.name,
            "fallback": fallback_used, "note": note, "text": text, "voice": voice}
