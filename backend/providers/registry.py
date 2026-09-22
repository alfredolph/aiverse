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


KINDS = ("llm", "image", "video", "tts")


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
    # 类型写错要当场拒绝。早先是照单收下：一条 type=bogus 的记录进了库，
    # 但 list_providers 只遍历已知类型、_user_providers 里 KeyError 又被
    # try/except 吞掉 —— 于是这个 Provider 在界面上**根本不存在**，
    # 用户却收到「添加成功」。
    if kind not in KINDS:
        raise ValueError(f"未知的 Provider 类型：{kind}。可选：{'、'.join(KINDS)}")
    pid = db.new_id("pv_")
    db.run(
        "INSERT INTO providers(id,name,type,base_url,api_key,models,enabled,meta) VALUES(?,?,?,?,?,?,1,?)",
        (pid, name, kind, base_url, api_key, db.dumps(models or []), db.dumps(meta or {})),
    )
    return {"id": pid}


def update(pid: str, **fields) -> None:
    allowed = {"name", "type", "base_url", "api_key", "models", "enabled", "meta"}
    if "type" in fields and fields["type"] not in KINDS:
        raise ValueError(f"未知的 Provider 类型：{fields['type']}。可选：{'、'.join(KINDS)}")
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


def upsert_builtin(pid: str, fields: dict) -> dict:
    """按固定 ID 写入/更新一个「系统托管」Provider（如部署完成后自动注册的 H3）。

    与用户手动新增的 Provider 不同，它带 meta.managed=True，
    界面会标注为「本地部署」，用户仍可改地址或停用。
    """
    name = fields.get("name") or pid
    kind = fields.get("type") or "video"
    base_url = fields.get("base_url") or ""
    api_key = fields.get("api_key") or ""
    models = fields.get("models") or []
    meta = dict(fields.get("meta") or {})
    meta["managed"] = True
    enabled = 1 if fields.get("enabled", True) else 0

    exist = db.one("SELECT id FROM providers WHERE id=?", (pid,))
    if exist:
        db.run(
            "UPDATE providers SET name=?,type=?,base_url=?,api_key=?,models=?,enabled=?,meta=? WHERE id=?",
            (name, kind, base_url, api_key, db.dumps(models), enabled, db.dumps(meta), pid),
        )
    else:
        db.run(
            "INSERT INTO providers(id,name,type,base_url,api_key,models,enabled,meta) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (pid, name, kind, base_url, api_key, db.dumps(models), enabled, db.dumps(meta)),
        )
    return {"id": pid, "ok": True}


def set_enabled(pid: str, enabled: bool) -> dict:
    db.run("UPDATE providers SET enabled=? WHERE id=?", (1 if enabled else 0, pid))
    return {"ok": True}
