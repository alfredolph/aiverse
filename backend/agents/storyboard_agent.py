"""Storyboard Agent —— 分镜导演（文档 §17 / §45）。

把剧本拆成分镜表：景别 / 时长 / 人物 / 场景 / 动作 / 运镜 / 情绪，并生成分镜画面。
支持单镜头抽卡与局部重生成（§16）。
"""
from __future__ import annotations

import hashlib

from ..core import candidates as gacha
from ..core import entities, shots as shot_store, store
from ..core.config import STATUS
from ..workflow import engine
from .base import Agent
from .render import render_image

SHOT_TYPES = ["远景", "全景", "中景", "近景", "特写"]
CAMERAS = ["Static", "Slow Push-in", "Tracking", "Pan", "Tilt Up"]
EMOTIONS = ["平静", "疑惑", "紧张", "愤怒", "悲伤", "喜悦"]


def _h(t: str) -> int:
    return int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)


class StoryboardAgent(Agent):
    key = "storyboard"
    name = "Storyboard Agent"

    # ---- 构建分镜 --------------------------------------------------
    def build(self, analysis: dict, n: int = 1) -> dict:
        raw = analysis.get("shots") or []
        out = []
        for s in raw:
            no = int(s.get("no") or len(out) + 1)
            panel_rel = f"storyboards/S{no:03d}.svg"
            prompt = self._shot_prompt(s)
            img = render_image(self.ctx, panel_rel, prompt, size="1024x576",
                               seed=_h(f"S{no}") % 100000)
            out.append({
                "no": no,
                "shot_type": s.get("shot_type") or SHOT_TYPES[_h(str(no)) % len(SHOT_TYPES)],
                "camera": s.get("camera") or CAMERAS[_h(f"c{no}") % len(CAMERAS)],
                "emotion": s.get("emotion") or EMOTIONS[_h(f"e{no}") % len(EMOTIONS)],
                "character": s.get("character") or "",
                "scene": s.get("scene") or "",
                "action": s.get("action") or s.get("summary") or "",
                "dialogue": s.get("dialogue") or "",
                "duration": float(s.get("duration") or 4),
                "prompt": prompt,
                "panel": img["path"],
                "panel_provider": img["provider"],
                "panel_fallback": img["fallback"],
                "status": STATUS["DRAFT"],
            })
        shot_store.replace_all(self.ctx.pid, out)
        store.write_json(self.ctx.pid, "storyboards/storyboard.json", out)
        engine.set_status(self.ctx.pid, "storyboard", STATUS["REVIEW"],
                          {"shots": len(out),
                           "duration": round(sum(x["duration"] for x in out), 1)})
        return {"shots": len(out), "duration": round(sum(x["duration"] for x in out), 1)}

    def _shot_prompt(self, s: dict) -> str:
        style = self.ctx.style
        chars = {c["name"]: c["payload"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER)}
        scenes = {c["name"]: c["payload"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_SCENE)}
        who = s.get("character") or ""
        cd = chars.get(who, {})
        sc = scenes.get(s.get("scene") or "", {})
        parts = [
            f"{s.get('shot_type', '中景')}镜头",
            f"{s.get('camera', 'Static')}运镜",
            (f"角色：{who}，{cd.get('appearance','')}，{cd.get('clothing','')}" if who else ""),
            (f"场景：{sc.get('location', s.get('scene',''))}，{sc.get('time','')}，{sc.get('weather','')}" if sc else f"场景：{s.get('scene','')}"),
            f"动作：{s.get('action') or s.get('summary','')}",
            f"情绪：{s.get('emotion','')}",
            f"{style['name']}风格",
        ]
        return "，".join([p for p in parts if p])

    # ---- 抽卡 / 局部重生成（§15 / §16） ---------------------------
    def redraw_shot(self, no: int, hint: str = "", lock: list[str] | None = None,
                    change: list[str] | None = None) -> dict:
        shot = shot_store.get_shot(self.ctx.pid, no)
        if not shot:
            return {"ok": False, "error": "镜头不存在"}
        lock = lock or []
        change = change or []
        p = dict(shot["payload"])
        base = {k: v for k, v in p.items()}
        tries = len(gacha.list_candidates(self.ctx.pid, "storyboard", f"shot:{no:03d}"))
        h = _h(f"{no}:{hint}:{tries}")
        if "action" in change or hint:
            p["action"] = (p.get("action") or "") + (f"（{hint}）" if hint else "")
        if "camera" in change:
            p["camera"] = CAMERAS[h % len(CAMERAS)]
        if "emotion" in change:
            p["emotion"] = EMOTIONS[h % len(EMOTIONS)]
        if "shot_type" in change:
            p["shot_type"] = SHOT_TYPES[h % len(SHOT_TYPES)]
        # 锁定字段保持原值
        for k in lock:
            if k in base:
                p[k] = base[k]

        prompt = self._shot_prompt(p)
        idx = gacha.next_label_index(self.ctx.pid, "storyboard", f"shot:{no:03d}")
        rel = f"storyboards/S{no:03d}_cand_{chr(ord('A') + idx % 26)}.svg"
        img = render_image(self.ctx, rel, prompt, size="1024x576", seed=(_h(prompt) + idx) % 100000)
        p["prompt"] = prompt
        p["panel"] = img["path"]
        p["panel_provider"] = img["provider"]
        p["panel_fallback"] = img["fallback"]
        p["locked"] = lock
        p["changed"] = change
        gacha.add_candidates(self.ctx.pid, "storyboard", f"shot:{no:03d}", [p], start_label=idx)
        return {"ok": True, "shot": p}

    def adopt_shot(self, no: int, candidate_id: str) -> dict:
        cand = gacha.choose(self.ctx.pid, candidate_id)
        if not cand:
            return {"ok": False, "error": "候选不存在"}
        shot_store.update_shot(self.ctx.pid, no, cand["payload"])
        return {"ok": True, "shot": cand["payload"]}

    def reorder(self, order: list[int]) -> dict:
        return {"ok": True, "shots": shot_store.reorder(self.ctx.pid, order)}

    def approve_all(self) -> dict:
        n = 0
        for s in shot_store.list_shots(self.ctx.pid):
            shot_store.update_shot(self.ctx.pid, s["no"], {}, STATUS["APPROVED"])
            n += 1
        return {"ok": True, "approved": n}
