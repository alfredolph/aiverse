"""Provider 抽象层。

对应文档：
  §8  多模型架构 —— 客户端绝不把 H3 写死
  §42 Provider 系统 —— Name / Type / API / Models / Cost / Capabilities / Limits

设计原则：任何新模型都通过 Provider + Adapter 接入，业务层只依赖抽象。
"""
from __future__ import annotations

import abc
from typing import Any


class Provider(abc.ABC):
    """所有 Provider 的基类。"""

    type: str = "base"

    def __init__(self, id: str, name: str, base_url: str = "", api_key: str = "",
                 models: list[str] | None = None, enabled: bool = True, meta: dict | None = None):
        self.id = id
        self.name = name
        self.base_url = base_url or ""
        self.api_key = api_key or ""
        self.models = models or []
        self.enabled = enabled
        self.meta = meta or {}

    # -- 文档 §42 的六个维度 -----------------------------------------
    def capabilities(self) -> list[str]:
        return []

    def limits(self) -> dict[str, Any]:
        return {}

    def cost(self) -> dict[str, Any]:
        return {"unit": "free", "price": 0.0}

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "models": self.models,
            "enabled": self.enabled,
            "capabilities": self.capabilities(),
            "limits": self.limits(),
            "cost": self.cost(),
            "has_key": bool(self.api_key),
        }

    def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "ok"}


class LLMProvider(Provider, abc.ABC):
    """大语言模型 Provider（文档 §9：WorkBuddy 只是其中一个 Provider）。"""

    type = "llm"

    @abc.abstractmethod
    def complete(self, prompt: str, system: str = "", json_mode: bool = False,
                 max_tokens: int = 2048) -> str:
        """返回模型文本。json_mode 为 True 时要求返回合法 JSON。"""

    def capabilities(self) -> list[str]:
        return ["text", "json"]


class ImageProvider(Provider, abc.ABC):
    type = "image"

    @abc.abstractmethod
    def generate(self, prompt: str, negative: str = "", size: str = "768x1024",
                 reference: str | None = None, seed: int | None = None) -> dict[str, Any]:
        """返回 {'path': 相对路径, 'seed': int, 'meta': {...}}"""

    def capabilities(self) -> list[str]:
        return ["text2image", "ref2image"]


class VideoProvider(Provider, abc.ABC):
    type = "video"

    @abc.abstractmethod
    def generate(self, prompt: str, reference: str | None = None, seconds: float = 5.0,
                 resolution: str = "720p", aspect: str = "16:9",
                 lock: list[str] | None = None, seed: int | None = None) -> dict[str, Any]:
        """返回 {'path': 相对路径, 'seed': int, 'meta': {...}}"""

    def capabilities(self) -> list[str]:
        return ["image2video", "text2video"]


class TTSProvider(Provider, abc.ABC):
    type = "tts"

    @abc.abstractmethod
    def speak(self, text: str, voice: str = "default", rate: str = "+0%") -> dict[str, Any]:
        """返回 {'path': 相对路径, 'duration': 秒}"""

    def capabilities(self) -> list[str]:
        return ["tts"]
