from .registry import default_registry, SkillRegistry
from .base import BaseSkill
from .web_search import WebSearchSkill

# 自动注册系统自带的核心技能
default_registry.register(WebSearchSkill())

__all__ = ["default_registry", "SkillRegistry", "BaseSkill"]
