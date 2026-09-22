"""分镜（Shot）数据访问 —— 文档 §17。"""
from __future__ import annotations

from typing import Any

from . import db


def replace_all(project_id: str, shots: list[dict[str, Any]]) -> list[dict]:
    db.run("DELETE FROM shots WHERE project_id=?", (project_id,))
    out = []
    for s in shots:
        sid = db.new_id("s_")
        db.run(
            "INSERT INTO shots(id,project_id,no,status,version,payload,updated_at) VALUES(?,?,?,?,1,?,?)",
            (sid, project_id, int(s.get("no") or 0), s.get("status", "DRAFT"), db.dumps(s), db.now()),
        )
        out.append({"id": sid, **s})
    return out


def list_shots(project_id: str) -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM shots WHERE project_id=? ORDER BY no", (project_id,)):
        d = dict(r)
        d["payload"] = db.loads(r["payload"], {})
        out.append(d)
    return out


def get_shot(project_id: str, no: int) -> dict | None:
    r = db.one("SELECT * FROM shots WHERE project_id=? AND no=?", (project_id, no))
    if not r:
        return None
    d = dict(r)
    d["payload"] = db.loads(r["payload"], {})
    return d


def update_shot(project_id: str, no: int, patch: dict, status: str | None = None) -> dict | None:
    r = db.one("SELECT * FROM shots WHERE project_id=? AND no=?", (project_id, no))
    if not r:
        return None
    payload = db.loads(r["payload"], {})
    payload.update(patch)
    db.run("UPDATE shots SET payload=?, status=COALESCE(?,status), version=version+1, updated_at=? WHERE id=?",
           (db.dumps(payload), status, db.now(), r["id"]))
    return {"id": r["id"], "payload": payload}


def reorder(project_id: str, order: list[int]) -> list[dict]:
    """按给定镜头号顺序重排（文档 §17 拖拽调整顺序）。"""
    shots = {s["no"]: s for s in list_shots(project_id)}
    seq = [shots[n] for n in order if n in shots]
    seq += [s for s in list_shots(project_id) if s["no"] not in order]
    for i, s in enumerate(seq, start=1):
        payload = s["payload"]
        payload["no"] = i
        db.run("UPDATE shots SET no=?, payload=?, updated_at=? WHERE id=?",
               (i, db.dumps(payload), db.now(), s["id"]))
    return list_shots(project_id)


def counts(project_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.rows("SELECT status, COUNT(*) AS n FROM shots WHERE project_id=? GROUP BY status", (project_id,)):
        out[r["status"]] = r["n"]
    return out
