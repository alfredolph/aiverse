"""渲染辅助：把 Provider 产物落盘到项目目录。

统一处理「真实 Provider 失败 → 回退内置占位 Provider」，保证任何环境下都有可查看产物。
"""
from __future__ import annotations

import json
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
    if res.get("svg"):
        store.write_text(ctx.pid, poster_rel, res["svg"])
    manifest = res.get("manifest") or {"prompt": prompt, "provider": prov.name}
    manifest["poster"] = poster_rel
    manifest["fallback"] = fallback_used
    manifest["note"] = note
    store.write_json(ctx.pid, manifest_rel, manifest)

    return {"poster": poster_rel, "manifest": manifest_rel, "seed": res.get("seed"),
            "provider": prov.name, "fallback": fallback_used, "note": note,
            "status": manifest.get("status", "placeholder")}


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
