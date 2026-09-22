"""角色 / 场景 / 道具 Agent（文档 §11 / §12 / §13 / §45 / §49）。

每个资产生成多份候选（抽卡），支持：
  - 采用某候选
  - 继续抽卡
  - 修改要求后重抽
  - 锁定字段重抽
"""
from __future__ import annotations

import hashlib

from ..core import candidates as gacha
from ..core import entities, store
from ..core.config import STATUS
from ..workflow import engine
from .base import Agent
from .render import render_image

AGE_POOL = ["18", "22", "25", "28", "32", "38"]
PERSONALITY_POOL = ["冷峻", "温柔", "机敏", "热血", "沉静", "狡黠", "坚毅", "天真"]
APPEARANCE_POOL = [
    "黑发，眉眼锋利，身材偏瘦", "长发及腰，气质清冷", "短发利落，轮廓分明",
    "微卷发，眼神温和", "束发高冠，面容俊朗", "半遮面，眼下有浅疤",
]
CLOTHING_POOL = ["白色长袍", "玄色劲装", "素色布衣", "锦缎长衫", "深色斗篷", "轻甲"]
VOICE_POOL = ["male_deep", "male_young", "female_soft", "female_bright"]
TIME_POOL = ["日", "夜", "黄昏", "清晨"]
WEATHER_POOL = ["晴", "阴", "雨", "雪", "雾"]


def _h(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


class CharacterAgent(Agent):
    key = "characters"
    name = "Character Agent"

    def build(self, analysis: dict, n: int = 3) -> dict:
        chars = analysis.get("characters") or []
        created = []
        for c in chars:
            name = c.get("name") or "未命名"
            g = self._group_key(name)
            if not gacha.list_candidates(self.ctx.pid, "characters", g):
                self._draw(name, base=c, n=n)
            self._materialize(name)
            created.append(name)
        engine.set_status(self.ctx.pid, "characters", STATUS["REVIEW"],
                          {"characters": created, "count": len(created)})
        return {"characters": created, "count": len(created)}

    # ---- 资产化 ----------------------------------------------------
    def _materialize(self, name: str) -> bool:
        """把抽出来的候选落成角色资产（已经建过就不动）。

        为什么必须有这一步：`_draw()` 只往候选表里塞东西，实体要等用户点「采用」
        才创建。于是流水线跑完 8 阶段、角色阶段也 APPROVED 了，角色面板却还是空的，
        「音色」下拉会提示「请先生成角色设计」，质量检查还会把分镜里出现的角色
        全报成「未资产化」—— 明明都生成过了。

        道具那边本来就在 `SceneAgent.build()` 里 upsert，角色/场景漏了，这里补齐。
        状态给 DRAFT：审核门的意义还在，用户点「全部通过」才转 APPROVED。
        """
        if entities.get_by_name(self.ctx.pid, entities.KIND_CHARACTER, name):
            return False
        cands = gacha.list_candidates(self.ctx.pid, "characters", self._group_key(name))
        if not cands:
            return False
        payload = dict(cands[0]["payload"])
        entities.upsert(self.ctx.pid, entities.KIND_CHARACTER, name, payload, STATUS["DRAFT"])
        store.write_json(self.ctx.pid, f"characters/{name}/design.json", payload)
        return True

    def materialize_all(self) -> int:
        """把所有已抽出的候选都落成资产，返回新建数量。幂等。"""
        n = 0
        for c in gacha.list_candidates(self.ctx.pid, "characters"):
            name = (c.get("payload") or {}).get("name") or ""
            if name and self._materialize(name):
                n += 1
        return n

    def _group_key(self, name: str) -> str:
        return f"char:{name}"

    def _draw(self, name: str, base: dict | None = None, n: int = 3,
              hint: str = "", lock: list[str] | None = None) -> list[dict]:
        base = base or {}
        lock = lock or []
        style = self.ctx.style
        g = self._group_key(name)
        start = gacha.next_label_index(self.ctx.pid, "characters", g)
        items = []
        for i in range(n):
            idx = start + i
            h = _h(f"{name}:{idx}")
            design = {
                "name": name,
                "gender": base.get("gender") or ("男" if h % 2 == 0 else "女"),
                "age": base.get("age") or AGE_POOL[h % len(AGE_POOL)],
                "personality": base.get("personality") or PERSONALITY_POOL[(h >> 3) % len(PERSONALITY_POOL)],
                "appearance": base.get("appearance") or APPEARANCE_POOL[(h >> 5) % len(APPEARANCE_POOL)],
                "clothing": base.get("clothing") or CLOTHING_POOL[(h >> 7) % len(CLOTHING_POOL)],
                "voice": base.get("voice") or VOICE_POOL[(h >> 9) % len(VOICE_POOL)],
                "negative": "extra fingers, deformed face, inconsistent identity",
                "style": style["name"],
                "hint": hint,
                "locked": lock,
            }
            prompt = (f"{design['name']}，{design['gender']}，{design['age']}岁，"
                      f"{design['appearance']}，{design['clothing']}，{style['name']}风格，"
                      f"角色设定图，正脸，半身" + (f"，{hint}" if hint else ""))
            rel = f"characters/{name}/cand_{chr(ord('A') + idx % 26)}.svg"
            img = render_image(self.ctx, rel, prompt, size="640x896",
                               negative=design["negative"], seed=h % 100000)
            design["ref"] = img["path"]
            design["ref_provider"] = img["provider"]
            design["ref_fallback"] = img["fallback"]
            items.append(design)
        return gacha.add_candidates(self.ctx.pid, "characters", g, items, start_label=start)

    # ---- 抽卡操作 --------------------------------------------------
    def redraw(self, name: str, n: int = 3, hint: str = "", lock: list[str] | None = None) -> list[dict]:
        return self._draw(name, n=n, hint=hint, lock=lock)

    def adopt(self, name: str, candidate_id: str) -> dict:
        g = self._group_key(name)
        cand = gacha.choose(self.ctx.pid, candidate_id)
        if not cand:
            return {"ok": False, "error": "候选不存在"}
        payload = dict(cand["payload"])
        payload["status"] = STATUS["APPROVED"]
        entities.upsert(self.ctx.pid, entities.KIND_CHARACTER, name, payload, STATUS["APPROVED"])
        store.write_json(self.ctx.pid, f"characters/{name}/design.json", payload)
        return {"ok": True, "name": name, "design": payload}

    def approve_all(self) -> dict:
        n = 0
        for c in entities.list_by_kind(self.ctx.pid, entities.KIND_CHARACTER):
            entities.set_status(self.ctx.pid, c["id"], STATUS["APPROVED"])
            n += 1
        return {"ok": True, "approved": n}


class SceneAgent(Agent):
    key = "scenes"
    name = "Scene Agent"

    def build(self, analysis: dict, n: int = 2) -> dict:
        scenes = analysis.get("scenes") or []
        props = analysis.get("props") or []
        created_s, created_p = [], []
        for s in scenes:
            name = s.get("name") or "主场景"
            g = f"scene:{name}"
            if not gacha.list_candidates(self.ctx.pid, "scenes", g):
                self._draw(name, base=s, n=n)
            self._materialize(name)
            created_s.append(name)
        for p in props:
            name = p.get("name") or "道具"
            # 已经建过就不动：重复跑 build 不该让版本号虚涨
            if not entities.get_by_name(self.ctx.pid, entities.KIND_PROP, name):
                payload = {"name": name, "desc": p.get("desc", ""), "style": self.ctx.style["name"]}
                entities.upsert(self.ctx.pid, entities.KIND_PROP, name, payload, STATUS["DRAFT"])
                store.write_json(self.ctx.pid, f"props/{name}/design.json", payload)
            created_p.append(name)
        engine.set_status(self.ctx.pid, "scenes", STATUS["REVIEW"],
                          {"scenes": created_s, "props": created_p,
                           "count": len(created_s) + len(created_p)})
        return {"scenes": created_s, "props": created_p,
                "count": len(created_s) + len(created_p)}

    # ---- 资产化 ----------------------------------------------------
    def _materialize(self, name: str) -> bool:
        """把抽出来的场景候选落成场景资产（已经建过就不动）。

        和 CharacterAgent._materialize 同一个理由：只抽卡不落实体的话，
        流水线跑完场景面板还是空的，分镜里的场景会被质量检查报成「未资产化」。
        状态给 DRAFT，等用户点「全部通过」才转 APPROVED。
        """
        if entities.get_by_name(self.ctx.pid, entities.KIND_SCENE, name):
            return False
        cands = gacha.list_candidates(self.ctx.pid, "scenes", self._group_key(name))
        if not cands:
            return False
        payload = dict(cands[0]["payload"])
        entities.upsert(self.ctx.pid, entities.KIND_SCENE, name, payload, STATUS["DRAFT"])
        store.write_json(self.ctx.pid, f"scenes/{name}/design.json", payload)
        return True

    def materialize_all(self) -> int:
        """把所有已抽出的场景候选都落成资产，返回新建数量。幂等。"""
        n = 0
        for c in gacha.list_candidates(self.ctx.pid, "scenes"):
            name = (c.get("payload") or {}).get("name") or ""
            if name and self._materialize(name):
                n += 1
        return n

    def _group_key(self, name: str) -> str:
        return f"scene:{name}"

    def _draw(self, name: str, base: dict | None = None, n: int = 2,
              hint: str = "", lock: list[str] | None = None) -> list[dict]:
        base = base or {}
        style = self.ctx.style
        g = self._group_key(name)
        start = gacha.next_label_index(self.ctx.pid, "scenes", g)
        items = []
        for i in range(n):
            idx = start + i
            h = _h(f"{name}:{idx}")
            design = {
                "name": name,
                "location": base.get("location") or name,
                "time": base.get("time") or TIME_POOL[h % len(TIME_POOL)],
                "weather": base.get("weather") or WEATHER_POOL[(h >> 3) % len(WEATHER_POOL)],
                "style": style["name"],
                "hint": hint,
                "locked": lock or [],
            }
            prompt = (f"{design['location']}，{design['time']}，{design['weather']}，"
                      f"{style['name']}风格，场景概念图，无人，宽幅" + (f"，{hint}" if hint else ""))
            rel = f"scenes/{name}/cand_{chr(ord('A') + idx % 26)}.svg"
            img = render_image(self.ctx, rel, prompt, size="1024x576", seed=h % 100000)
            design["ref"] = img["path"]
            design["ref_provider"] = img["provider"]
            design["ref_fallback"] = img["fallback"]
            items.append(design)
        return gacha.add_candidates(self.ctx.pid, "scenes", g, items, start_label=start)

    def redraw(self, name: str, n: int = 2, hint: str = "", lock: list[str] | None = None) -> list[dict]:
        return self._draw(name, n=n, hint=hint, lock=lock)

    def adopt(self, name: str, candidate_id: str) -> dict:
        cand = gacha.choose(self.ctx.pid, candidate_id)
        if not cand:
            return {"ok": False, "error": "候选不存在"}
        payload = dict(cand["payload"])
        entities.upsert(self.ctx.pid, entities.KIND_SCENE, name, payload, STATUS["APPROVED"])
        store.write_json(self.ctx.pid, f"scenes/{name}/design.json", payload)
        return {"ok": True, "name": name, "design": payload}

    def approve_all(self) -> dict:
        n = 0
        for kind in (entities.KIND_SCENE, entities.KIND_PROP):
            for e in entities.list_by_kind(self.ctx.pid, kind):
                entities.set_status(self.ctx.pid, e["id"], STATUS["APPROVED"])
                n += 1
        return {"ok": True, "approved": n}
