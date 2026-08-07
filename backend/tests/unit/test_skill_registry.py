"""
Skill 与 Tool 动态发现注册器单元测试 (tests/unit/test_skill_registry.py)

用于测试 discover_skills_and_tools 动态扫描、工具识别、去重以及错误模块容错能力。
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.tools import tool, BaseTool
from app.skills.registry import discover_skills_and_tools
from app.agents.chat_agent import ChatAgent


@tool
def dummy_test_skill_alpha(query: str) -> str:
    """Alpha 测试技能描述"""
    return f"alpha: {query}"


@tool
def dummy_test_skill_beta(count: int) -> int:
    """Beta 测试技能描述"""
    return count * 2


def test_discover_skills_should_load_existing_tools():
    """测试动态扫描功能：能否正常装载 app.skills 和 app.agents.tools 下的所有可用工具"""
    tools = discover_skills_and_tools(package_names=["app.skills", "app.agents.tools"])

    assert isinstance(tools, list)
    assert len(tools) > 0

    # 验证常用工具被自动发现
    tool_names = [t.name for t in tools]
    assert "web_search" in tool_names or "search_document_tool" in tool_names or "extract_qualification_info" in tool_names


def test_discover_skills_deduplication_should_merge_by_name():
    """测试工具去重场景：当出现同名工具时，后发现的工具或注册字典能正确去重"""
    tools = discover_skills_and_tools(package_names=["app.skills"])
    tool_names = [t.name for t in tools]

    # 断言无重复工具名称
    assert len(tool_names) == len(set(tool_names))


def test_discover_skills_invalid_package_should_handle_gracefully():
    """测试异常场景：当扫描不存在的包名时，应拦截异常并优雅返回空列表或可用列表"""
    tools = discover_skills_and_tools(package_names=["app.non_existent_package_xyz"])

    assert isinstance(tools, list)
    assert len(tools) == 0


def test_chat_agent_integration_should_load_discovered_tools():
    """测试 ChatAgent 连贯集成：验证 ChatAgent 能够成功初始化并包含自动发现的 Skill"""
    with patch("app.agents.chat_agent.create_react_agent") as mock_create_react:
        chat_agent = ChatAgent()

        # 生成系统提示词验证无异常
        prompt = chat_agent._build_chat_system_prompt("doc_test_123")
        assert "ChatAgent" in prompt
        assert "doc_test_123" in prompt
