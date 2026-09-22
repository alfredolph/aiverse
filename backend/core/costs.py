"""成本记录（文档 §43 / §44）。"""
from __future__ import annotations

from . import db


def record(project_id: str, kind: str, seconds: float = 0.0, tokens: int = 0,
           amount: float = 0.0, note: str = "") -> None:
    db.run(
        "INSERT INTO costs(id,project_id,kind,seconds,tokens,amount,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (db.new_id("cost_"), project_id, kind, float(seconds), int(tokens), float(amount), note, db.now()),
    )


def summary(project_id: str) -> dict:
    r = db.one(
        "SELECT COALESCE(SUM(seconds),0) AS s, COALESCE(SUM(tokens),0) AS t, "
        "COALESCE(SUM(amount),0) AS a FROM costs WHERE project_id=?",
        (project_id,),
    ) or {"s": 0, "t": 0, "a": 0}
    secs = float(r["s"] or 0)
    return {
        "local_seconds": round(secs, 1),
        "local_human": f"{int(secs // 3600)}小时{int((secs % 3600) // 60)}分钟",
        "tokens": int(r["t"] or 0),
        "cloud_amount": round(float(r["a"] or 0), 2),
        "total_amount": round(float(r["a"] or 0), 2),
    }


def by_kind(project_id: str) -> list[dict]:
    return db.rows(
        "SELECT kind, COUNT(*) AS n, SUM(seconds) AS s, SUM(tokens) AS t, SUM(amount) AS a "
        "FROM costs WHERE project_id=? GROUP BY kind ORDER BY n DESC",
        (project_id,),
    )
