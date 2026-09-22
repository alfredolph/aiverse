"""SQLite 索引层。

对应文档：§32 项目数据库 —— SQLite + 文件系统，大文件不直接存 SQLite。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DATA_DIR, DB_PATH

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, name TEXT, style TEXT, aspect TEXT, resolution TEXT,
  mode TEXT, logline TEXT, created_at REAL, updated_at REAL, meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS stages(
  project_id TEXT, key TEXT, name TEXT, idx INTEGER, status TEXT,
  payload TEXT DEFAULT '{}', updated_at REAL, PRIMARY KEY(project_id, key)
);
CREATE TABLE IF NOT EXISTS candidates(
  id TEXT PRIMARY KEY, project_id TEXT, stage_key TEXT, group_key TEXT,
  label TEXT, payload TEXT, chosen INTEGER DEFAULT 0, created_at REAL
);
CREATE TABLE IF NOT EXISTS entities(
  id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, name TEXT, status TEXT,
  version INTEGER DEFAULT 1, payload TEXT DEFAULT '{}', updated_at REAL
);
CREATE TABLE IF NOT EXISTS shots(
  id TEXT PRIMARY KEY, project_id TEXT, no INTEGER, status TEXT,
  version INTEGER DEFAULT 1, payload TEXT DEFAULT '{}', updated_at REAL
);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, project_id TEXT, title TEXT, stage_key TEXT, status TEXT,
  priority INTEGER DEFAULT 5, progress REAL DEFAULT 0, error TEXT,
  created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS providers(
  id TEXT PRIMARY KEY, name TEXT, type TEXT, base_url TEXT, api_key TEXT,
  models TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1, meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS costs(
  id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, seconds REAL DEFAULT 0,
  tokens INTEGER DEFAULT 0, amount REAL DEFAULT 0, note TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_entities ON entities(project_id, kind);
CREATE INDEX IF NOT EXISTS idx_candidates ON candidates(project_id, stage_key, group_key);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now() -> float:
    return time.time()


def rows(sql: str, args: Iterable = ()) -> list[dict[str, Any]]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, tuple(args)).fetchall()]


def one(sql: str, args: Iterable = ()) -> dict[str, Any] | None:
    r = rows(sql, args)
    return r[0] if r else None


def run(sql: str, args: Iterable = ()) -> int:
    with tx() as c:
        return c.execute(sql, tuple(args)).lastrowid


def loads(v, default=None):
    if v in (None, ""):
        return default if default is not None else {}
    try:
        return json.loads(v)
    except Exception:
        return default if default is not None else {}


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False)
