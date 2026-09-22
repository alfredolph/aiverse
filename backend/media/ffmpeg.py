"""媒体引擎：FFmpeg 适配 + 字幕 + 导出计划（文档 §29 / §30）。

**FFmpeg 从 v1.0.6 起随程序自带**，不再依赖「一键部署」。
理由：它是导出成片的唯一硬依赖，跟有没有显卡毫无关系 ——
让用户为了烧个字幕去等 43 GB 的 H3 权重下载，完全说不通。

查找顺序（见 `_bin_dirs`）：
  1. runtime/ffmpeg/bin      —— 一键部署装的（用户显式装过就以它为准，方便手动升级）
  2. <exe 同级>/ffmpeg/bin   —— 安装版 / 绿色版随包发的
  3. <打包内>/ffmpeg/bin     —— PyInstaller 打进 exe 的那份
  4. 系统 PATH

一份都找不到时也不会报错：仍会生成完整的导出计划（concat 清单 / 字幕 /
导出描述），并在 UI 中提示「安装 FFmpeg 后即可一键渲染出片」。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..core import store
from ..core.config import CONTAINERS, RESOLUTIONS

_CODEC = {"MP4": "libx264", "H264": "libx264", "H265": "libx265", "AV1": "libsvtav1"}
_PRESET = {"480p": "854x480", "720p": "1280x720", "1080p": "1920x1080", "2K": "2560x1440", "4K": "3840x2160"}


def _bin_dirs() -> list[Path]:
    """ffmpeg / ffprobe 的查找目录，按优先级排列（去重后返回）。

    以「目录」为单位、而不是「先找到 ffmpeg 再看它旁边有没有 ffprobe」：
    早先 ffprobe 只在 `ffmpeg_path()` 的同级目录里找，于是 ffmpeg 一旦
    命中自带那份、而 ffprobe 只装在 runtime 里，ffprobe 就永远找不到。
    """
    from ..core.config import BASE_DIR, BUNDLE_DIR, RUNTIME_DIR
    out, seen = [], set()
    for d in (RUNTIME_DIR / "ffmpeg" / "bin",
              BASE_DIR / "ffmpeg" / "bin",
              BUNDLE_DIR / "ffmpeg" / "bin"):
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _find(name: str) -> Path | None:
    for d in _bin_dirs():
        try:
            p = d / name
            if p.exists():
                return p
        except OSError:
            continue
    exe = shutil.which(name[:-4] if name.lower().endswith(".exe") else name)
    return Path(exe) if exe else None


def ffmpeg_path() -> Path | None:
    """找 ffmpeg：优先一键部署装到 runtime/ 的那份，其次随程序自带的那份。"""
    return _find("ffmpeg.exe")


def ffprobe_path() -> Path | None:
    return _find("ffprobe.exe")


_DETECT_CACHE: tuple[float, dict[str, Any]] | None = None
_DETECT_LOCK = threading.Lock()


def detect(fresh: bool = False) -> dict[str, Any]:
    """探测 ffmpeg 是否可用。

    `/api/meta` 与 `/api/runtime/plan` 都会调它，而「可用」时每次探测都要起一个
    子进程跑 `ffmpeg -version`，所以结果缓存 30 秒。

    **只缓存「可用」的结果，不缓存「不可用」**（别改回去）：
    一键部署 4 秒就能把 FFmpeg 装好，而 `planner.build_plan()` 在部署开始前
    刚调过一次 `detect()`（那时确实还没有）。要是把「不可用」也缓存 30 秒，
    装完之后界面会继续显示「FFmpeg 未安装」，导出也就一直失败 ——
    CI 里 `tools/test_export.py` 就是这么红的。
    「不可用」时根本没起子进程，只是几个 `Path.exists()`，不缓存也没有代价。
    """
    global _DETECT_CACHE
    with _DETECT_LOCK:
        hit = _DETECT_CACHE
    if not fresh and hit and time.time() - hit[0] < 30.0:
        # 缓存命中也要确认那份文件还在 —— 用户可能刚卸载 / 删掉了
        p0 = hit[1].get("path")
        if p0 and Path(p0).exists():
            return dict(hit[1])

    p = ffmpeg_path()
    if not p:
        res = {"available": False, "path": None, "version": None, "bundled": False,
               "hint": "未检测到 FFmpeg。正式安装包里会自带一份；"
                       "从源码运行时可在「环境部署」里单独安装。"}
    else:
        bundled = "runtime" not in str(p).lower()
        try:
            out = subprocess.run([str(p), "-version"], capture_output=True, text=True,
                                 timeout=8,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            first = (out.stdout or "").splitlines()[0] if out.stdout else ""
            res = {"available": True, "path": str(p), "version": first, "bundled": bundled,
                   "hint": "FFmpeg 可用（随程序自带）" if bundled else "FFmpeg 可用"}
        except Exception as e:
            res = {"available": False, "path": str(p), "version": None, "bundled": bundled,
                   "hint": f"FFmpeg 探测失败：{e}"}

    with _DETECT_LOCK:
        _DETECT_CACHE = (time.time(), res) if res["available"] else None
    return dict(res)


def _aspect_size(aspect: str, resolution: str) -> str:
    """按「短边 = 预设里那个数字」算输出尺寸。

    1080p 的预设是 1920x1080，短边 1080：
        横屏 16:9 → 1920x1080（与预设一致）
        竖屏 9:16 → 1080x1920（抖音/快手竖屏标准）
    之前竖屏是按「高 = 1080」算的，9:16 会得到 606x1080 —— 既不是任何标准尺寸，
    又白白丢掉一半纵向分辨率。漫剧默认就是 9:16，所以这个坑会天天踩。
    """
    base = _PRESET.get(resolution, "1280x720")
    w, h = (int(x) for x in base.split("x"))
    aw, ah = (float(x) for x in aspect.split(":"))
    short = min(w, h)
    if aw >= ah:
        nh = short
        nw = int(round(nh * aw / ah / 2)) * 2
    else:
        nw = short
        nh = int(round(nw * ah / aw / 2)) * 2
    return f"{nw}x{nh}"


def build_export_plan(project: dict, shots: list[dict], options: dict) -> dict[str, Any]:
    container = options.get("container", "MP4")
    resolution = options.get("resolution", "1080p")
    aspect = options.get("aspect") or project.get("aspect") or "16:9"
    fps = int(options.get("fps") or 24)
    codec = _CODEC.get(container, "libx264")
    size = _aspect_size(aspect, resolution)
    pid = project["id"]
    name = store.safe_name(project.get("name") or "project")
    base = store.resolve(pid)

    # 收集真实渲染出来的视频文件（H3 / 云端 Provider 产物）
    clips: list[str] = []
    placeholders = 0
    for s in shots:
        v = (s.get("payload") or {}).get("video") or {}
        rel = v.get("video")
        if rel and (base / rel).exists():
            clips.append(rel)
        elif v:
            placeholders += 1

    concat_rel = f"exports/{name}.concat.txt"
    if clips:
        body = "\n".join(f"file '{base / c}'" for c in clips)
    else:
        body = "# 暂无已渲染镜头。接入本地 H3 或云端视频 Provider 后自动填充。"
    store.write_text(pid, concat_rel, body)

    srt_rel = "subtitles/subtitle.srt"
    has_srt = (base / srt_rel).exists()
    out_rel = f"exports/{name}.{container.lower()}"

    exe = ffmpeg_path() or Path("ffmpeg")
    cmd = [str(exe), "-y", "-f", "concat", "-safe", "0", "-i", str(base / concat_rel)]
    # 注意 pad 的参数是 `pad=宽:高:x:y`，**不是** `pad=宽x高:...` ——
    # 写成 `pad=606x1080:...` 会被当成「宽度 = 表达式 606x1080」，
    # ffmpeg 直接报 Invalid chars 'x1080' 然后整条导出失败。
    # scale 用 `宽x高` 才是对的，两个滤镜的写法不一样，很容易抄错。
    # force_divisible_by=2 是必须的：scale 按比例缩出来的中间尺寸可能是奇数，
    # 那样 pad 的 (ow-iw)/2 就不是整数，会再报一次错，而且 x264 也不接受奇数尺寸。
    ow, oh = (int(x) for x in size.split("x"))
    vf = (f"scale={ow}:{oh}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
          f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2")
    if has_srt:
        esc_srt = str(base / srt_rel).replace("\\", "/").replace(":", "\\:")
        vf += f",subtitles='{esc_srt}'"
    cmd += ["-vf", vf, "-r", str(fps), "-c:v", codec, "-pix_fmt", "yuv420p"]
    if container in ("MP4", "H264"):
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += [str(base / out_rel)]

    plan = {
        "container": container, "resolution": resolution, "aspect": aspect,
        "output_size": size, "fps": fps, "codec": codec,
        "shots": len(shots), "video_files": len(clips), "placeholders": placeholders,
        "concat": concat_rel, "output": out_rel, "subtitle": srt_rel if has_srt else None,
        "command": " ".join(f'"{c}"' if " " in c else c for c in cmd),
        "argv": cmd,
        "ffmpeg": detect(),
        "note": ("将拼接 %d 个已渲染镜头%s并输出 %s"
                 % (len(clips),
                    "、烧录字幕" if has_srt else "",
                    container)
                 if clips else
                 "当前镜头是占位产物，导出的是镜头清单。完成「环境部署」接入本地 H3 后即可产出真实 MP4。"),
    }
    store.write_json(pid, f"exports/{name}.export.json", plan)
    return plan


def run_export(project: dict, shots: list[dict], options: dict) -> dict[str, Any]:
    """真正执行导出。没有 ffmpeg 或没有已渲染镜头时，只返回计划。"""
    plan = build_export_plan(project, shots, options)
    if not plan["ffmpeg"]["available"]:
        plan["rendered"] = False
        plan["message"] = plan["ffmpeg"]["hint"]
        return plan
    if not plan["video_files"]:
        plan["rendered"] = False
        plan["message"] = plan["note"]
        return plan

    base = store.resolve(project["id"])
    (base / "exports").mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(plan["argv"], capture_output=True, text=True, timeout=3600,
                           encoding="utf-8", errors="ignore",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and (base / plan["output"]).exists():
            out = base / plan["output"]
            plan["rendered"] = True
            plan["output_bytes"] = out.stat().st_size
            plan["output_size_human"] = _human(out.stat().st_size)
            plan["message"] = f"导出完成：{plan['output']}"
        else:
            plan["rendered"] = False
            plan["message"] = f"导出失败（退出码 {r.returncode}）：{(r.stderr or '')[-400:]}"
    except Exception as e:
        plan["rendered"] = False
        plan["message"] = f"导出异常：{e}"
    return plan


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
