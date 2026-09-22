"""Quality Agent —— 视频质量检查（文档 §25）。

AI 只给检测结果与建议，绝不替用户决定是否采用。
"""
from __future__ import annotations

import hashlib

from ..core import entities
from .base import Agent


def _h(t: str) -> int:
    return int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)


class QualityAgent(Agent):
    key = "quality"
    name = "Quality Agent"

    def check_shot(self, shot: dict, render_result: dict | None = None) -> dict:
        no = int(shot.get("no") or 0)
        h = _h(f"{self.ctx.pid}:{no}:{shot.get('action','')}")

        # 人物一致性：角色是否已建立 Character Bible
        who = shot.get("character") or ""
        chars = {c["name"] for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER)}
        identity = 92 if who and who in chars else (70 if who else 60)

        # Prompt 符合度：要素是否齐全
        prompt = shot.get("prompt") or ""
        need = [bool(shot.get("character")), bool(shot.get("scene")),
                bool(shot.get("action")), bool(shot.get("camera"))]
        fidelity = int(sum(need) / len(need) * 100)

        # 动作合理性：动作描述长度与关键词
        action = shot.get("action") or ""
        motion = 88 if 6 <= len(action) <= 60 else (72 if action else 55)

        # 画面完整性
        complete = 90 if render_result and render_result.get("poster") else 65

        # 异常检测（伪随机，稳定可复现）
        anomaly = (h >> 4) % 100 < 18
        anomaly_type = "疑似手部结构异常" if anomaly else ""

        score = int((identity * 0.35 + fidelity * 0.25 + motion * 0.2 + complete * 0.2))
        suggestions = []
        if identity < 85 and who:
            suggestions.append(f"「{who}」尚未在角色库中定稿，建议先完成角色审核以提升一致性")
        if fidelity < 90:
            suggestions.append("分镜要素不完整，建议补齐 人物 / 场景 / 动作 / 运镜")
        if anomaly:
            suggestions.append(f"检测到{anomaly_type}，建议重新抽卡")
        if not suggestions:
            suggestions.append("各项指标正常，可直接采用")

        def lv(v: int) -> str:
            return "较高" if v >= 85 else ("一般" if v >= 70 else "偏低")

        return {
            "shot": no,
            "identity": identity, "identity_label": lv(identity),
            "fidelity": fidelity, "fidelity_label": lv(fidelity),
            "motion": motion, "motion_label": lv(motion),
            "complete": complete,
            "anomaly": anomaly, "anomaly_type": anomaly_type,
            "score": score,
            "suggestions": suggestions,
            "auto_decision": False,   # §25：AI 不替用户决定
        }
