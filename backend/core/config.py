"""全局配置与路径。

对应文档：§1 产品定位 / §33 文件结构
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- 应用信息
APP_NAME = "AI Studio"
APP_CODE = "AIVerse"
VERSION = "1.0.5"

# ---------------------------------------------------------------- 路径
# 支持三种运行方式：
#   1) 源码运行   ：aiverse/backend/core/config.py -> parents[2] == aiverse/
#   2) 绿色版 exe ：PyInstaller 单文件，资源解包到 sys._MEIPASS，
#                   用户数据与运行时写在 exe 同级（可随 U 盘带走）
#   3) 安装版 exe ：Inno Setup 会写入 aiverse.ini 作为标记，
#                   数据与运行时统一放到 %LOCALAPPDATA%\AIVerse（无需管理员权限，
#                   重装/升级不丢 30GB 模型）
FROZEN = bool(getattr(sys, "frozen", False))


def _writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _local_root() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local) / "AIVerse"


def _installed_mode() -> bool:
    """安装版标志：由 Inno Setup 在安装目录写入 aiverse.ini。

    安装版把「项目数据 + 30GB 推理运行时」放到 %LOCALAPPDATA%\\AIVerse，
    这样重装/升级不会丢模型，卸载也不会误删。
    绿色版（直接拷 exe）则全部放在 exe 同级，可随 U 盘带走。
    """
    try:
        return (BASE_DIR / "aiverse.ini").exists()
    except Exception:
        return False


def _default_data_dir() -> Path:
    if not FROZEN:
        return BASE_DIR / "projects"
    if _installed_mode():
        return _local_root() / "projects"
    beside = BASE_DIR / "projects"
    if _writable(beside):
        return beside
    return _local_root() / "projects"


if FROZEN:
    # exe 所在目录（用户可见）；打包内只读资源在 _MEIPASS
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", str(BASE_DIR)))
else:
    BASE_DIR = Path(__file__).resolve().parents[2]
    BUNDLE_DIR = BASE_DIR

FRONTEND_DIR = BUNDLE_DIR / "frontend"
DATA_DIR = Path(os.environ.get("AIVERSE_DATA") or _default_data_dir())
DB_PATH = DATA_DIR / "aiverse.db"
LOG_PATH = DATA_DIR / "aiverse.log"

# 本地推理运行时（Python/CUDA/ComfyUI/H3 权重），体积可达 30GB+。
# 绿色版：放在 exe 同级 runtime/，可整体迁移；
# 安装版：放在 %LOCALAPPDATA%\AIVerse\runtime，重装不丢模型。
# 可用环境变量 AIVERSE_RUNTIME 强制覆盖。
def _default_runtime_dir() -> Path:
    if not FROZEN:
        return DATA_DIR.parent / "runtime"
    if _installed_mode():
        return _local_root() / "runtime"
    return BASE_DIR / "runtime"


RUNTIME_DIR = Path(os.environ.get("AIVERSE_RUNTIME") or _default_runtime_dir())

# ---------------------------------------------------------------- 服务
HOST = os.environ.get("AIVERSE_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIVERSE_PORT", "8770"))

# ---------------------------------------------------------------- 项目目录结构（文档 §33）
PROJECT_SUBDIRS = [
    "script",
    "characters",
    "scenes",
    "props",
    "storyboards",
    "workflows",
    "images",
    "videos",
    "audio",
    "subtitles",
    "timeline",
    "exports",
    "cache",
]

# ---------------------------------------------------------------- 管线阶段（文档 §3 / §6）
# (key, 展示名, 说明)
STAGES = [
    ("script", "剧本分析", "AI 理解剧本，抽取人物 / 场景 / 道具 / 镜头需求"),
    ("characters", "角色设计", "建立 Character Bible，生成角色参考图候选"),
    ("scenes", "场景设计", "建立 Scene Bible 与 Props Bible，生成场景参考图"),
    ("storyboard", "分镜导演", "拆解分镜表：景别 / 时长 / 动作 / 运镜 / 情绪"),
    ("video", "视频生成", "按分镜调用视频 Provider（H3 / 云端）生成镜头"),
    ("voice", "配音音效", "角色 TTS、旁白、环境音、BGM、音效"),
    ("edit", "自动剪辑", "AI 生成初版时间线，人工可改"),
    ("final", "成片", "渲染导出 MP4 / H264 / H265 / AV1"),
]

# ---------------------------------------------------------------- 审核状态机（文档 §48）
STATUS = {
    "DRAFT": "DRAFT",
    "GENERATING": "GENERATING",
    "REVIEW": "REVIEW",
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "REGENERATING": "REGENERATING",
    "FINAL": "FINAL",
}

STATUS_LABEL = {
    "DRAFT": "草稿",
    "GENERATING": "生成中",
    "REVIEW": "待审核",
    "APPROVED": "已通过",
    "REJECTED": "已驳回",
    "REGENERATING": "重新生成",
    "FINAL": "已完成",
}

# ---------------------------------------------------------------- 画幅 / 分辨率（文档 §30）
ASPECTS = ["9:16", "16:9", "3:4", "1:1"]
RESOLUTIONS = ["480p", "720p", "1080p", "2K", "4K"]
CONTAINERS = ["MP4", "H264", "H265", "AV1"]

# ---------------------------------------------------------------- 内置风格库（文档 §26）
STYLES = [
    {"key": "guoman", "name": "国漫", "positive": "chinese comic style, cel shading, clean lineart, vivid color",
     "negative": "photo, 3d render, blurry", "motion": "moderate", "lighting": "soft key"},
    {"key": "riman", "name": "日漫", "positive": "anime style, japanese animation, expressive eyes",
     "negative": "photo, realistic skin", "motion": "snappy", "lighting": "flat"},
    {"key": "american", "name": "美漫", "positive": "american comic, bold ink, halftone shading",
     "negative": "soft anime, pastel", "motion": "dynamic", "lighting": "hard"},
    {"key": "korean", "name": "韩漫", "positive": "korean webtoon, vertical comic, glossy render",
     "negative": "rough sketch", "motion": "gentle", "lighting": "rim"},
    {"key": "cyberpunk", "name": "赛博朋克", "positive": "cyberpunk, neon, rain, volumetric fog",
     "negative": "daylight, rustic", "motion": "slow push-in", "lighting": "neon"},
    {"key": "realistic", "name": "写实电影", "positive": "cinematic photography, 35mm, shallow depth of field",
     "negative": "cartoon, anime", "motion": "steady", "lighting": "natural"},
    {"key": "cgi3d", "name": "3D 动画", "positive": "stylized 3d animation, subsurface scattering",
     "negative": "2d flat", "motion": "smooth", "lighting": "studio"},
    {"key": "pixar", "name": "Pixar-like 3D", "positive": "pixar style 3d, rounded shapes, warm palette",
     "negative": "gritty, dark", "motion": "bouncy", "lighting": "warm"},
    {"key": "ghibli", "name": "吉卜力式手绘", "positive": "ghibli style, hand painted background, watercolor sky",
     "negative": "3d, neon", "motion": "gentle", "lighting": "golden hour"},
    {"key": "ink", "name": "水墨国风", "positive": "chinese ink wash painting, xuan paper texture",
     "negative": "saturated, neon", "motion": "slow", "lighting": "diffuse"},
    {"key": "hk", "name": "港漫", "positive": "hong kong manhua, muscular lineart, dramatic speed lines",
     "negative": "cute chibi", "motion": "impactful", "lighting": "contrast"},
    {"key": "western", "name": "欧美奇幻", "positive": "western fantasy illustration, epic scale",
     "negative": "modern city", "motion": "epic", "lighting": "dramatic"},
    {"key": "gothic", "name": "黑暗哥特", "positive": "dark gothic, muted palette, ornate detail",
     "negative": "bright cheerful", "motion": "slow", "lighting": "low key"},
    {"key": "chibi", "name": "Q版", "positive": "chibi, super deformed, big head small body",
     "negative": "realistic proportion", "motion": "bouncy", "lighting": "flat"},
    {"key": "motioncomic", "name": "动态漫画", "positive": "motion comic, layered parallax, comic panel",
     "negative": "full animation", "motion": "parallax", "lighting": "comic"},
    {"key": "gamecg", "name": "游戏 CG", "positive": "game cinematic cg, unreal engine render",
     "negative": "hand drawn", "motion": "smooth", "lighting": "cinematic"},
]
