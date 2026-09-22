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
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
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


_PORT_CACHE: dict[str, tuple[float, bool]] = {}


def _port_open(url: str, timeout: float = 0.2, ttl: float = 3.0) -> bool:
    """探测端口通不通（用于判断 ComfyUI 是否在跑）。

    两个坑：
      1. 有些 Windows 安全软件会让「连不上」的本地端口静默丢包，
         而不是立刻返回 RST —— 所以超时必须给得很小（0.2s），
         否则每个镜头都要白等一两秒。
      2. 结果缓存 3 秒：一次生成要查几十次，别每次都真的去连。
    """
    now = time.time()
    hit = _PORT_CACHE.get(url)
    if hit and now - hit[0] < ttl:
        return hit[1]

    ok = False
    try:
        u = urllib.parse.urlparse(url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 8188
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            ok = s.connect_ex((host, port)) == 0
    except Exception:
        ok = False

    _PORT_CACHE[url] = (time.time(), ok)
    return ok


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
    """MiniMax H3（经本地 ComfyUI）Adapter —— 文档 §36 / §37 的执行引擎接口。

    真实工作流：
        1. 连本地 ComfyUI，读 /object_info 自动识别 H3 节点类名
        2. 用 h3_workflows.build_graph() 生成 API 格式工作流
        3. POST /prompt 提交，轮询 /history/{id} 等结果
        4. 从 /view 拉回生成的 MP4（H3 同时产出音频轨）
    未接通时抛错，由上层自动回退到占位 Provider，不会中断流程。
    """

    def __init__(self, id="video-h3", name="MiniMax H3 (ComfyUI)", base_url="http://127.0.0.1:8188",
                 api_key="", models=None, meta=None):
        super().__init__(id=id, name=name, base_url=base_url, api_key=api_key,
                         models=models or ["h3-fl2va", "h3-ref2va"], meta=meta)

    def capabilities(self):
        return ["text2video", "image2video", "ref2video", "native_audio"]

    def cost(self):
        return {"unit": "local_gpu", "price": 0.0}

    def limits(self):
        return {"native_resolution": "768p", "max_reference_images": 9,
                "max_reference_videos": 3, "max_reference_audios": 3}

    # ------------------------------------------------------------ 连接
    def _api(self, path: str, data: dict | None = None, timeout: int = 30):
        url = self.base_url.rstrip("/") + path
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"} if body else {},
            method="POST" if body else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def health(self):
        if not self.base_url:
            return {"ok": False, "detail": "缺少 ComfyUI 地址"}
        # 先用极短的 TCP 探测挡一道：ComfyUI 没开时直接返回，
        # 避免每个镜头都白等一次 HTTP 超时。
        if not _port_open(self.base_url):
            return {"ok": False, "connected": False,
                    "detail": f"ComfyUI 未在运行（{self.base_url}）—— "
                              f"点「启动 ComfyUI」，或直接开始生成（会自动拉起）"}
        try:
            stats = self._api("/system_stats", timeout=4)
            obj = self._api("/object_info", timeout=25)
            from .h3_workflows import h3_available
            info = h3_available(obj)
            if not info["available"]:
                return {"ok": False, "connected": True,
                        "detail": "ComfyUI 已连接，但未检测到 H3 节点。请先安装 MiniMax H3 节点包",
                        "comfyui": stats.get("system", {})}
            return {"ok": True, "connected": True, "detail": "H3 节点就绪",
                    "acceleration": info["acceleration"],
                    "related_nodes": info["related_nodes"]}
        except Exception as e:
            return {"ok": False, "connected": True,
                    "detail": f"无法连接 ComfyUI（{self.base_url}）：{e}"}

    def node_map(self) -> dict:
        """实时读取 ComfyUI 节点清单并自动映射；失败则用默认映射。"""
        from .h3_workflows import DEFAULT_NODE_MAP, autodetect_node_map
        try:
            obj = self._api("/object_info", timeout=25)
            detected = autodetect_node_map(obj, self.meta.get("node_map") or DEFAULT_NODE_MAP)
            self.meta["node_map"] = detected
            self.meta["object_info_count"] = len(obj)
            return detected
        except Exception:
            return dict(self.meta.get("node_map") or DEFAULT_NODE_MAP)

    # ------------------------------------------------------------ 自动拉起
    def ensure_ready(self, wait_seconds: int = 120) -> bool:
        """ComfyUI 没在跑就自动拉起（用部署器装的那一份）。

        这样用户不需要先手动开 ComfyUI 再回来点生成 —— 少一步是一步。
        """
        if self.health().get("ok"):
            return True
        if not self._spawn_comfy():
            return False
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            time.sleep(3)
            if self.health().get("ok"):
                return True
        return False

    def _spawn_comfy(self) -> bool:
        try:
            from ..core.config import RUNTIME_DIR
        except Exception:
            return False
        main_py = RUNTIME_DIR / "comfyui" / "main.py"
        venv_py = RUNTIME_DIR / "venv" / "Scripts" / "python.exe"
        if not main_py.exists() or not venv_py.exists():
            return False
        # 已经在跑就别重复拉
        if _port_open(self.base_url):
            return True
        try:
            subprocess.Popen(
                [str(venv_py), str(main_py), "--listen", "127.0.0.1", "--port", "8188"],
                cwd=str(RUNTIME_DIR / "comfyui"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 生成
    def generate(self, prompt, reference=None, seconds=5.0, resolution="720p",
                 aspect="16:9", lock=None, seed=None, **_extra):
        if not self.base_url:
            raise RuntimeError("H3 Adapter 未配置 ComfyUI 地址")

        from .h3_workflows import build_graph

        # 1) 健康检查（ComfyUI 没开就先自动拉起）+ 节点映射
        if not self.ensure_ready():
            h = self.health()
            raise RuntimeError(h.get("detail") or "H3 未就绪：ComfyUI 未运行且无法自动启动")
        nm = self.node_map()

        # 2) 尺寸：H3-Base 原生 768p 级，按画幅换算
        w, hh = _h3_size(aspect, resolution)
        fps = int(self.meta.get("fps") or 24)
        frames = max(25, int(round(seconds * fps / 4)) * 4 + 1)   # 视频模型常见的 4n+1

        params = {
            "prompt": prompt,
            "negative": (self.meta.get("negative")
                         or "blurry, low quality, deformed, watermark, text"),
            "width": w, "height": hh, "frames": frames, "fps": fps,
            "steps": int(self.meta.get("steps") or 50),
            "cfg": float(self.meta.get("cfg") or 6.0),
            "seed": int(seed if seed is not None else _seed_of(prompt) % 2 ** 31),
            "precision": self.meta.get("precision") or "quantized",
            "offload": bool(self.meta.get("offload", True)),
            "model_name": self.meta.get("model_name") or "MiniMax-H3",
            "filename_prefix": "aiverse/h3",
        }
        kind = "ref2va" if reference else "fl2va"
        if reference:
            params["reference"] = reference

        graph = build_graph(kind, params, nm)

        # 3) 提交
        try:
            resp = self._api("/prompt", {"prompt": graph, "client_id": "aiverse"})
        except Exception as e:
            raise RuntimeError(f"提交 ComfyUI 任务失败：{e}")
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id：{str(resp)[:300]}")

        # 4) 轮询
        deadline = time.time() + int(self.meta.get("timeout_seconds") or 3600)
        while time.time() < deadline:
            time.sleep(2.5)
            try:
                hist = self._api(f"/history/{prompt_id}", timeout=20)
            except Exception:
                continue
            entry = hist.get(prompt_id)
            if not entry:
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError(f"H3 执行报错：{str(msgs)[:400]}")
            outputs = entry.get("outputs") or {}
            files = _collect_video_outputs(outputs)
            if files:
                # 5) 取回文件
                local = self._download(files[0], prompt_id)
                return {
                    "path": str(local), "video_path": str(local),
                    "seed": params["seed"],
                    "manifest": {
                        "prompt": prompt, "reference": reference, "seconds": seconds,
                        "resolution": f"{w}x{hh}", "aspect": aspect, "frames": frames,
                        "fps": fps, "steps": params["steps"], "seed": params["seed"],
                        "provider": self.name, "backend": "comfyui",
                        "prompt_id": prompt_id, "variant": kind,
                        "node_map": nm,
                        "status": "rendered",
                        "note": "由本地 ComfyUI + MiniMax H3 生成（原生 768p，含音频轨）",
                    },
                }
        raise RuntimeError("H3 生成超时")

    def _download(self, item: dict, prompt_id: str) -> Path:
        q = urllib.parse.urlencode({
            "filename": item.get("filename", ""),
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        url = self.base_url.rstrip("/") + "/view?" + q
        tmp = Path(tempfile.gettempdir()) / "aiverse_h3"
        tmp.mkdir(parents=True, exist_ok=True)
        dest = tmp / f"{prompt_id}_{item.get('filename', 'output.mp4')}"
        with urllib.request.urlopen(url, timeout=180) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return dest


def _h3_size(aspect: str, resolution: str) -> tuple[int, int]:
    """H3-Base 原生 768p 级；按画幅给出宽高，长边按分辨率档位缩放。"""
    long_edge = {"480p": 640, "720p": 832, "1080p": 1152, "2K": 1344, "4K": 1344}.get(resolution, 832)
    ratio = {"16:9": 16 / 9, "9:16": 9 / 16, "3:4": 3 / 4, "1:1": 1.0}.get(aspect, 16 / 9)
    if ratio >= 1:
        w = long_edge
        h = int(round(long_edge / ratio))
    else:
        h = long_edge
        w = int(round(long_edge * ratio))
    # 对齐到 32 的倍数，避免多数模型报错
    w = max(256, w // 32 * 32)
    h = max(256, h // 32 * 32)
    return w, h


def _collect_video_outputs(outputs: dict) -> list[dict]:
    """从 ComfyUI history 的 outputs 里挑出视频文件。"""
    exts = (".mp4", ".webm", ".mkv", ".mov", ".gif")
    found: list[dict] = []
    for _nid, out in (outputs or {}).items():
        for key in ("videos", "gifs", "images", "video"):
            for item in (out.get(key) or []):
                if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(exts):
                    found.append(item)
    # 优先 mp4
    found.sort(key=lambda x: 0 if str(x.get("filename", "")).lower().endswith(".mp4") else 1)
    return found


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
