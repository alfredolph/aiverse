"""抽卡（Gacha）候选池 —— 文档 §15 / §49。

任何阶段的每次生成都产出多份候选（方案 A/B/C/D），用户「采用 / 继续抽卡 / 修改要求」。
"""
from __future__ import annotations

from typing import Any

from . import db


def add_candidates(project_id: str, stage_key: str, group_key: str,
                   items: list[dict[str, Any]], start_label: int = 0) -> list[dict]:
    out = []
    for i, it in enumerate(items):
        cid = db.new_id("c_")
        label = chr(ord("A") + (start_label + i) % 26)
        db.run(
            "INSERT INTO candidates(id,project_id,stage_key,group_key,label,payload,chosen,created_at) "
            "VALUES(?,?,?,?,?,?,0,?)",
            (cid, project_id, stage_key, group_key, label, db.dumps(it), db.now()),
        )
        out.append({"id": cid, "label": label, "payload": it})
    return out


def list_candidates(project_id: str, stage_key: str | None = None,
                    group_key: str | None = None) -> list[dict]:
    sql = "SELECT * FROM candidates WHERE project_id=?"
    args: list = [project_id]
    if stage_key:
        sql += " AND stage_key=?"
        args.append(stage_key)
    if group_key:
        sql += " AND group_key=?"
        args.append(group_key)
    sql += " ORDER BY created_at"
    out = []
    for r in db.rows(sql, args):
        d = dict(r)
        d["payload"] = db.loads(r["payload"], {})
        d["chosen"] = bool(r["chosen"])
        out.append(d)
    return out


def group_counts(project_id: str, stage_key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.rows(
        "SELECT group_key, COUNT(*) AS n FROM candidates WHERE project_id=? AND stage_key=? GROUP BY group_key",
        (project_id, stage_key),
    ):
        out[r["group_key"]] = r["n"]
    return out


def choose(project_id: str, candidate_id: str) -> dict | None:
    cand = db.one("SELECT * FROM candidates WHERE id=? AND project_id=?", (candidate_id, project_id))
    if not cand:
        return None
    db.run("UPDATE candidates SET chosen=0 WHERE project_id=? AND stage_key=? AND group_key=?",
           (project_id, cand["stage_key"], cand["group_key"]))
    db.run("UPDATE candidates SET chosen=1 WHERE id=?", (candidate_id,))
    d = dict(cand)
    d["payload"] = db.loads(cand["payload"], {})
    d["chosen"] = True
    return d


def chosen_for(project_id: str, stage_key: str, group_key: str) -> dict | None:
    r = db.one(
        "SELECT * FROM candidates WHERE project_id=? AND stage_key=? AND group_key=? AND chosen=1 LIMIT 1",
        (project_id, stage_key, group_key),
    )
    if not r:
        return None
    d = dict(r)
    d["payload"] = db.loads(r["payload"], {})
    d["chosen"] = True
    return d


def clear_group(project_id: str, stage_key: str, group_key: str) -> None:
    db.run("DELETE FROM candidates WHERE project_id=? AND stage_key=? AND group_key=?",
           (project_id, stage_key, group_key))


def next_label_index(project_id: str, stage_key: str, group_key: str) -> int:
    n = db.one("SELECT COUNT(*) AS n FROM candidates WHERE project_id=? AND stage_key=? AND group_key=?",
               (project_id, stage_key, group_key))
    return int((n or {}).get("n") or 0)
