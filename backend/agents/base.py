"""Agent 基类与共享上下文（文档 §45 / §46）。

所有 Agent 共享 Project Context / Character Bible / Scene Bible / Style Bible / Workflow。
"""
from __future__ import annotations

from typing import Any

from ..core import db, store
from ..providers import registry


class AgentContext:
    """项目上下文（§46 Context 管理：避免每次重新理解整个剧本）。"""

    def __init__(self, project: dict):
        self.project = project
        self.pid = project["id"]

    @property
    def style(self) -> dict:
        from ..core.config import STYLES
        key = self.project.get("style") or "guoman"
        return next((s for s in STYLES if s["key"] == key), STYLES[0])

    def memory(self) -> dict:
        return store.read_json(self.pid, "cache/memory.json", {}) or {}

    def save_memory(self, patch: dict) -> dict:
        m = self.memory()
        m.update(patch)
        store.write_json(self.pid, "cache/memory.json", m)
        return m

    def bible(self, kind: str) -> list[dict]:
        out = []
        for r in db.rows("SELECT * FROM entities WHERE project_id=? AND kind=? ORDER BY rowid",
                         (self.pid, kind)):
            d = dict(r)
            d["payload"] = db.loads(r["payload"], {})
            out.append(d)
        return out

    def llm(self):
        return registry.get_llm(self.project.get("meta", {}).get("llm_provider"))

    def image(self):
        return registry.get_image(self.project.get("meta", {}).get("image_provider"))

    def video(self):
        return registry.get_video(self.project.get("meta", {}).get("video_provider"))

    def tts(self):
        return registry.get_tts(self.project.get("meta", {}).get("tts_provider"))


class Agent:
    """Agent 基类。"""

    key = "agent"
    name = "Agent"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    def run(self, **kwargs) -> dict[str, Any]:
        raise NotImplementedError
