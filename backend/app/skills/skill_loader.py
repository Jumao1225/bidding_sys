"""
官方 Agent Skill 动态解析与加载器 (skill_loader.py)

功能：
1. 自动扫描 .agents/skills/ 目录下的所有 SKILL.md 官方规范技能文件；
2. 解析 YAML Frontmatter (name, description) 生成技能目录提示；
3. 封装 load_agent_skill 工具，允许自定义 Agent 按需加载任意技能的具体 SOP 工作流。
"""

import os
import re
from typing import Dict, List, Optional
from loguru import logger
from langchain_core.tools import tool


class SkillLoader:
    """官方 Agent Skill 加载与管理服务"""

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir is None:
            # 招投标业务系统专属技能目录：backend/app/skills/ (与 IDE 的 .agents 彻底隔离)
            skills_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.skills_dir = skills_dir
        self.skills_cache: Dict[str, Dict[str, str]] = {}
        self._reload_skills()

    def _reload_skills(self):
        """扫描并加载所有 SKILL.md 文件"""
        self.skills_cache.clear()
        if not os.path.exists(self.skills_dir):
            logger.warning(f"⚠️ [SkillLoader] 技能目录不存在: {self.skills_dir}")
            return

        for root, dirs, files in os.walk(self.skills_dir):
            if "SKILL.md" in files:
                skill_file = os.path.join(root, "SKILL.md")
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    meta, body = self._parse_frontmatter(content)
                    skill_name = meta.get("name", os.path.basename(root))
                    description = meta.get("description", "暂无描述")

                    self.skills_cache[skill_name] = {
                        "name": skill_name,
                        "description": description,
                        "instruction": body,
                        "file_path": skill_file
                    }
                    logger.info(f"✨ [SkillLoader] 成功加载官方技能: '{skill_name}'")
                except Exception as e:
                    logger.error(f"❌ [SkillLoader] 读取技能文件失败 {skill_file}: {e}")

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """解析 YAML Frontmatter 元数据"""
        frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
        match = frontmatter_pattern.match(content)
        if not match:
            return {}, content

        yaml_str, body = match.group(1), match.group(2)
        meta = {}
        for line in yaml_str.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip("'\"")

        return meta, body

    def get_skill_catalog_prompt(self) -> str:
        """生成供 Agent System Prompt 使用的技能目录摘要"""
        if not self.skills_cache:
            return "【可用官方技能】: 当前暂无已安装技能。"

        lines = ["【可用官方技能 (Skill Catalog)】:"]
        for name, info in self.skills_cache.items():
            lines.append(f"- **{name}**: {info['description']}")
        lines.append("提示：如需查看技能的完整 SOP 操作指南，请调用 `load_agent_skill(skill_name)` 工具。")
        return "\n".join(lines)

    def get_skill_instruction(self, skill_name: str) -> str:
        """获取特定技能的完整 SOP 指南"""
        skill_info = self.skills_cache.get(skill_name)
        if not skill_info:
            return f"❌ 未找到名为 '{skill_name}' 的技能。可用技能包括: {list(self.skills_cache.keys())}"
        return f"=== 技能 [{skill_name}] SOP 指南 ===\n{skill_info['instruction']}"


# 全局单例加载器
skill_loader = SkillLoader()


@tool
def load_agent_skill(skill_name: str) -> str:
    """
    [官方 Skill 调取工具] 当你需要了解如何操作特定领域（如 docx 排版、office-cli 操作、webapp 测试）的具体 SOP 指南或规则时调用此工具。

    :param skill_name: 技能名称（例如 'docx', 'office-cli', 'mcp-builder'）
    :return: 技能的详细操作规范与工作流 Markdown 文本
    """
    return skill_loader.get_skill_instruction(skill_name)
