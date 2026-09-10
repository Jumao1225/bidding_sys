"""
Tool 动态自动发现注册模块 (registry.py)

本模块只负责发现可执行的 LangChain Tool。Skill 是由 SkillLoader 扫描的
SKILL.md 操作规范，两者不在这里混合解析或注册。
"""

import importlib
import json
import pkgutil
from typing import Any, Dict, List, Optional, Set
from loguru import logger
from langchain_core.tools import BaseTool, tool


def discover_tools(
    package_names: Optional[List[str]] = None,
    exclude_modules: Optional[Set[str]] = None
) -> List[BaseTool]:
    """
    动态扫描并发现指定 Python 包路径下的所有可执行 Tool。

    :param package_names: 需要扫描的包名列表，默认扫描 ["app.skills", "app.agents.tools"]
    :param exclude_modules: 需要排查的模块或子模块集合
    :return: 去重后的 LangChain BaseTool 列表
    """
    if package_names is None:
        package_names = ["app.skills", "app.agents.tools"]

    if exclude_modules is None:
        exclude_modules = {"security", "registry", "__init__"}

    discovered_tools: Dict[str, BaseTool] = {}

    for package_name in package_names:
        try:
            package = importlib.import_module(package_name)
        except Exception as e:
            logger.warning(f"⚠️ [Tool Discovery] 无法导入包 '{package_name}': {e}")
            continue

        package_path = getattr(package, "__path__", None)
        if not package_path:
            logger.warning(f"⚠️ [Tool Discovery] 包 '{package_name}' 缺少 __path__ 属性，跳过扫描。")
            continue

        # 使用 pkgutil 迭代子模块
        for _, modname, ispkg in pkgutil.iter_modules(package_path):
            if ispkg or modname in exclude_modules:
                continue

            full_mod_name = f"{package_name}.{modname}"
            try:
                module = importlib.import_module(full_mod_name)
            except Exception as exc:
                logger.error(f"❌ [Tool Discovery] 导入模块 '{full_mod_name}' 失败: {exc}")
                continue

            # 遍历模块属性查找 BaseTool 实例
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue

                attr_value = getattr(module, attr_name, None)
                if isinstance(attr_value, BaseTool):
                    tool_name = attr_value.name
                    if tool_name not in discovered_tools:
                        discovered_tools[tool_name] = attr_value
                        logger.info(f"✨ [Tool Discovery] 自动加载可执行 Tool: '{tool_name}' (来源: {full_mod_name})")

    tool_list = list(discovered_tools.values())
    logger.info(f"✅ [Tool Discovery] 自动发现完成，共装载 {len(tool_list)} 个可执行 Tool。")
    return tool_list


def get_tool_catalog_prompt(tools: List[BaseTool]) -> str:
    """生成只包含可执行 Tool 的目录摘要，明确排除 SKILL.md 内容。"""
    if not tools:
        return "【可用 Tool 目录（仅列可执行函数，不包含 Skill SOP）】: 当前暂无可用 Tool。"

    lines = ["【可用 Tool 目录（仅列可执行函数，不包含 Skill SOP）】:"]
    for current_tool in sorted(tools, key=lambda item: item.name):
        description = (current_tool.description or "暂无描述").splitlines()[0]
        try:
            argument_schema = json.dumps(current_tool.args, ensure_ascii=False)
        except (TypeError, ValueError):
            argument_schema = "{}"
        lines.append(
            f"- **{current_tool.name}**: {description}\n"
            f"  参数: `{argument_schema}`"
        )
    lines.append("提示：Tool 用于实际查询、写入、导出或调用外部能力；Skill SOP 请使用 `list_agent_skills` 和 `load_agent_skill`。")
    return "\n".join(lines)


@tool
def list_agent_tools() -> str:
    """
    [Tool 列表工具] 列出当前业务系统已注册的全部可执行 Tool。

    本工具只返回 Python Tool，不读取或列出 SKILL.md 的操作规范。
    """
    discovered_tools = discover_tools(package_names=["app.skills", "app.agents.tools"])
    # 注册器自身不参与扫描，单独补回本 Tool，确保目录完整反映可调用入口。
    discovered_tools.extend([list_agent_tools, execute_agent_tool])
    discovered_tools = list({current_tool.name: current_tool for current_tool in discovered_tools}.values())
    catalog = get_tool_catalog_prompt(discovered_tools)
    logger.info(f"📚 [Tool Discovery] 已刷新并返回 {len(discovered_tools)} 个可执行 Tool")
    return catalog


@tool
async def execute_agent_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """
    [按需执行 Tool] 只在 Tool 目录确认名称和参数后，动态发现并执行指定的非核心 Tool。

    核心 Tool 应直接调用；本入口用于避免非核心 Tool 在 ChatAgent 启动时全部注册。
    """
    if not tool_name:
        return "❌ 未提供要执行的 Tool 名称。请先调用 list_agent_tools。"

    discovered_tools = discover_tools(package_names=["app.skills", "app.agents.tools"])
    tool_map = {current_tool.name: current_tool for current_tool in discovered_tools}
    selected_tool = tool_map.get(tool_name)
    if selected_tool is None:
        return f"❌ 未找到可执行 Tool: {tool_name}。请先调用 list_agent_tools 刷新目录。"

    try:
        result = await selected_tool.ainvoke(arguments or {})
    except Exception as exc:
        logger.exception(f"❌ [Tool Discovery] 按需执行 Tool '{tool_name}' 失败: {exc}")
        return f"❌ 执行 Tool [{tool_name}] 失败: {exc}"

    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)
