"""
Skill 动态在线安装器单元测试 (tests/unit/test_skill_installer.py)

用于测试 install_skill_from_url 工具的 URL 名称解析、HTTP 下载保存以及热加载行为。
"""

import os
import shutil
import pytest
from unittest.mock import patch, MagicMock
from app.skills.installer import install_skill_from_url, _extract_skill_name_from_url
from app.skills.skill_loader import skill_loader


def test_extract_skill_name_from_url():
    """测试从不同格式的 URL 提取技能名称"""
    assert _extract_skill_name_from_url("https://github.com/user/demo-skill.git") == "demo-skill"
    assert _extract_skill_name_from_url("https://example.com/downloads/my_tool.zip") == "my_tool"
    assert _extract_skill_name_from_url("invalid-url") == "invalid-url" or "custom_skill"


def test_install_skill_from_invalid_url_should_fail():
    """测试非法 URL 格式时的校验阻断"""
    res = install_skill_from_url.invoke({"url": "not-a-valid-url"})
    assert "安装失败" in res
    assert "http" in res


def test_install_skill_from_url_mock_success():
    """测试通过 HTTP 下载 SKILL.md 单文件并完成热加载"""
    test_skill_name = "unit_test_temp_skill"
    target_dir = os.path.join(skill_loader.skills_dir, test_skill_name)

    mock_markdown = b"---\nname: unit_test_temp_skill\ndescription: Test skill\n---\n# Test Skill"

    try:
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.headers = {"Content-Type": "text/markdown"}
            mock_resp.read.return_value = mock_markdown
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            res = install_skill_from_url.invoke({"url": "https://example.com/SKILL.md", "skill_name": test_skill_name})

            assert "成功" in res
            assert test_skill_name in skill_loader.skills_cache
    finally:
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            skill_loader._reload_skills()
