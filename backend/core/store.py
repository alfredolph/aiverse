"""项目文件系统读写。

对应文档：§33 文件结构 —— 每个项目一个独立目录，资产分门别类落盘。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .config import DATA_DIR, PROJECT_SUBDIRS


def safe_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", (name or "project").strip())
    return name[:48] or "project"


def project_dir(project_id: str, name: str | None = None) -> Path:
    d = DATA_DIR / f"{safe_name(name)}_{project_id}" if name else DATA_DIR / project_id
    return d


def resolve(project_id: str) -> Path:
    """通过 id 前缀匹配已存在的项目目录。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if (DATA_DIR / project_id).exists():
        return DATA_DIR / project_id
    for p in DATA_DIR.iterdir():
        if p.is_dir() and p.name.endswith(project_id):
            return p
    return DATA_DIR / project_id


def ensure_dirs(project_id: str, name: str | None = None) -> Path:
    base = project_dir(project_id, name)
    for sub in PROJECT_SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def write_json(project_id: str, rel: str, obj: Any) -> Path:
    base = resolve(project_id)
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read_json(project_id: str, rel: str, default=None):
    p = resolve(project_id) / rel
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_text(project_id: str, rel: str, text: str) -> Path:
    base = resolve(project_id)
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def read_text(project_id: str, rel: str, default: str = "") -> str:
    p = resolve(project_id) / rel
    if not p.exists():
        return default
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return default


def asset_dir(project_id: str, kind: str) -> Path:
    base = resolve(project_id)
    mapping = {
        "image": "images",
        "video": "videos",
        "audio": "audio",
        "subtitle": "subtitles",
        "timeline": "timeline",
        "export": "exports",
        "workflow": "workflows",
        "storyboard": "storyboards",
    }
    d = base / mapping.get(kind, "cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def remove_project(project_id: str) -> None:
    d = resolve(project_id)
    if d.exists() and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)


def dir_tree(project_id: str, limit: int = 200) -> list[str]:
    base = resolve(project_id)
    out: list[str] = []
    if not base.exists():
        return out
    for p in sorted(base.rglob("*")):
        if len(out) >= limit:
            break
        rel = p.relative_to(base).as_posix()
        out.append(rel + ("/" if p.is_dir() else ""))
    return out
