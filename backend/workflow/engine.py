"""Workflow Engine（文档 §5.1 / §37 / §48）。

职责：
  - 维护 8 阶段管线的状态机
  - 强制「审核门」：上一阶段未 APPROVED，下一阶段不可进入（§48）
  - 提供 WorkflowAdapter 统一接口（§37）
"""
from __future__ import annotations

import abc
from typing import Any

from ..core import db
from ..core.config import STAGES, STATUS


# ---------------------------------------------------------------- Adapter（文档 §37）
class WorkflowAdapter(abc.ABC):
    """任何模型/工作流都通过 Adapter 接入统一接口。"""

    name: str = "adapter"

    @abc.abstractmethod
    def validate(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def prepare(self, ctx: dict) -> dict[str, Any]: ...

    @abc.abstractmethod
    def execute(self, ctx: dict) -> dict[str, Any]: ...

    def monitor(self, task_id: str) -> dict[str, Any]:
        return {"task_id": task_id, "progress": 0}

    def cancel(self, task_id: str) -> bool:
        return False

    def retry(self, ctx: dict) -> dict[str, Any]:
        return self.execute(ctx)

    def export(self, ctx: dict) -> dict[str, Any]:
        return {"ok": True}


# ---------------------------------------------------------------- 阶段定义
def stage_defs() -> list[dict]:
    return [{"key": k, "name": n, "desc": d, "idx": i} for i, (k, n, d) in enumerate(STAGES)]


def stage_index(key: str) -> int:
    for i, (k, _, _) in enumerate(STAGES):
        if k == key:
            return i
    return -1


def stage_name(key: str) -> str:
    for k, n, _ in STAGES:
        if k == key:
            return n
    return key


def init_stages(project_id: str) -> None:
    for i, (k, n, _) in enumerate(STAGES):
        db.run(
            "INSERT OR IGNORE INTO stages(project_id,key,name,idx,status,payload,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (project_id, k, n, i, STATUS["DRAFT"], "{}", db.now()),
        )


def stages_of(project_id: str) -> list[dict]:
    init_stages(project_id)
    out = []
    for r in db.rows("SELECT * FROM stages WHERE project_id=? ORDER BY idx", (project_id,)):
        d = dict(r)
        d["payload"] = db.loads(r["payload"], {})
        d["status_label"] = {
            "DRAFT": "草稿", "GENERATING": "生成中", "REVIEW": "待审核",
            "APPROVED": "已通过", "REJECTED": "已驳回",
            "REGENERATING": "重新生成", "FINAL": "已完成",
        }.get(r["status"], r["status"])
        out.append(d)
    return out


def get_stage(project_id: str, key: str) -> dict | None:
    r = db.one("SELECT * FROM stages WHERE project_id=? AND key=?", (project_id, key))
    if not r:
        return None
    r["payload"] = db.loads(r["payload"], {})
    return r


def set_status(project_id: str, key: str, status: str, payload: dict | None = None) -> None:
    if payload is None:
        db.run("UPDATE stages SET status=?, updated_at=? WHERE project_id=? AND key=?",
               (status, db.now(), project_id, key))
    else:
        db.run("UPDATE stages SET status=?, payload=?, updated_at=? WHERE project_id=? AND key=?",
               (status, db.dumps(payload), db.now(), project_id, key))


def merge_payload(project_id: str, key: str, patch: dict) -> dict:
    cur = get_stage(project_id, key)
    payload = dict(cur["payload"]) if cur else {}
    payload.update(patch)
    set_status(project_id, key, (cur or {}).get("status", STATUS["DRAFT"]), payload)
    return payload


# ---------------------------------------------------------------- 审核门（文档 §48）
def gate(project_id: str, key: str) -> dict[str, Any]:
    """判断某阶段是否允许进入。"""
    idx = stage_index(key)
    if idx <= 0:
        return {"ok": True, "blocked_by": None}
    prev_key = STAGES[idx - 1][0]
    prev = get_stage(project_id, prev_key)
    if prev and prev["status"] == STATUS["APPROVED"]:
        return {"ok": True, "blocked_by": None}
    return {"ok": False, "blocked_by": prev_key, "blocked_by_name": stage_name(prev_key)}


def approve(project_id: str, key: str) -> dict[str, Any]:
    """审核通过。必须满足审核门，防止错误污染后续资产。"""
    g = gate(project_id, key)
    if not g["ok"]:
        return {"ok": False, "error": f"请先通过上一阶段「{g['blocked_by_name']}」", **g}
    st = get_stage(project_id, key)
    if not st or st["status"] in (STATUS["DRAFT"],):
        return {"ok": False, "error": "该阶段尚未生成内容，无法通过"}
    set_status(project_id, key, STATUS["FINAL"] if key == STAGES[-1][0] else STATUS["APPROVED"])
    return {"ok": True}


def reject(project_id: str, key: str, reason: str = "") -> dict[str, Any]:
    set_status(project_id, key, STATUS["REJECTED"], {**((get_stage(project_id, key) or {}).get("payload") or {}), "_reject_reason": reason})
    return {"ok": True}


def reopen(project_id: str, key: str) -> dict[str, Any]:
    """返回上一阶段重新编辑（§3：任何阶段都可以返回）。"""
    set_status(project_id, key, STATUS["REVIEW"])
    return {"ok": True}


def progress(project_id: str) -> dict[str, Any]:
    st = stages_of(project_id)
    done = sum(1 for s in st if s["status"] in (STATUS["APPROVED"], STATUS["FINAL"]))
    cur = next((s["key"] for s in st if s["status"] not in (STATUS["APPROVED"], STATUS["FINAL"])), None)
    return {"total": len(st), "done": done, "current": cur,
            "percent": round(done / max(1, len(st)) * 100)}
