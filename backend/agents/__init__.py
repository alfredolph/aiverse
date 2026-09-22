"""Agent 层（文档 §45）。

Director / Script / Character / Scene / Storyboard / Video / Voice / Editor / Quality / Workflow
"""
from .base import Agent, AgentContext
from .script_agent import DirectorAgent, ScriptAgent
from .asset_agents import CharacterAgent, SceneAgent
from .storyboard_agent import StoryboardAgent
from .video_agent import VideoAgent
from .voice_agent import VoiceAgent
from .editor_agent import EditorAgent
from .quality_agent import QualityAgent

AGENTS = {
    "director": DirectorAgent,
    "script": ScriptAgent,
    "characters": CharacterAgent,
    "scenes": SceneAgent,
    "storyboard": StoryboardAgent,
    "video": VideoAgent,
    "voice": VoiceAgent,
    "edit": EditorAgent,
    "quality": QualityAgent,
}

__all__ = [
    "Agent", "AgentContext", "AGENTS",
    "DirectorAgent", "ScriptAgent", "CharacterAgent", "SceneAgent",
    "StoryboardAgent", "VideoAgent", "VoiceAgent", "EditorAgent", "QualityAgent",
]
