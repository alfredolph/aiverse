"""Video Agent —— 视频生成（文档 §16 / §19 / §23 / §25 / §45）。

- 按分镜逐个生成，支持批量 / 指定镜头 / 局部重生成
- 局部重生成：锁定 Character / Scene / Camera / Style，只改 Action（§16）
- 生成后自动跑 Quality Agent，但采用与否由用户决定
"""
from __future__ import annotations

from ..core import candidates as gacha
from ..core import costs, entities, shots as shot_store, store
from ..core.config import STATUS
from ..workflow import engine
from .base import Agent
from .quality_agent import QualityAgent
from .render import render_video


class VideoAgent(Agent):
    key = "video"
    name = "Video Agent"

    def generate_all(self, resolution: str = "720p", aspect: str = "16:9",
                     only: list[int] | None = None) -> dict:
        shots = shot_store.list_shots(self.ctx.pid)
        done, failed = [], []
        for s in shots:
            if only and s["no"] not in only:
                continue
            try:
                self.generate_shot(s["no"], resolution=resolution, aspect=aspect)
                done.append(s["no"])
            except Exception as e:
                failed.append({"no": s["no"], "error": str(e)})
        engine.set_status(self.ctx.pid, "video", STATUS["REVIEW"],
                          {"generated": done, "failed": failed,
                           "resolution": resolution, "aspect": aspect})
        return {"generated": done, "failed": failed, "count": len(done)}

    def generate_shot(self, no: int, resolution: str = "720p", aspect: str = "16:9",
                      lock: list[str] | None = None, change: list[str] | None = None,
                      hint: str = "") -> dict:
        shot = shot_store.get_shot(self.ctx.pid, no)
        if not shot:
            raise ValueError(f"镜头 S{no:03d} 不存在")

        p = dict(shot["payload"])
        lock = lock or []
        change = change or []
        tries = gacha.next_label_index(self.ctx.pid, "video", f"shot:{no:03d}")

        # 局部重生成：只改指定维度，其余锁定（§16）
        if change or hint:
            if "action" in change or hint:
                p["action"] = (p.get("action") or "").split("（")[0] + (f"（{hint}）" if hint else "")
            if "camera" in change:
                from .storyboard_agent import CAMERAS
                import hashlib
                p["camera"] = CAMERAS[int(hashlib.md5(f'{no}{tries}'.encode()).hexdigest()[:6], 16) % len(CAMERAS)]
            if "emotion" in change:
                from .storyboard_agent import EMOTIONS
                import hashlib
                p["emotion"] = EMOTIONS[int(hashlib.md5(f'e{no}{tries}'.encode()).hexdigest()[:6], 16) % len(EMOTIONS)]

        prompt = self._video_prompt(p, hint)

        # 参考图：优先用已定稿角色图，其次场景图
        ref = None
        chars = {c["name"]: c["payload"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER)}
        scenes = {c["name"]: c["payload"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_SCENE)}
        who = p.get("character") or ""
        if who in chars and "character" not in change and chars[who].get("ref"):
            ref = chars[who]["ref"]
        elif p.get("scene") in scenes and "scene" not in change:
            ref = scenes[p["scene"]].get("ref")

        res = render_video(
            self.ctx, "videos", no, prompt, reference=ref,
            seconds=float(p.get("duration") or 4), resolution=resolution, aspect=aspect,
            lock=lock or (["character", "scene", "camera", "style"] if change else []),
            seed=(abs(hash(prompt)) + tries) % 100000,
        )

        quality = QualityAgent(self.ctx).check_shot(p, res)
        item = {
            "no": no,
            "shot_type": p.get("shot_type"), "camera": p.get("camera"),
            "emotion": p.get("emotion"), "character": who, "scene": p.get("scene"),
            "action": p.get("action"), "dialogue": p.get("dialogue"),
            "duration": p.get("duration"), "prompt": prompt,
            "reference": ref,
            "video": res,
            "quality": quality,
            "locked": lock, "changed": change, "hint": hint,
            "resolution": resolution, "aspect": aspect,
            "status": res.get("status", "placeholder"),
        }

        cand = gacha.add_candidates(self.ctx.pid, "video", f"shot:{no:03d}", [item], start_label=tries)
        # 首版自动采用为当前镜头版本
        shot_store.update_shot(self.ctx.pid, no, {
            "video": res, "quality": quality, "video_prompt": prompt,
            "video_status": res.get("status"), "candidate_id": cand[0]["id"] if cand else None,
        })
        costs.record(self.ctx.pid, "local_gpu" if res.get("fallback") else "video",
                     seconds=float(p.get("duration") or 4) * 3.5,
                     amount=0.0, note=f"S{no:03d} 视频生成")
        return item

    def _video_prompt(self, p: dict, hint: str = "") -> str:
        style = self.ctx.style
        base = p.get("prompt") or p.get("action") or ""
        parts = [
            base,
            f"{p.get('camera','Static')}运镜",
            f"{p.get('emotion','')}情绪",
            f"{style['name']}风格",
            "人物保持一致",
            (hint if hint else ""),
        ]
        return "，".join([x for x in parts if x])

    def adopt(self, no: int, candidate_id: str) -> dict:
        cand = gacha.choose(self.ctx.pid, candidate_id)
        if not cand:
            return {"ok": False, "error": "候选不存在"}
        shot_store.update_shot(self.ctx.pid, no, cand["payload"])
        return {"ok": True, "shot": cand["payload"]}

    def approve_all(self) -> dict:
        n = 0
        for s in shot_store.list_shots(self.ctx.pid):
            if s["payload"].get("video"):
                shot_store.update_shot(self.ctx.pid, s["no"], {}, STATUS["APPROVED"])
                n += 1
        store.write_json(self.ctx.pid, "videos/manifest.json",
                         [s["payload"] for s in shot_store.list_shots(self.ctx.pid)])
        return {"ok": True, "approved": n}
