"""Provider 注册中心（文档 §42）。

内置 Provider 始终可用；用户可在「设置」里增删 OpenAI 兼容 / ComfyUI / 云端 Provider。
"""
from __future__ import annotations

from ..core import db
from .base import ImageProvider, LLMProvider, TTSProvider, VideoProvider
from .llm import HeuristicLLM, OpenAICompatLLM
from .media import (CloudTTSProvider, ComfyUIImageProvider, H3ComfyUIProvider,
                    OfflineTTSProvider, PlaceholderImageProvider,
                    PlaceholderVideoProvider)

# 内置 Provider 实例（不落库，随进程存在）
_BUILTIN = {
    "llm": [HeuristicLLM()],
    "image": [PlaceholderImageProvider()],
    "video": [PlaceholderVideoProvider(), H3ComfyUIProvider()],
    "tts": [OfflineTTSProvider()],
}

_BUILDERS = {
    "llm": lambda r: OpenAICompatLLM(r["id"], r["name"], r["base_url"], r["api_key"],
                                     db.loads(r.get("models"), []), db.loads(r.get("meta"), {})),
    "image": lambda r: ComfyUIImageProvider(r["id"], r["name"], r["base_url"], r["api_key"],
                                            db.loads(r.get("models"), []), db.loads(r.get("meta"), {})),
    "video": lambda r: H3ComfyUIProvider(r["id"], r["name"], r["base_url"], r["api_key"],
                                         db.loads(r.get("models"), []), db.loads(r.get("meta"), {})),
    "tts": lambda r: CloudTTSProvider(r["id"], r["name"], r["base_url"], r["api_key"],
                                      db.loads(r.get("models"), []), db.loads(r.get("meta"), {})),
}


def _user_providers(kind: str) -> list:
    out = []
    for r in db.rows("SELECT * FROM providers WHERE type=? AND enabled=1 ORDER BY name", (kind,)):
        try:
            out.append(_BUILDERS[kind](r))
        except Exception:
            continue
    return out


def list_providers(kind: str | None = None) -> list[dict]:
    kinds = [kind] if kind else ["llm", "image", "video", "tts"]
    out = []
    for k in kinds:
        for p in _BUILTIN.get(k, []) + _user_providers(k):
            d = p.describe()
            d["builtin"] = p in _BUILTIN.get(k, [])
            out.append(d)
    return out


def get(kind: str, provider_id: str | None = None):
    """按 kind 取 Provider，未指定则取第一个可用的（用户配置优先）。"""
    candidates = _user_providers(kind) + _BUILTIN.get(kind, [])
    if provider_id:
        for p in candidates:
            if p.id == provider_id:
                return p
    for p in candidates:
        if p.enabled:
            return p
    return None


def get_llm(provider_id: str | None = None) -> LLMProvider:
    return get("llm", provider_id)


def get_image(provider_id: str | None = None) -> ImageProvider:
    return get("image", provider_id)


def get_video(provider_id: str | None = None) -> VideoProvider:
    return get("video", provider_id)


def get_tts(provider_id: str | None = None) -> TTSProvider:
    return get("tts", provider_id)


def add(name: str, kind: str, base_url: str = "", api_key: str = "",
        models: list[str] | None = None, meta: dict | None = None) -> dict:
    pid = db.new_id("pv_")
    db.run(
        "INSERT INTO providers(id,name,type,base_url,api_key,models,enabled,meta) VALUES(?,?,?,?,?,?,1,?)",
        (pid, name, kind, base_url, api_key, db.dumps(models or []), db.dumps(meta or {})),
    )
    return {"id": pid}


def update(pid: str, **fields) -> None:
    allowed = {"name", "type", "base_url", "api_key", "models", "enabled", "meta"}
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("models", "meta"):
            v = db.dumps(v)
        sets.append(f"{k}=?")
        args.append(v)
    if not sets:
        return
    args.append(pid)
    db.run(f"UPDATE providers SET {','.join(sets)} WHERE id=?", args)


def delete(pid: str) -> None:
    db.run("DELETE FROM providers WHERE id=?", (pid,))
