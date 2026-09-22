"""媒体 Provider 实现：图片 / 视频 / TTS。

说明：
  - 默认使用「离线占位 Provider」，产出真实可查看的文件（SVG 分镜图 / WAV 音频 / 镜头清单），
    保证没有 GPU、没有 ffmpeg、没有 API Key 的环境下全流程也能跑通并落盘。
  - 接真实模型时，只需实现同样的 Provider 接口（见 H3ComfyUIProvider / 云端 Provider 示例）。
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from pathlib import Path

from .base import ImageProvider, TTSProvider, VideoProvider

PALETTE = [
    ("#1b2a41", "#3f6fa8"), ("#2a1b3d", "#7b4fa8"), ("#3d1b1b", "#a85b3f"),
    ("#1b3d2f", "#3fa87b"), ("#3d3a1b", "#a8a03f"), ("#1b2f3d", "#3f8fa8"),
    ("#3d1b2f", "#a83f7b"), ("#2f3d1b", "#7ba83f"),
]


def _seed_of(text: str, seed: int | None = None) -> int:
    if seed is not None:
        return int(seed)
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap(s: str, n: int = 14) -> list[str]:
    s = s or ""
    return [s[i:i + n] for i in range(0, min(len(s), n * 3), n)] or [""]


# ---------------------------------------------------------------- 图片
class PlaceholderImageProvider(ImageProvider):
    """生成风格化的 SVG 参考图（可当分镜/立绘占位）。"""

    def __init__(self, id="img-placeholder", name="内置占位图 Provider"):
        super().__init__(id=id, name=name, models=["placeholder-svg"])

    def cost(self):
        return {"unit": "free", "price": 0.0}

    def generate(self, prompt, negative="", size="768x1024", reference=None, seed=None):
        sd = _seed_of(prompt + (reference or ""), seed)
        c1, c2 = PALETTE[sd % len(PALETTE)]
        w, h = (int(x) for x in size.lower().split("x"))
        lines = _wrap(prompt, 16)[:4]
        circles = "".join(
            f'<circle cx="{60 + (sd >> (i * 3)) % (w - 120)}" cy="{90 + (sd >> (i * 5)) % (h - 180)}" '
            f'r="{18 + (sd >> (i * 2)) % 46}" fill="#ffffff" opacity="0.06"/>'
            for i in range(7)
        )
        text = "".join(
            f'<text x="40" y="{h - 150 + i * 30}" font-size="24" fill="#e9eef7" '
            f'font-family="system-ui,Microsoft YaHei" opacity="0.92">{_esc(l)}</text>'
            for i, l in enumerate(lines)
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/></linearGradient></defs>
<rect width="{w}" height="{h}" fill="url(#g)"/>{circles}
<rect x="20" y="20" width="{w - 40}" height="{h - 40}" fill="none" stroke="#ffffff" stroke-opacity="0.18"/>
<text x="40" y="70" font-size="22" fill="#ffffff" opacity="0.65" font-family="system-ui,Microsoft YaHei">AIVerse · 参考图占位</text>
{text}
<text x="40" y="{h - 40}" font-size="18" fill="#ffffff" opacity="0.5" font-family="system-ui,Microsoft YaHei">seed {sd}</text>
</svg>"""
        return {"path": None, "svg": svg, "seed": sd,
                "meta": {"provider": self.name, "size": size, "negative": negative}}


class ComfyUIImageProvider(ImageProvider):
    """把请求转发给本地 ComfyUI（真实出图）。未连接时抛错，由上层回退占位。"""

    def __init__(self, id, name, base_url, api_key="", models=None, meta=None):
        super().__init__(id=id, name=name, base_url=base_url, api_key=api_key,
                         models=models or [], meta=meta)

    def health(self):
        return {"ok": bool(self.base_url), "detail": self.base_url or "缺少 ComfyUI 地址"}

    def generate(self, prompt, negative="", size="768x1024", reference=None, seed=None):
        raise RuntimeError(
            "ComfyUI Image Provider 未接通：请在「设置 → Provider」中填写 ComfyUI 地址并加载对应工作流。"
        )


# ---------------------------------------------------------------- 视频
class PlaceholderVideoProvider(VideoProvider):
    """离线占位：产出镜头清单 + 分镜海报，标记为「待真实 Provider 渲染」。"""

    def __init__(self, id="video-placeholder", name="内置占位视频 Provider"):
        super().__init__(id=id, name=name, models=["placeholder"])

    def cost(self):
        return {"unit": "free", "price": 0.0}

    def generate(self, prompt, reference=None, seconds=5.0, resolution="720p",
                 aspect="16:9", lock=None, seed=None):
        sd = _seed_of(prompt, seed)
        c1, c2 = PALETTE[sd % len(PALETTE)]
        ratio = {"16:9": (1280, 720), "9:16": (720, 1280), "3:4": (900, 1200), "1:1": (1024, 1024)}
        w, h = ratio.get(aspect, (1280, 720))
        poster = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/></linearGradient></defs>
<rect width="{w}" height="{h}" fill="url(#g)"/>
<text x="48" y="{h // 2}" font-size="34" fill="#ffffff" opacity="0.92" font-family="system-ui,Microsoft YaHei">分镜海报（待渲染）</text>
<text x="48" y="{h // 2 + 44}" font-size="22" fill="#ffffff" opacity="0.7" font-family="system-ui,Microsoft YaHei">{_esc(prompt[:36])}</text>
<text x="48" y="{h - 40}" font-size="18" fill="#ffffff" opacity="0.55" font-family="system-ui,Microsoft YaHei">{resolution} · {aspect} · {seconds}s · seed {sd}</text>
</svg>"""
        manifest = {
            "prompt": prompt, "reference": reference, "seconds": seconds,
            "resolution": resolution, "aspect": aspect, "locked": lock or [],
            "seed": sd, "provider": self.name,
            "status": "placeholder",
            "note": "离线占位产物。接入 MiniMax H3 / 云端视频 Provider 后即可输出真实 MP4。",
        }
        return {"path": None, "svg": poster, "manifest": manifest, "seed": sd,
                "meta": manifest}


class H3ComfyUIProvider(VideoProvider):
    """MiniMax H3（经 ComfyUI）Adapter —— 文档 §36 / §37 的执行引擎接口。

    真实接入方式：向本地 ComfyUI 的 /prompt 提交 H3 Ref2V 工作流，
    轮询 /history 取结果，再下载到项目 videos/ 目录。此处给出接口骨架。
    """

    def __init__(self, id="video-h3", name="MiniMax H3 (ComfyUI)", base_url="http://127.0.0.1:8188",
                 api_key="", models=None, meta=None):
        super().__init__(id=id, name=name, base_url=base_url, api_key=api_key,
                         models=models or ["h3-ref2v"], meta=meta)

    def health(self):
        return {"ok": bool(self.base_url), "detail": self.base_url or "未配置 ComfyUI 地址"}

    def generate(self, prompt, reference=None, seconds=5.0, resolution="720p",
                 aspect="16:9", lock=None, seed=None):
        raise RuntimeError(
            "H3 Adapter 未接通：请启动本地 ComfyUI 并加载 H3 Ref2V 工作流，"
            "然后在「设置 → Provider」中启用并填写地址。"
        )


# ---------------------------------------------------------------- TTS
class OfflineTTSProvider(TTSProvider):
    """零依赖 TTS：用标准库 wave 合成真实 WAV（音高随角色 Voice ID 变化）。"""

    def __init__(self, id="tts-offline", name="内置离线语音合成"):
        super().__init__(id=id, name=name, models=["offline-tone"])

    def cost(self):
        return {"unit": "free", "price": 0.0}

    VOICE_BASE = {
        "default": 196.0, "narrator": 165.0, "male_deep": 130.0, "male_young": 220.0,
        "female_soft": 320.0, "female_bright": 392.0, "child": 440.0,
    }

    def speak(self, text, voice="default", rate="+0%"):
        base = self.VOICE_BASE.get(voice, 196.0)
        try:
            pct = int(str(rate).replace("%", "").replace("+", "")) if rate else 0
        except Exception:
            pct = 0
        base *= (1 + pct / 100.0)

        chars = max(1, len(text or ""))
        duration = max(0.6, chars * 0.16)          # 约 6 字/秒
        sr = 22050
        frames = bytearray()
        n = int(sr * duration)
        for i in range(n):
            t = i / sr
            # 简单音节包络，听起来像有节奏的语音占位
            syl = math.sin(2 * math.pi * 3.2 * t) > -0.2
            env = (0.5 + 0.5 * math.sin(2 * math.pi * 3.2 * t)) if syl else 0.0
            val = math.sin(2 * math.pi * base * t) * 0.32 * env
            val += math.sin(2 * math.pi * base * 2 * t) * 0.08 * env
            frames += struct.pack("<h", int(max(-1, min(1, val)) * 32767))
        return {"wav_bytes": bytes(frames), "sample_rate": sr, "duration": round(duration, 2)}


class CloudTTSProvider(TTSProvider):
    """云端 TTS 接口骨架（MiniMax / Edge TTS / 自建）。"""

    def __init__(self, id, name, base_url, api_key="", models=None, meta=None):
        super().__init__(id=id, name=name, base_url=base_url, api_key=api_key,
                         models=models or [], meta=meta)

    def speak(self, text, voice="default", rate="+0%"):
        raise RuntimeError("云端 TTS 未接通：请在「设置 → Provider」中配置地址与 Key。")


def save_wav(path: Path, wav_bytes: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(wav_bytes)
