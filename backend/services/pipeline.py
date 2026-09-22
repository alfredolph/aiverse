"""管线编排：把「阶段」映射到「Agent」（文档 §3 / §6 / §56）。"""
from __future__ import annotations

from typing import Any

from ..agents import (AgentContext, CharacterAgent, EditorAgent, QualityAgent,
                      SceneAgent, ScriptAgent, StoryboardAgent, VideoAgent, VoiceAgent)
from ..core import candidates as gacha
from ..core import costs, entities, projects, shots, store
from ..core.config import STATUS
from ..media import ffmpeg
from ..workflow import engine


def ctx(project_id: str) -> AgentContext:
    p = projects.get(project_id)
    if not p:
        raise ValueError("项目不存在")
    return AgentContext(p)


def analysis(project_id: str) -> dict:
    return store.read_json(project_id, "script/analysis.json", {}) or {}


def run_stage(project_id: str, key: str, options: dict | None = None) -> dict[str, Any]:
    """执行某个阶段的生成。返回该阶段的产物摘要。"""
    options = options or {}
    c = ctx(project_id)

    # ---- 审核门：进入生成前先检查上一阶段是否通过（§48）----------
    g = engine.gate(project_id, key)
    if not g["ok"] and not options.get("force"):
        return {"ok": False, "error": f"请先通过上一阶段「{g['blocked_by_name']}」", **g}

    engine.set_status(project_id, key, STATUS["GENERATING"])

    if key == "script":
        script = options.get("script") or store.read_text(project_id, "script/script.md") or ""
        if not script.strip():
            engine.set_status(project_id, key, STATUS["DRAFT"])
            return {"ok": False, "error": "剧本为空，请先导入或输入剧本"}
        res = ScriptAgent(c).run(script)
        return {"ok": True, "stage": key, "result": res}

    if key == "characters":
        a = analysis(project_id)
        if not a:
            engine.set_status(project_id, key, STATUS["DRAFT"])
            return {"ok": False, "error": "请先完成剧本分析"}
        res = CharacterAgent(c).build(a, n=int(options.get("n") or 3))
        return {"ok": True, "stage": key, "result": res}

    if key == "scenes":
        a = analysis(project_id)
        if not a:
            engine.set_status(project_id, key, STATUS["DRAFT"])
            return {"ok": False, "error": "请先完成剧本分析"}
        res = SceneAgent(c).build(a, n=int(options.get("n") or 2))
        return {"ok": True, "stage": key, "result": res}

    if key == "storyboard":
        a = analysis(project_id)
        if not a:
            engine.set_status(project_id, key, STATUS["DRAFT"])
            return {"ok": False, "error": "请先完成剧本分析"}
        res = StoryboardAgent(c).build(a)
        return {"ok": True, "stage": key, "result": res}

    if key == "video":
        res = VideoAgent(c).generate_all(
            resolution=options.get("resolution") or c.project.get("resolution") or "1080p",
            aspect=options.get("aspect") or c.project.get("aspect") or "16:9",
            only=options.get("only"),
        )
        return {"ok": True, "stage": key, "result": res}

    if key == "voice":
        res = VoiceAgent(c).generate_all()
        return {"ok": True, "stage": key, "result": res}

    if key == "edit":
        res = EditorAgent(c).build(subtitle_style=options.get("subtitle_style") or "漫剧字幕")
        return {"ok": True, "stage": key, "result": res}

    if key == "final":
        plan = ffmpeg.build_export_plan(c.project, shots.list_shots(project_id), {
            "container": options.get("container") or "MP4",
            "resolution": options.get("resolution") or c.project.get("resolution") or "1080p",
            "aspect": options.get("aspect") or c.project.get("aspect") or "9:16",
            "fps": options.get("fps") or 24,
        })
        engine.set_status(project_id, key, STATUS["REVIEW"], plan)
        return {"ok": True, "stage": key, "result": plan}

    return {"ok": False, "error": f"未知阶段 {key}"}


def quality_report(project_id: str) -> dict:
    """全片质量体检（§25）。"""
    c = ctx(project_id)
    qa = QualityAgent(c)
    rows = []
    for s in shots.list_shots(project_id):
        rows.append(qa.check_shot(s["payload"], (s["payload"].get("video") or {})))
    avg = round(sum(r["score"] for r in rows) / max(1, len(rows)), 1)
    return {
        "shots": rows,
        "average": avg,
        "anomalies": [r for r in rows if r["anomaly"]],
        "note": "AI 仅给出检测结果与建议，是否采用由你决定。",
    }


def batch_plan(project_id: str, episodes: int = 3) -> dict:
    """批量生产（§31）：每集独立 Project 目录，角色与场景资产跨集复用。"""
    p = projects.get(project_id)
    return {
        "project": p["name"],
        "episodes": [f"EP{str(i + 1).zfill(3)}" for i in range(episodes)],
        "reuse": {
            "characters": [e["name"] for e in entities.list_by_kind(project_id, entities.KIND_CHARACTER)],
            "scenes": [e["name"] for e in entities.list_by_kind(project_id, entities.KIND_SCENE)],
            "props": [e["name"] for e in entities.list_by_kind(project_id, entities.KIND_PROP)],
        },
        "note": "角色 / 场景 / 道具资产跨集复用，每集独立保存 Project 目录。",
    }
