"""Script Agent + Director Agent（文档 §10 / §45）。

职责：理解剧本，识别 人物 / 时间 / 地点 / 情节 / 冲突 / 情绪 / 对白 / 动作 / 道具 / 镜头需求。
优先调用真实 LLM Provider；失败或未配置时回退到内置启发式引擎，保证全流程可跑。
"""
from __future__ import annotations

import json

from ..core import db, store
from ..core.config import STATUS
from ..providers.llm import HeuristicLLM, parse_json_loose
from ..workflow import engine
from .base import Agent, AgentContext

ANALYZE_SYSTEM = "你是专业影视导演与编剧分析助手。只输出 JSON，不要任何解释。"

ANALYZE_PROMPT = """请分析下面的剧本，输出严格 JSON：
{{
  "logline": "一句话故事梗概",
  "characters": [{{"name":"", "gender":"", "age":"", "personality":"", "appearance":"", "clothing":"", "voice":"male_deep|male_young|female_soft|female_bright|child|narrator"}}],
  "scenes": [{{"name":"", "location":"", "time":"日|夜|黄昏|清晨", "weather":"", "style":""}}],
  "props": [{{"name":"", "desc":""}}],
  "shots": [{{"no":1, "shot_type":"远景|全景|中景|近景|特写", "camera":"Static|Slow Push-in|Tracking|Pan|Tilt Up", "emotion":"", "character":"", "scene":"", "action":"", "dialogue":"", "duration":4}}]
}}
剧本：
---
{script}
---"""


class ScriptAgent(Agent):
    key = "script"
    name = "Script Agent"

    def run(self, script: str, **kwargs) -> dict:
        result = self._analyze(script)
        store.write_text(self.ctx.pid, "script/script.md", script)
        store.write_json(self.ctx.pid, "script/analysis.json", result)
        engine.set_status(self.ctx.pid, "script", STATUS["REVIEW"], result)
        self.ctx.save_memory({
            "logline": result.get("logline"),
            "characters": [c["name"] for c in result.get("characters", [])],
            "scenes": [s["name"] for s in result.get("scenes", [])],
            "shots_count": len(result.get("shots", [])),
        })
        return result

    def _analyze(self, script: str) -> dict:
        llm = self.ctx.llm()
        if llm and not isinstance(llm, HeuristicLLM):
            try:
                raw = llm.complete(ANALYZE_PROMPT.format(script=script[:12000]),
                                   system=ANALYZE_SYSTEM, json_mode=True, max_tokens=4096)
                data = parse_json_loose(raw)
                if data.get("characters") and data.get("shots"):
                    return self._normalize(data, script)
            except Exception as e:
                print(f"[ScriptAgent] LLM 失败，回退启发式：{e}")
        return self._from_heuristic(HeuristicLLM().analyze(script), script)

    # ---- 归一化 ----------------------------------------------------
    def _from_heuristic(self, h: dict, script: str) -> dict:
        style = self.ctx.style
        chars = []
        for n in h["characters"]:
            chars.append({
                "name": n, "gender": "", "age": "", "personality": "",
                "appearance": f"{style['name']}风格，形象统一", "clothing": "",
                "voice": "narrator" if n in ("旁白",) else "male_deep",
            })
        scenes = [{"name": s, "location": s, "time": "夜" if "夜" in s else "日",
                   "weather": "", "style": style["name"]} for s in h["scenes"]]
        props = [{"name": p, "desc": "剧本中出现的关键道具"} for p in h["props"]]
        shots = []
        for s in h["shots"]:
            shots.append({
                "no": s["no"], "shot_type": s["shot_type"], "camera": s["camera"],
                "emotion": s["emotion"], "character": s.get("character") or "",
                "scene": s.get("scene") or (scenes[0]["name"] if scenes else "主场景"),
                "action": s["summary"], "dialogue": s.get("dialogue") or "",
                "duration": s["duration"],
            })
        return {
            "logline": h["logline"], "characters": chars, "scenes": scenes,
            "props": props, "shots": shots, "stats": h["stats"], "engine": "heuristic",
        }

    def _normalize(self, data: dict, script: str) -> dict:
        chars = data.get("characters") or []
        chars = [c if isinstance(c, dict) else {"name": str(c)} for c in chars]
        scenes = data.get("scenes") or []
        scenes = [s if isinstance(s, dict) else {"name": str(s)} for s in scenes]
        props = data.get("props") or []
        props = [p if isinstance(p, dict) else {"name": str(p)} for p in props]
        shots = data.get("shots") or []
        for i, s in enumerate(shots):
            s.setdefault("no", i + 1)
            s.setdefault("duration", 4)
            s.setdefault("camera", "Static")
            s.setdefault("shot_type", "中景")
        data["stats"] = {
            "characters": len(chars), "scenes": len(scenes), "props": len(props),
            "shots": len(shots),
            "duration": round(sum(float(s.get("duration") or 4) for s in shots), 1),
        }
        data["engine"] = "llm"
        return data


class DirectorAgent(Agent):
    """AI 导演：串起全流程的编排者（文档 §10 / §45）。"""

    key = "director"
    name = "Director Agent"

    def plan(self, request: str) -> dict:
        """文档 §6：让 AI 自己设计工作流。"""
        stages = engine.stage_defs()
        return {
            "request": request,
            "workflow": [{"stage": s["key"], "name": s["name"], "agent": f"{s['key'].capitalize()}Agent"} for s in stages],
            "note": "可在「工作流」中编辑 / 保存为模板 / 导出。",
        }

    def summarize(self) -> dict:
        st = engine.stages_of(self.ctx.pid)
        mem = self.ctx.memory()
        return {
            "project": self.ctx.project["name"],
            "logline": mem.get("logline", ""),
            "progress": engine.progress(self.ctx.pid),
            "stages": [{"key": s["key"], "name": s["name"], "status": s["status"]} for s in st],
        }
