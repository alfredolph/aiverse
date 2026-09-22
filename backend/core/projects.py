"""项目 CRUD（文档 §31 / §32 / §33 / §43）。"""
from __future__ import annotations

import time
from typing import Any

from . import costs, db, entities, shots, store
from .config import ASPECTS, RESOLUTIONS, STATUS, STYLES
from ..workflow import engine


def create(name: str, script: str = "", style: str = "guoman", aspect: str = "9:16",
           resolution: str = "1080p", mode: str = "novice", source: str = "input",
           logline: str = "") -> dict:
    pid = db.new_id("p_")
    db.run(
        "INSERT INTO projects(id,name,style,aspect,resolution,mode,logline,created_at,updated_at,meta) "
        "VALUES(?,?,?,?,?,?,?,?,?,'{}')",
        (pid, name or "未命名项目", style, aspect, resolution, mode, logline, db.now(), db.now()),
    )
    store.ensure_dirs(pid, name)
    engine.init_stages(pid)
    if script:
        store.write_text(pid, "script/script.md", script)
    store.write_json(pid, "project.json", {
        "id": pid, "name": name, "style": style, "aspect": aspect,
        "resolution": resolution, "mode": mode, "source": source,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return get(pid)


def get(project_id: str) -> dict | None:
    r = db.one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not r:
        return None
    d = dict(r)
    d["meta"] = db.loads(r.get("meta"), {})
    d["style_name"] = next((s["name"] for s in STYLES if s["key"] == d.get("style")), d.get("style"))
    return d


def list_projects() -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM projects ORDER BY updated_at DESC"):
        d = dict(r)
        d["meta"] = db.loads(r.get("meta"), {})
        d["progress"] = engine.progress(d["id"])
        d["counts"] = {
            **entities.counts(d["id"]),
            "shots": len(shots.list_shots(d["id"])),
        }
        d["style_name"] = next((s["name"] for s in STYLES if s["key"] == d.get("style")), d.get("style"))
        out.append(d)
    return out


def update(project_id: str, **fields) -> dict | None:
    allowed = {"name", "style", "aspect", "resolution", "mode", "logline"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            args.append(v)
    if "meta" in fields:
        sets.append("meta=?")
        args.append(db.dumps(fields["meta"]))
    if not sets:
        return get(project_id)
    sets.append("updated_at=?")
    args.append(db.now())
    args.append(project_id)
    db.run(f"UPDATE projects SET {','.join(sets)} WHERE id=?", args)
    return get(project_id)


def set_meta(project_id: str, patch: dict) -> dict:
    p = get(project_id)
    meta = dict(p.get("meta") or {})
    meta.update(patch)
    update(project_id, meta=meta)
    return meta


def delete(project_id: str) -> dict:
    db.run("DELETE FROM projects WHERE id=?", (project_id,))
    for t in ("stages", "candidates", "entities", "shots", "tasks", "costs"):
        db.run(f"DELETE FROM {t} WHERE project_id=?", (project_id,))
    store.remove_project(project_id)
    return {"ok": True}


def detail(project_id: str) -> dict[str, Any]:
    p = get(project_id)
    if not p:
        return {}
    return {
        "project": p,
        "stages": engine.stages_of(project_id),
        "progress": engine.progress(project_id),
        "counts": {**entities.counts(project_id), "shots": len(shots.list_shots(project_id))},
        "costs": costs.summary(project_id),
        "files": store.dir_tree(project_id),
    }
