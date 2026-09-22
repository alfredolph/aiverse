"""LLM Provider 实现。

包含：
  - HeuristicLLM  : 零依赖离线引擎（默认），保证无 Key 也能完整跑通全流程
  - OpenAICompatLLM : 任何 OpenAI 兼容 API（OpenAI / DeepSeek / Claude 代理 / 本地 vLLM / WorkBuddy）
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from .base import LLMProvider

# ---------------------------------------------------------------- 离线启发式引擎
EMOTION_LEX = {
    "疑惑": ["疑惑", "不解", "皱眉", "迟疑", "愣", "奇怪", "诧异"],
    "愤怒": ["冷笑", "冷声", "怒", "吼", "喝", "咬牙", "咆哮", "愤", "冷厉", "阴沉"],
    "悲伤": ["哭", "泪", "悲", "痛", "哽咽", "绝望", "颤抖"],
    "喜悦": ["笑", "喜", "欢", "开心", "轻松", "眉开"],
    "紧张": ["紧张", "冷汗", "心跳", "屏住", "急促", "危险", "杀"],
    "平静": ["沉默", "平静", "淡淡", "静静", "缓缓"],
}

CAMERA_LEX = {
    "Slow Push-in": ["走近", "靠近", "推门", "踏入", "缓缓"],
    "Tracking": ["追", "跑", "奔", "穿过", "跟随"],
    "Pan": ["转头", "环视", "扫视", "望向", "看向"],
    "Static": ["站着", "坐着", "停", "静", "沉默"],
    "Tilt Up": ["抬头", "仰望", "升起"],
    "Close-up": ["眼神", "眼睛", "脸", "手", "唇", "眉"],
}

SHOT_TYPE_LEX = {
    "远景": ["街道", "山", "天空", "全景", "城", "远处", "旷野", "屋顶"],
    "全景": ["房间", "药铺", "大厅", "庭院", "广场", "屋内"],
    "中景": ["走近", "坐下", "推门", "拿起", "转身", "递"],
    "近景": ["看着", "说道", "盯着", "低声"],
    "特写": ["眼神", "眼睛", "手", "嘴角", "泪水", "指尖", "伤口"],
}

PROP_LEX = [
    "药瓶", "长剑", "短刀", "手机", "马车", "桌子", "椅子", "茶杯", "灯笼", "雨伞",
    "书信", "信封", "玉佩", "卷轴", "钥匙", "铜镜", "酒壶", "银针", "药方", "账本",
    "剑", "刀", "伞", "灯", "酒", "信", "药", "书", "门", "窗",
]

NAME_STOP_CHARS = set(
    "他说她我你您这那什么怎么时候地方声音目光神情心中眼手是的不了和与就都还又很太更最只在被把给对从向以为着过们当便再"
    "一二三四五六七八九十个上下里外前后些会能要使得来去到已没经但而因为所如果虽然还每各种位条只件"
)
NAME_BLACK = set("""一个 什么 怎么 时候 地方 声音 目光 神情 心中 眼中 手心 自己 我们 你们 他们 她们 这个 那个 这样 那样 这么 那么
一声 一下 一会 一起 一直 已经 突然 忽然 然后 于是 但是 因为 所以 如果 虽然 而且 并且 只是 还是 就是 就是 可以 不能 没有 不知
抬头 低头 转身 走过 走来 看着 听到 知道 觉得 以为 发现 出现 说话 开口 笑了 冷笑 沉默 缓缓 轻轻 慢慢 悄悄 立刻 马上 终于""".split())


def _ngram_counts(text: str) -> dict[str, int]:
    """统计所有 2-3 字连续片段的出现次数（跨标点不合并）。"""
    from collections import Counter
    cnt: Counter = Counter()
    for run in re.findall(r"[\u4e00-\u9fa5]+", text):
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                cnt[run[i:i + n]] += 1
    return cnt
NAME_VERB_TAIL = set("说道问答喊叫笑看走来去想的了是又还便就再望盯冷笑低声开口转身抬低")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?…])|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _is_scene_header(s: str) -> bool:
    return bool(re.fullmatch(r"[【\[（(][^】\]）)]{1,20}[】\]）)]", s.strip()))


def _clean_name(n: str) -> str:
    while len(n) > 2 and n[-1] in NAME_VERB_TAIL:
        n = n[:-1]
    return n


def _extract_names(text: str) -> list[str]:
    scores: dict[str, int] = {}
    grams = _ngram_counts(text)

    def ok(n: str) -> bool:
        if not (2 <= len(n) <= 3):
            return False
        if n in NAME_BLACK:
            return False
        if any(ch in NAME_STOP_CHARS for ch in n):
            return False
        return True

    def add(n: str, w: int) -> None:
        n = _clean_name(n)
        if ok(n):
            scores[n] = scores.get(n, 0) + w

    # 1) 行首 / 标点后的「名字：」——最强信号
    for m in re.finditer(r"(?:^|(?<=[\n。！？，；、\s]))([\u4e00-\u9fa5]{2,4})[：:]", text, re.M):
        add(m.group(1), 6)
    # 2) 「名字说 / 名字道 / 名字冷笑」
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,4})(?=说|道|问|答|喊|叫|开口|低声|冷笑)", text):
        add(m.group(1), 3)
    # 3) 句首名词（主语位置）
    for m in re.finditer(r"(?:^|(?<=[\n。！？；]))\s*([\u4e00-\u9fa5]{2,3})", text, re.M):
        add(m.group(1), 2)
    # 4) 引号前的说话人
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,3})[^\u4e00-\u9fa5]{0,2}[“「]", text):
        add(m.group(1), 3)

    # 5) 高频专名兜底：全文出现 ≥3 次的 2 字片段（人名往往反复出现）
    for n, c in grams.items():
        if c >= 3 and ok(n):
            scores[n] = scores.get(n, 0) + c * 2

    # 过滤：总分 ≥4 才认定为角色，避免把普通名词当人名
    final = {n: s for n, s in scores.items() if s >= 4}
    ranked = sorted(final.items(), key=lambda kv: -kv[1])
    return [n for n, _ in ranked][:12]


def _extract_scenes(text: str) -> list[str]:
    explicit: list[str] = []   # 显式写出来的场景标记，可信
    guess: list[str] = []      # 靠介词猜出来的地点，得复核

    # 显式场景标记 【xx】（xx）
    for m in re.finditer(r"[【\[（(]([^】\]）)]{2,16})[】\]）)]", text):
        explicit.append(m.group(1).strip())
    # 「场景：xx」「地点：xx」
    for m in re.finditer(r"(?:场景|地点|内景|外景)[：:]\s*([^\n，。；]{2,16})", text):
        explicit.append(m.group(1).strip())
    # 介词 + 地点
    for m in re.finditer(r"(?:在|来到|走进|进入|回到|站在|推开)([\u4e00-\u9fa5]{2,8}?)(?:里|内|中|外|前|后|门口|之中|的木门|的门)", text):
        guess.append(m.group(1).strip())

    def clean(s: str) -> str:
        s = re.sub(r"^(?:场景|地点|内景|外景)\s*", "", s)
        # 去掉尾部时间词
        s = re.sub(r"[\s·,，]*(日|夜|黄昏|清晨|早晨|凌晨|白天|晚上|傍晚|午后|晨|午)$",
                   "", s).strip()
        return re.sub(r"\s+", " ", s)

    def keep(pairs: list[tuple[str, bool]]) -> list[str]:
        seen, out = set(), []
        for s, is_explicit in pairs:
            if not (2 <= len(s) <= 16) or s in seen:
                continue
            # 只被提到过一次的「地点」多半是件东西，不是场景：
            # 「你要的药，不在箱子里」会猜出「箱子」，「站在一块青石前」会猜出「一块青石」。
            # 真正的场景在一集里总要反复出现，所以要求出现 ≥2 次。
            if not is_explicit and text.count(s) < 2:
                continue
            seen.add(s)
            out.append(s)
        return out[:12]

    pairs = [(clean(s), True) for s in explicit] + [(clean(s), False) for s in guess]
    out = keep(pairs)
    # 过滤太狠就退回去用没过滤的版本 —— 宁可场景名糙一点，也别让分镜全落到「主场景」
    return out or keep([(clean(s), True) for s in explicit + guess])


def _extract_props(text: str) -> list[str]:
    found = []
    for p in PROP_LEX:
        if p in text:
            found.append(p)
    # 去重并去掉被更长词包含的短词
    found = sorted(set(found), key=len, reverse=True)
    out = []
    for p in found:
        if not any(p != q and p in q for q in out):
            out.append(p)
    return out[:12]


def _detect_emotion(s: str) -> str:
    for emo, words in EMOTION_LEX.items():
        if any(w in s for w in words):
            return emo
    return "平静"


def _detect_camera(s: str) -> str:
    for cam, words in CAMERA_LEX.items():
        if any(w in s for w in words):
            return cam
    return "Static"


def _detect_shot_type(s: str) -> str:
    for t, words in SHOT_TYPE_LEX.items():
        if any(w in s for w in words):
            return t
    return "中景"


def _detect_dialogue(s: str) -> str | None:
    m = re.search(r"[“「]([^”」]{1,120})[”」]", s)
    if m:
        return m.group(1).strip()
    # 「…：台词」剧本格式（冒号可出现在句中）
    m = re.search(r"[：:]\s*(.+)$", s.strip())
    if m and len(m.group(1).strip()) >= 2:
        return m.group(1).strip()
    return None


def _split_speaker(s: str) -> tuple[str | None, str]:
    """把「掌柜：这么晚了」拆成 ('掌柜', '这么晚了')。"""
    m = re.match(r"^([\u4e00-\u9fa5]{2,4})[：:]\s*(.+)$", s.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, s.strip()


def _action_of(s: str, dialogue: str | None, speaker: str | None) -> str:
    """从「动作＋台词」中切出纯动作描述。"""
    if dialogue:
        idx = s.find(dialogue)
        if idx > 0:
            prefix = s[:idx].rstrip("：: ，,")
            if len(prefix) >= 4:
                return prefix
    return s.strip()


class HeuristicLLM(LLMProvider):
    """离线启发式引擎：无网络、无 Key，用于 MVP 默认体验与演示。"""

    def __init__(self, id="llm-heuristic", name="内置启发式引擎（离线）"):
        super().__init__(id=id, name=name, models=["heuristic-v1"])

    def cost(self):
        return {"unit": "free", "price": 0.0}

    def complete(self, prompt: str, system: str = "", json_mode: bool = False,
                 max_tokens: int = 2048) -> str:
        # 该 Provider 不真正做通用对话，只服务结构化任务。
        # 由 agents 层直接调用 analyze()，这里作为兜底。
        return json.dumps(self.analyze(prompt), ensure_ascii=False)

    # ---- 结构化能力：剧本分析 -------------------------------------
    def analyze(self, script: str) -> dict:
        raw_sentences = _split_sentences(script)
        names = _extract_names(script)
        scenes = _extract_scenes(script)
        props = _extract_props(script)

        # 场景标题行不参与分镜，但可作为场景归属提示
        sentences = [s for s in raw_sentences if not _is_scene_header(s)]
        current_scene = scenes[0] if scenes else "主场景"

        shots = []
        for s in sentences:
            if _is_scene_header(s):
                continue
            # 场景切换提示
            for sc in scenes:
                if sc and (sc in s or (len(sc) >= 2 and sc[:2] in s)):
                    current_scene = sc
                    break
            dialogue = _detect_dialogue(s)
            speaker, spoken = _split_speaker(s)
            who = speaker or next((n for n in names if n in s), None)
            action = _action_of(s, dialogue, who)
            shots.append({
                "no": len(shots) + 1,
                "summary": s[:40],
                "shot_type": _detect_shot_type(action),
                "camera": _detect_camera(action),
                "emotion": _detect_emotion(action),
                "character": who,
                "scene": current_scene,
                "action": action[:60],
                "dialogue": dialogue,
                "duration": 4.0 if dialogue else 3.0,
            })

        # 合并过短的镜头，控制总时长
        merged: list[dict] = []
        for sh in shots:
            if merged and merged[-1]["duration"] < 2.5 and not merged[-1]["dialogue"] and not sh["dialogue"]:
                merged[-1]["summary"] += "；" + sh["summary"]
                merged[-1]["duration"] += sh["duration"]
            else:
                merged.append(sh)
        for idx, sh in enumerate(merged):
            sh["no"] = idx + 1
            sh["duration"] = round(min(8.0, max(2.0, sh["duration"])), 1)

        logline = next((s for s in sentences if len(s) >= 6), (sentences[0] if sentences else ""))

        return {
            "logline": logline[:60],
            "characters": names,
            "scenes": scenes or ["主场景"],
            "props": props,
            "shots": merged,
            "stats": {
                "characters": len(names),
                "scenes": len(scenes or ["主场景"]),
                "props": len(props),
                "shots": len(merged),
                "duration": round(sum(s["duration"] for s in merged), 1),
            },
        }


# ---------------------------------------------------------------- OpenAI 兼容
class OpenAICompatLLM(LLMProvider):
    """任何 OpenAI 兼容 /chat/completions 接口。"""

    def __init__(self, id, name, base_url, api_key, models=None, meta=None):
        super().__init__(id=id, name=name, base_url=base_url, api_key=api_key,
                         models=models or ["gpt-4o-mini"], meta=meta)

    def cost(self):
        return {"unit": "token", "price": float(self.meta.get("price_per_1k", 0.0))}

    def limits(self):
        return {"timeout": 120, "max_tokens": 8192}

    def health(self):
        if not self.base_url:
            return {"ok": False, "detail": "缺少 Base URL"}
        if not self.api_key:
            return {"ok": False, "detail": "缺少 API Key"}
        return {"ok": True, "detail": "已配置"}

    def complete(self, prompt: str, system: str = "", json_mode: bool = False,
                 max_tokens: int = 2048) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        model = self.models[0] if self.models else "gpt-4o-mini"
        payload: dict = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"LLM HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}")


def parse_json_loose(text: str) -> dict:
    """从模型输出中稳健地抠出 JSON。"""
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}
