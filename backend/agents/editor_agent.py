"""Editor Agent —— 自动剪辑 / 字幕 / 时间线（文档 §18 / §28 / §29）。

根据剧情节奏、对白、镜头长度、BGM、情绪生成初版时间线，并导出 SRT 字幕。
"""
from __future__ import annotations

from ..core import shots as shot_store, store
from ..core.config import STATUS
from ..workflow import engine
from .base import Agent


def _ts(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class EditorAgent(Agent):
    key = "edit"
    name = "Editor Agent"

    def build(self, subtitle_style: str = "漫剧字幕") -> dict:
        shots = shot_store.list_shots(self.ctx.pid)
        video_track, subtitle_track, subtitle_lines = [], [], []
        t = 0.0
        idx = 1
        for s in shots:
            p = s["payload"]
            dur = float(p.get("duration") or 4)
            video_track.append({
                "shot": s["no"], "start": round(t, 2), "duration": dur,
                "shot_type": p.get("shot_type"), "camera": p.get("camera"),
                "emotion": p.get("emotion"), "video": p.get("video"),
                "panel": p.get("panel"),
            })
            if p.get("dialogue"):
                start = round(t + min(0.4, dur * 0.1), 2)
                end = round(min(t + dur, start + max(1.0, len(p["dialogue"]) * 0.18)), 2)
                subtitle_track.append({
                    "shot": s["no"], "start": start, "end": end,
                    "text": p["dialogue"], "speaker": p.get("character") or "",
                    "style": subtitle_style,
                })
                subtitle_lines.append(
                    f"{idx}\n{_ts(start)} --> {_ts(end)}\n"
                    f"{'【' + p['character'] + '】' if p.get('character') else ''}{p['dialogue']}\n"
                )
                idx += 1
            t += dur

        total = round(t, 2)
        timeline = {
            "total": total,
            "fps": 24,
            "video_track": video_track,
            "voice_track": (store.read_json(self.ctx.pid, "audio/timeline.json", {}) or {}).get("dialogue_track", []),
            "music_track": (store.read_json(self.ctx.pid, "audio/timeline.json", {}) or {}).get("music_track", []),
            "sfx_track": [],
            "subtitle_track": subtitle_track,
        }
        store.write_json(self.ctx.pid, "timeline/timeline.json", timeline)
        srt = "\n".join(subtitle_lines)
        store.write_text(self.ctx.pid, "subtitles/subtitle.srt", srt)
        store.write_json(self.ctx.pid, "subtitles/subtitle.json", subtitle_track)

        engine.set_status(self.ctx.pid, "edit", STATUS["REVIEW"],
                          {"total": total, "clips": len(video_track), "subtitles": len(subtitle_track)})
        return {"total": total, "clips": len(video_track), "subtitles": len(subtitle_track)}

    def update_timeline(self, timeline: dict) -> dict:
        store.write_json(self.ctx.pid, "timeline/timeline.json", timeline)
        return {"ok": True}
