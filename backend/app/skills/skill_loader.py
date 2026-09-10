"""
业务 Skill 动态解析与加载器 (skill_loader.py)

本模块只扫描 backend/app/skills 下的 SKILL.md 操作规范。Python 文件中的
@tool 函数属于 Tool，由 registry.py 负责发现；本模块不把 Tool 当作 Skill。
"""

import os
import re
from typing import Dict, List, Optional
from loguru import logger
from langchain_core.tools import tool


class SkillLoader:
    """只负责加载和管理 SKILL.md 操作规范的服务。"""

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir is None:
            # 招投标业务系统专属技能目录：backend/app/skills/ (与 IDE 的 .agents 彻底隔离)
            skills_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.skills_dir = skills_dir
        self.skills_cache: Dict[str, Dict[str, str]] = {}
        self._catalog_loaded = False

    def _reload_skills(self):
        """扫描 Skill 元数据，不读取完整 SOP 正文。"""
        self.skills_cache.clear()
        self._catalog_loaded = True
        if not os.path.exists(self.skills_dir):
            logger.warning(f"⚠️ [SkillLoader] 技能目录不存在: {self.skills_dir}")
            return

        for root, dirs, files in os.walk(self.skills_dir):
            if "SKILL.md" in files:
                skill_file = os.path.join(root, "SKILL.md")
                try:
                    meta = self._read_frontmatter_metadata(skill_file)
                    skill_name = meta.get("name", os.path.basename(root))
                    description = meta.get("description", "暂无描述")

                    self.skills_cache[skill_name] = {
                        "name": skill_name,
                        "description": description,
                        "file_path": skill_file
                    }
                    logger.info(f"📚 [SkillLoader] 发现 Skill 元数据: '{skill_name}'")
                except Exception as e:
                    logger.exception(f"❌ [SkillLoader] 读取技能元数据失败 {skill_file}: {e}")

    def reload_skills(self) -> None:
        """公开重新扫描入口，支持运行期间发现新加入的 Skill 文件夹。"""
        self._reload_skills()

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

    def _read_frontmatter_metadata(self, skill_file: str) -> dict[str, str]:
        """只读取 SKILL.md 顶部 Frontmatter，避免扫描目录时加载正文。"""
        metadata: dict[str, str] = {}
        with open(skill_file, "r", encoding="utf-8") as skill_handle:
            if skill_handle.readline().strip() != "---":
                return metadata

            for line in skill_handle:
                normalized_line = line.strip()
                if normalized_line == "---":
                    break
                if ":" not in normalized_line or normalized_line.startswith("#"):
                    continue
                key, value = normalized_line.split(":", 1)
                metadata[key.strip()] = value.strip().strip("'\"")
        return metadata

    def get_skill_catalog_prompt(self) -> str:
        """生成渐进式披露第一层：只包含 SKILL.md 的元数据摘要。"""
        if not self._catalog_loaded:
            self.reload_skills()
        if not self.skills_cache:
            return "【可用 Skill 目录（仅 SKILL.md，不包含 Tool）】: 当前暂无已安装 Skill。"

        lines = ["【可用 Skill 目录（第一层：仅元数据，不包含完整 SOP 或 Tool）】:"]
        for name in sorted(self.skills_cache):
            info = self.skills_cache[name]
            lines.append(f"- **{name}**: {info['description']}")
        lines.append("提示：如需查看 Skill 的完整 SOP，请进入第二层并调用 `load_agent_skill(skill_name)` Tool。")
        return "\n".join(lines)

    def get_skill_instruction(self, skill_name: str) -> str:
        """获取渐进式披露第二层：特定 Skill 的完整 SOP 指南。"""
        if not self._catalog_loaded:
            self.reload_skills()
        skill_info = self.skills_cache.get(skill_name)
        if not skill_info:
            return f"❌ 未找到名为 '{skill_name}' 的技能。可用技能包括: {list(self.skills_cache.keys())}"

        instruction = skill_info.get("instruction")
        if instruction is None:
            try:
                with open(skill_info["file_path"], "r", encoding="utf-8") as skill_handle:
                    content = skill_handle.read()
                _, instruction = self._parse_frontmatter(content)
                skill_info["instruction"] = instruction
                logger.info(f"📖 [SkillLoader] 按需加载 Skill SOP: '{skill_name}'")
            except (OSError, UnicodeDecodeError) as exc:
                logger.exception(f"❌ [SkillLoader] 读取 Skill SOP 失败 {skill_info['file_path']}: {exc}")
                return f"❌ 读取 Skill '{skill_name}' 的 SOP 失败: {exc}"

        return f"=== Skill [{skill_name}] SOP 指南（第二层） ===\n{instruction}"

    def get_skill_resource(self, skill_name: str, resource_path: str) -> str:
        """安全读取指定 Skill 目录中的单个引用资源。"""
        if not self._catalog_loaded:
            self.reload_skills()
        skill_info = self.skills_cache.get(skill_name)
        if not skill_info:
            return f"❌ 未找到名为 '{skill_name}' 的 Skill。请先调用 list_agent_skills 确认名称。"

        if not resource_path or os.path.isabs(resource_path):
            return "❌ 资源路径必须是 Skill 目录内的相对路径。"

        skill_root = os.path.abspath(os.path.dirname(skill_info["file_path"]))
        resource_file = os.path.abspath(os.path.join(skill_root, resource_path))
        try:
            if os.path.commonpath([skill_root, resource_file]) != skill_root:
                return "❌ 资源路径超出 Skill 目录范围，已拒绝读取。"
        except ValueError:
            return "❌ 资源路径无效，已拒绝读取。"

        if not os.path.isfile(resource_file):
            return f"❌ 未找到 Skill [{skill_name}] 的资源: {resource_path}"

        try:
            with open(resource_file, "r", encoding="utf-8") as resource_handle:
                resource_content = resource_handle.read()
        except UnicodeDecodeError:
            return f"❌ 资源 [{resource_path}] 不是 UTF-8 文本，当前 Tool 不读取二进制资源。"
        except OSError as exc:
            logger.exception(f"❌ [SkillLoader] 读取 Skill 资源失败 {resource_file}: {exc}")
            return f"❌ 读取 Skill 资源失败: {exc}"

        logger.info(f"📄 [SkillLoader] 按需加载 Skill 资源: '{skill_name}/{resource_path}'")
        return f"=== Skill [{skill_name}] 资源（第三层）: {resource_path} ===\n{resource_content}"


# 全局单例加载器
skill_loader = SkillLoader()


@tool
def load_agent_skill(skill_name: str) -> str:
    """
    [Skill SOP 读取 Tool] 当你需要了解特定领域的操作规范时调用此 Tool，返回渐进式披露第二层的完整 SKILL.md。

    :param skill_name: Skill 名称，例如 'docx'、'officecli' 或 'mcp-builder'
    :return: Skill 的详细操作规范与工作流 Markdown 文本
    """
    # 读取前刷新目录，确保运行期间新增或更新的 SKILL.md 立即生效。
    skill_loader.reload_skills()
    return skill_loader.get_skill_instruction(skill_name)


@tool
def load_agent_skill_resource(skill_name: str, resource_path: str) -> str:
    """
    [Skill 资源读取 Tool] 仅在 Skill SOP 明确引用某个文件时，按需读取该文件。

    支持读取 Skill 目录内的 UTF-8 文本资源，例如 references/*.md、scripts/*.py。
    不允许使用绝对路径或路径穿越读取 Skill 目录之外的文件。
    """
    # 资源读取前刷新目录，确保新安装的 Skill 及其引用文件立即可用。
    skill_loader.reload_skills()
    return skill_loader.get_skill_resource(skill_name, resource_path)


@tool
def list_agent_skills() -> str:
    """
    [Skill 列表 Tool] 列出当前业务系统已发现的全部 SKILL.md Skill 及其用途。

    本工具只返回 Skill，不返回 Python 可执行 Tool。
    用户询问可用 Skill、已安装 Skill 或要求确认某个 Skill 是否存在时，必须优先调用本工具。
    """
    # 每次列目录前刷新文件系统，确保运行期间新增的 Skill 文件夹也能被发现。
    skill_loader.reload_skills()
    catalog = skill_loader.get_skill_catalog_prompt()
    logger.info(f"📚 [SkillLoader] 已刷新并返回 {len(skill_loader.skills_cache)} 个可用 Skill")
    return catalog
