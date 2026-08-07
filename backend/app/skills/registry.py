"""
Skill 与 Tool 动态自动发现注册模块 (registry.py)

功能：
1. 动态扫描指定包路径 (如 app.skills, app.agents.tools) 下的所有 Python 模块；
2. 自动识别并装载所有 LangChain BaseTool / @tool 实例；
3. 支持工具去重与强健的异常隔离，避免单个模块损坏导致 Agent 初始化失败。
"""

import importlib
import pkgutil
from typing import List, Dict, Optional, Set
from loguru import logger
from langchain_core.tools import BaseTool


def discover_skills_and_tools(
    package_names: Optional[List[str]] = None,
    exclude_modules: Optional[Set[str]] = None
) -> List[BaseTool]:
    """
    动态扫描并全自动发现指定 Python 包路径下的所有 Skill 与 Tool。

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
            logger.warning(f"⚠️ [Skill Discovery] 无法导入包 '{package_name}': {e}")
            continue

        package_path = getattr(package, "__path__", None)
        if not package_path:
            logger.warning(f"⚠️ [Skill Discovery] 包 '{package_name}' 缺少 __path__ 属性，跳过扫描。")
            continue

        # 使用 pkgutil 迭代子模块
        for _, modname, ispkg in pkgutil.iter_modules(package_path):
            if ispkg or modname in exclude_modules:
                continue

            full_mod_name = f"{package_name}.{modname}"
            try:
                module = importlib.import_module(full_mod_name)
            except Exception as exc:
                logger.error(f"❌ [Skill Discovery] 导入模块 '{full_mod_name}' 失败: {exc}")
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
                        logger.info(f"✨ [Skill Discovery] 自动加载技能/工具: '{tool_name}' (来源: {full_mod_name})")

    tool_list = list(discovered_tools.values())
    logger.info(f"✅ [Skill Discovery] 自动发现完成，共装载 {len(tool_list)} 个技能与工具。")
    return tool_list
