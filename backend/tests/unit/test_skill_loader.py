"""
SkillLoader 单元测试 (tests/unit/test_skill_loader.py)

用于测试官方 SKILL.md 文件的扫描、YAML Frontmatter 解析与 load_agent_skill 工具的可靠性。
"""

import pytest
from app.skills.skill_loader import SkillLoader, load_agent_skill


def test_skill_loader_scan_should_target_app_skills():
    """测试 SkillLoader 准确锁定业务系统专属目录 app/skills/ (与 IDE 的 .agents/ 隔离)"""
    loader = SkillLoader()
    skills = loader.skills_cache

    assert isinstance(skills, dict)
    assert loader.skills_dir.endswith("skills")


def test_skill_loader_catalog_prompt_format():
    """测试生成的 Prompt 目录描述格式"""
    loader = SkillLoader()
    catalog_prompt = loader.get_skill_catalog_prompt()

    assert "【可用官方技能 (Skill Catalog)】" in catalog_prompt or "【可用官方技能】" in catalog_prompt


def test_load_official_officecli_skill_from_folder():
    """测试 SkillLoader 自动扫描并装载用户放在 app/skills/officecli/ 下的官方 SKILL.md"""
    loader = SkillLoader()
    skills = loader.skills_cache

    assert "officecli" in skills
    assert "Office document" in skills["officecli"]["description"]

    # 验证调取 SOP 指南
    res = load_agent_skill.invoke({"skill_name": "officecli"})
    assert isinstance(res, str)
    assert "OfficeCLI" in res
    assert "When To Use This Skill" in res


def test_load_agent_skill_tool_invoke():
    """测试 load_agent_skill 工具调用"""
    res = load_agent_skill.invoke({"skill_name": "non_existent_skill"})
    assert isinstance(res, str)
    assert "未找到名为" in res
