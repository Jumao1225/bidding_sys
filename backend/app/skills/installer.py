"""
技能在线下载与动态安装模块 (installer.py)

功能：
1. 提供 install_skill_from_url 工具，支持从 GitHub 仓库 URL、Zip 压缩包直链或 Raw SKILL.md 链接自动下载技能；
2. 自动安装并解压到 backend/app/skills/<skill_name>/ 目录；
3. 触发 SkillLoader 热重载，实现“在线安装 ➔ 立即生效”。
"""

import os
import re
import shutil
import tempfile
import zipfile
import subprocess
import urllib.request
from typing import Optional
from loguru import logger
from langchain_core.tools import tool

from app.skills.skill_loader import skill_loader


def _extract_skill_name_from_url(url: str, default_name: str = "custom_skill") -> str:
    """从 URL 提取建议的技能名称"""
    clean_url = url.rstrip("/").removesuffix(".git").removesuffix(".zip")
    base_name = clean_url.split("/")[-1]
    # 清理非合法文件名字符
    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '', base_name)
    return clean_name if clean_name else default_name


@tool
def install_skill_from_url(url: str, skill_name: Optional[str] = None) -> str:
    """
    [技能在线安装工具] 当用户提供一个技能的下载链接 (例如 Git 仓库地址、Zip 包链接或 SKILL.md 直链) 并要求安装时使用此工具。
    系统会自动下载该技能文件，安装到 backend/app/skills/ 目录下并实时热加载生效。

    :param url: 技能的下载或 Git 仓库链接 (如 'https://github.com/user/my-skill' 或 'https://example.com/skill.zip')
    :param skill_name: 可选的自定义技能名称，若不填则自动从 URL 中提取
    :return: 安装与热加载结果说明
    """
    logger.info(f"📦 [Skill Installer] 收到技能在线安装请求，URL: '{url}'")
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return "❌ 安装失败：请提供以 http:// 或 https:// 开头的合法技能链接。"

    target_name = skill_name.strip() if skill_name else _extract_skill_name_from_url(url)
    skills_base_dir = skill_loader.skills_dir
    target_skill_dir = os.path.join(skills_base_dir, target_name)

    try:
        # 1. 尝试使用 Git Clone (若为 GitHub 或以 .git 结尾的仓库链接)
        if "github.com" in url or url.endswith(".git"):
            logger.info(f"📦 [Skill Installer] 识别为 Git 仓库链接，使用 git clone 下载...")
            if os.path.exists(target_skill_dir):
                shutil.rmtree(target_skill_dir)

            res = subprocess.run(
                ["git", "clone", "--depth", "1", url, target_skill_dir],
                capture_output=True,
                text=True,
                timeout=60
            )

            if res.returncode == 0:
                skill_loader._reload_skills()
                logger.info(f"✅ [Skill Installer] 成功克隆并安装技能 '{target_name}'")
                return f"✅ 技能 [{target_name}] 已成功从 Git 仓库克隆并安装到 '{target_skill_dir}'，现已实时热加载生效！"
            else:
                logger.warning(f"⚠️ [Skill Installer] git clone 尝试未成功，降级尝试 HTTP 下载: {res.stderr}")

        # 2. HTTP 下载 (Zip 压缩包或单文件 SKILL.md)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BiddingSys SkillInstaller)"})
        with urllib.request.urlopen(req, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()

        os.makedirs(target_skill_dir, exist_ok=True)

        # 判断是否为 Zip 包
        if url.endswith(".zip") or "zip" in content_type:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                with zipfile.ZipFile(tmp_path, "r") as zip_ref:
                    zip_ref.extractall(target_skill_dir)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            
            skill_loader._reload_skills()
            logger.info(f"✅ [Skill Installer] 成功解压并安装技能 Zip 包 '{target_name}'")
            return f"✅ 技能 Zip 包 [{target_name}] 已成功解压并安装到 '{target_skill_dir}'，现已实时热加载生效！"

        # 判断是否为单文件 SKILL.md 或文本
        else:
            skill_file_path = os.path.join(target_skill_dir, "SKILL.md")
            with open(skill_file_path, "wb") as f:
                f.write(data)
            
            skill_loader._reload_skills()
            logger.info(f"✅ [Skill Installer] 成功保存 SKILL.md 并热装载技能 '{target_name}'")
            return f"✅ 技能文件 [{target_name}] 已成功保存到 '{skill_file_path}'，现已实时热加载生效！"

    except Exception as e:
        logger.exception(f"❌ [Skill Installer] 在线安装技能出现异常: {e}")
        return f"❌ 技能在线安装失败: {str(e)}"
