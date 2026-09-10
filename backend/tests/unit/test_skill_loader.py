"""
SkillLoader 单元测试 (tests/unit/test_skill_loader.py)

用于测试 SKILL.md 文件的扫描、YAML Frontmatter 解析与 Skill 管理 Tool 的可靠性。
"""

import os
from unittest.mock import mock_open, patch

import pytest
from app.skills.skill_loader import (
    SkillLoader,
    load_agent_skill,
    load_agent_skill_resource,
    list_agent_skills,
    skill_loader,
)


def test_skill_loader_scan_should_target_app_skills():
    """测试 SkillLoader 准确锁定业务系统专属目录 app/skills/ (与 IDE 的 .agents/ 隔离)"""
    loader = SkillLoader()
    skills = loader.skills_cache

    assert isinstance(skills, dict)
    assert skills == {}
    assert loader.skills_dir.endswith("skills")


def test_skill_loader_should_load_only_metadata_until_sop_is_requested():
    """测试初始化和目录扫描阶段不读取完整 SOP，调用具体 Skill 时才读取正文。"""
    loader = SkillLoader()
    assert loader.skills_cache == {}

    loader.reload_skills()
    assert loader.skills_cache["officecli"]["description"]
    assert "instruction" not in loader.skills_cache["officecli"]

    instruction = loader.get_skill_instruction("officecli")
    assert "OfficeCLI" in instruction
    assert loader.skills_cache["officecli"]["instruction"]


def test_skill_loader_catalog_prompt_format():
    """测试生成的 Prompt 目录描述格式"""
    loader = SkillLoader()
    catalog_prompt = loader.get_skill_catalog_prompt()

    assert "【可用 Skill 目录（第一层：仅元数据，不包含完整 SOP 或 Tool）】" in catalog_prompt


def test_list_agent_skills_should_refresh_new_skill_directory():
    """测试运行期间新增的 SKILL.md 文件夹能够被列表工具及时发现"""
    original_skills_dir = skill_loader.skills_dir
    temporary_skills_dir = "virtual_skills"
    temporary_skill_file = os.path.join(temporary_skills_dir, "temporary_skill", "SKILL.md")
    temporary_skill_content = (
        "---\nname: temporary_skill\ndescription: 临时测试技能\n---\n# 临时测试技能\n"
    )

    try:
        skill_loader.skills_dir = temporary_skills_dir
        real_path_exists = os.path.exists
        with patch(
            "app.skills.skill_loader.os.walk",
            return_value=[(os.path.dirname(temporary_skill_file), [], ["SKILL.md"])],
        ), patch(
            "app.skills.skill_loader.os.path.exists",
            side_effect=lambda path: path == temporary_skills_dir or real_path_exists(path),
        ), patch("builtins.open", mock_open(read_data=temporary_skill_content)):
            catalog = list_agent_skills.invoke({})

        assert "temporary_skill" in catalog
        assert "临时测试技能" in catalog
    finally:
        skill_loader.skills_dir = original_skills_dir
        skill_loader.reload_skills()


def test_load_official_officecli_skill_from_folder():
    """测试 SkillLoader 自动扫描并装载用户放在 app/skills/officecli/ 下的官方 SKILL.md"""
    loader = SkillLoader()
    loader.reload_skills()
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


def test_load_agent_skill_resource_should_load_referenced_text_on_demand():
    """测试第三层按需读取 Skill 引用的文本资源。"""
    res = load_agent_skill_resource.invoke(
        {"skill_name": "officecli", "resource_path": "references/demos.md"}
    )

    assert "第三层" in res
    assert "OfficeCLI demo gallery" in res


def test_load_agent_skill_resource_should_reject_path_traversal():
    """测试 Skill 资源读取不能越界访问 Skill 目录之外的文件。"""
    res = load_agent_skill_resource.invoke(
        {"skill_name": "officecli", "resource_path": "../SKILL.md"}
    )

    assert "超出 Skill 目录范围" in res


def test_list_agent_skills_should_only_return_skill_catalog():
    """测试 Skill 列表 Tool 不把可执行 Tool 混入 Skill 目录。"""
    catalog = list_agent_skills.invoke({})

    assert "第一层：仅元数据，不包含完整 SOP 或 Tool" in catalog
    assert "officecli" in catalog
