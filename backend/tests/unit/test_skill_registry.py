"""
Tool 动态发现注册器单元测试 (tests/unit/test_skill_registry.py)

用于测试 discover_tools 动态扫描、工具识别、去重以及错误模块容错能力。
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.tools import tool, BaseTool
from app.skills.registry import (
    discover_tools,
    execute_agent_tool,
    get_tool_catalog_prompt,
    list_agent_tools,
)
from app.agents.chat_agent import ChatAgent


@tool
def dummy_test_skill_alpha(query: str) -> str:
    """Alpha 测试技能描述"""
    return f"alpha: {query}"


@tool
def dummy_test_skill_beta(count: int) -> int:
    """Beta 测试技能描述"""
    return count * 2


def test_discover_tools_should_load_existing_tools():
    """测试动态扫描功能：能否正常装载业务包下的可执行 Tool。"""
    tools = discover_tools(package_names=["app.skills", "app.agents.tools"])

    assert isinstance(tools, list)
    assert len(tools) > 0

    # 验证常用工具被自动发现
    tool_names = [t.name for t in tools]
    assert "web_search" in tool_names or "search_document_tool" in tool_names or "extract_qualification_info" in tool_names
    assert "list_agent_skills" in tool_names


def test_discover_tools_deduplication_should_merge_by_name():
    """测试 Tool 去重场景：同名 Tool 只保留一个注册项。"""
    tools = discover_tools(package_names=["app.skills"])
    tool_names = [t.name for t in tools]

    # 断言无重复工具名称
    assert len(tool_names) == len(set(tool_names))


def test_discover_tools_invalid_package_should_handle_gracefully():
    """测试异常场景：扫描不存在的包名时应优雅返回空列表。"""
    tools = discover_tools(package_names=["app.non_existent_package_xyz"])

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
        assert "officecli" in prompt
        assert "list_agent_skills" in prompt
        assert "【Tool 渐进式披露规则】" in prompt
        assert "list_agent_tools" in prompt
        assert "Skill 只提供操作规范" in prompt
        assert "完整目录不在系统提示词中重复展开" in prompt


def test_tool_catalog_should_not_be_skill_catalog():
    """测试 Tool 目录明确声明不包含 Skill SOP。"""
    tools = discover_tools(package_names=["app.skills"])
    catalog = get_tool_catalog_prompt(tools)

    assert "仅列可执行函数，不包含 Skill SOP" in catalog
    assert "web_search" in catalog


def test_list_agent_tools_should_return_executable_tool_catalog():
    """测试 Tool 列表 Tool 返回可执行 Tool 目录。"""
    catalog = list_agent_tools.invoke({})

    assert "可用 Tool 目录" in catalog
    assert "web_search" in catalog


@pytest.mark.asyncio
async def test_execute_agent_tool_should_load_non_core_tool_on_demand():
    """测试非核心 Tool 仅在执行请求发生时才被发现并调用。"""
    result = await execute_agent_tool.ainvoke(
        {"tool_name": "web_search", "arguments": {"query": "渐进式披露"}}
    )

    assert "模拟搜索结果" in result
