"""Voice Agent —— 配音 / 音效（文档 §27 / §45）。

每个角色拥有固定 Voice ID；生成对白、旁白、环境音、BGM、音效，并落盘为音频时间线。
"""
from __future__ import annotations

import hashlib

from ..core import costs, entities, shots as shot_store, store
from ..core.config import STATUS
from ..workflow import engine
from .base import Agent
from .render import render_voice


class VoiceAgent(Agent):
    key = "voice"
    name = "Voice Agent"

    def generate_all(self) -> dict:
        shots = shot_store.list_shots(self.ctx.pid)
        chars = {c["name"]: c["payload"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER)}
        track = []
        t = 0.0
        for s in shots:
            p = s["payload"]
            dur = float(p.get("duration") or 4)
            entry = {
                "shot": s["no"], "start": round(t, 2), "duration": dur,
                "character": p.get("character") or "",
                "dialogue": p.get("dialogue") or "",
            }
            if p.get("dialogue"):
                who = p.get("character") or "旁白"
                voice = (chars.get(who) or {}).get("voice") or ("narrator" if who == "旁白" else "male_deep")
                rel = f"audio/dialogue/S{s['no']:03d}.wav"
                res = render_voice(self.ctx, rel, p["dialogue"], voice=voice)
                entry["audio"] = res
                entry["voice"] = voice
                costs.record(self.ctx.pid, "tts", seconds=res.get("duration", 0), note=f"S{s['no']:03d} 配音")
            else:
                entry["audio"] = None
            track.append(entry)
            t += dur

        total = round(t, 2)
        # BGM / 环境音占位轨
        bgm = render_voice(self.ctx, "audio/bgm/theme.wav", "BGM" * 20, voice="narrator")
        amb = render_voice(self.ctx, "audio/ambient/room.wav", "AMB" * 16, voice="default")

        timeline = {
            "total": total,
            "dialogue_track": track,
            "music_track": [{"start": 0.0, "duration": total, "audio": bgm, "name": "主题 BGM"}],
            "ambient_track": [{"start": 0.0, "duration": total, "audio": amb, "name": "环境音"}],
            "sfx_track": [],
        }
        store.write_json(self.ctx.pid, "audio/timeline.json", timeline)
        engine.set_status(self.ctx.pid, "voice", STATUS["REVIEW"],
                          {"total": total, "lines": sum(1 for e in track if e.get("audio"))})
        return {"total": total, "lines": sum(1 for e in track if e.get("audio"))}

    def set_voice(self, character: str, voice: str) -> dict:
        chars = {c["name"]: c for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER)}
        c = chars.get(character)
        if not c:
            return {"ok": False, "error": "角色不存在"}
        entities.update_payload(self.ctx.pid, c["id"], {"voice": voice})
        return {"ok": True, "character": character, "voice": voice}


VOICES = [
    {"id": "male_deep", "name": "沉稳男声"},
    {"id": "male_young", "name": "青年男声"},
    {"id": "female_soft", "name": "温柔女声"},
    {"id": "female_bright", "name": "明亮女声"},
    {"id": "child", "name": "童声"},
    {"id": "narrator", "name": "旁白"},
]
