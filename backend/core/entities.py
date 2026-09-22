"""资产实体（Character / Scene / Prop Bible）—— 文档 §11 / §12 / §13 / §47。

角色、场景、道具必须资产化，跨镜头/跨集复用，并保留版本。
"""
from __future__ import annotations

from typing import Any

from . import db

KIND_CHARACTER = "character"
KIND_SCENE = "scene"
KIND_PROP = "prop"


def get_by_name(project_id: str, kind: str, name: str) -> dict | None:
    """按「项目 + 类型 + 名字」取实体。

    资产是按名字幂等的（同一角色重复生成只升版本号），所以判断「这个资产建过没有」
    要按名字查，不能按 id。
    """
    r = db.one("SELECT * FROM entities WHERE project_id=? AND kind=? AND name=?",
               (project_id, kind, name))
    if not r:
        return None
    d = dict(r)
    d["payload"] = db.loads(r["payload"], {})
    return d


def upsert(project_id: str, kind: str, name: str, payload: dict[str, Any],
           status: str = "DRAFT") -> dict:
    exist = get_by_name(project_id, kind, name)
    if exist:
        version = int(exist["version"] or 1) + 1
        db.run("UPDATE entities SET payload=?, status=?, version=?, updated_at=? WHERE id=?",
               (db.dumps(payload), status, version, db.now(), exist["id"]))
        eid = exist["id"]
    else:
        eid = db.new_id("e_")
        db.run(
            "INSERT INTO entities(id,project_id,kind,name,status,version,payload,updated_at) "
            "VALUES(?,?,?,?,?,1,?,?)",
            (eid, project_id, kind, name, status, db.dumps(payload), db.now()),
        )
    return {"id": eid, "kind": kind, "name": name, "payload": payload, "status": status}


def list_by_kind(project_id: str, kind: str) -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM entities WHERE project_id=? AND kind=? ORDER BY rowid",
                     (project_id, kind)):
        d = dict(r)
        d["payload"] = db.loads(r["payload"], {})
        out.append(d)
    return out


def get(project_id: str, entity_id: str) -> dict | None:
    r = db.one("SELECT * FROM entities WHERE project_id=? AND id=?", (project_id, entity_id))
    if not r:
        return None
    d = dict(r)
    d["payload"] = db.loads(r["payload"], {})
    return d


def update_payload(project_id: str, entity_id: str, patch: dict, status: str | None = None) -> dict | None:
    r = db.one("SELECT * FROM entities WHERE project_id=? AND id=?", (project_id, entity_id))
    if not r:
        return None
    payload = db.loads(r["payload"], {})
    payload.update(patch)
    version = int(r["version"] or 1) + 1
    db.run("UPDATE entities SET payload=?, status=COALESCE(?,status), version=?, updated_at=? WHERE id=?",
           (db.dumps(payload), status, version, db.now(), entity_id))
    return {"id": entity_id, "payload": payload, "version": version}


def set_status(project_id: str, entity_id: str, status: str) -> None:
    db.run("UPDATE entities SET status=?, updated_at=? WHERE project_id=? AND id=?",
           (status, db.now(), project_id, entity_id))


def snapshot(project_id: str, entity_id: str, note: str = "") -> dict | None:
    """保存版本快照（文档 §47 版本控制）。

    注意存进去的必须是「当前这一版长什么样」，所以要把 `_versions` 摘掉再存。
    早先是直接 `{"payload": payload}` 又把同一个 dict 挂回 `payload["_versions"]`，
    于是 payload 里嵌 _versions、_versions 里又指回 payload ——
    `json.dumps` 抛 `Circular reference detected`，这个接口直接 500。
    （一直没被发现，是因为它只在「实体真的存在」时才会走到：
     测试里那个工作项目当时没有实体，接口提前 return None 就过了。）
    """
    r = db.one("SELECT * FROM entities WHERE project_id=? AND id=?", (project_id, entity_id))
    if not r:
        return None
    payload = db.loads(r["payload"], {})
    versions = list(payload.get("_versions") or [])
    snapshot_body = {k: v for k, v in payload.items() if k != "_versions"}
    versions.append({"version": int(r["version"] or 1), "note": note,
                     "payload": snapshot_body})
    payload["_versions"] = versions[-10:]
    db.run("UPDATE entities SET payload=?, updated_at=? WHERE id=?",
           (db.dumps(payload), db.now(), entity_id))
    return {"versions": len(payload["_versions"])}


def counts(project_id: str) -> dict[str, int]:
    out = {}
    for r in db.rows("SELECT kind, COUNT(*) AS n FROM entities WHERE project_id=? GROUP BY kind", (project_id,)):
        out[r["kind"]] = r["n"]
    return out
