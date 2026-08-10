"""
OfficeCLIService - OfficeCLI 命令行底层异步服务封装

基于 OfficeCLI 提供高性能 .docx/.pptx/.xlsx 的增删改查与批处理操作。
遵循项目规范：
1. 全全面面使用中文注释与 Docstring；
2. 全全面面使用 Type Hints 类型提示；
3. 使用 loguru 进行详细日志记录；
4. 防御性编程与尽早返回（Early Return）。
"""

import os
import shutil
import json
import asyncio
import tempfile
from typing import List, Dict, Any, Optional
from loguru import logger


class OfficeCLIService:
    """
    OfficeCLI 工具封装服务类，提供无头 Office 文档自动化操作能力
    """

    def __init__(self, cli_path: Optional[str] = None):
        """
        初始化 OfficeCLIService，自动检测可执行路径
        """
        self.cli_path = cli_path or self._find_cli_path()
        logger.info(f"OfficeCLIService 初始化，当前使用的 OfficeCLI 路径: {self.cli_path}")

    def _find_cli_path(self) -> str:
        """
        查找系统中的 officecli 可执行路径
        """
        # 1. 优先检测系统环境变量 PATH 中的 officecli
        which_path = shutil.which("officecli")
        if which_path:
            return which_path

        # 2. 检测 Windows 默认安装路径
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            windows_default = os.path.join(local_app_data, "OfficeCLI", "officecli.exe")
            if os.path.exists(windows_default):
                return windows_default

        # 默认回退
        return "officecli"

    async def _run_command(self, args: List[str]) -> str:
        """
        异步执行底层 officecli 子进程命令并捕获输出 (兼容 Windows Uvicorn 各种 EventLoop 策略)
        """
        import subprocess

        cmd = [self.cli_path] + args
        logger.debug(f"正在执行 OfficeCLI 命令: {' '.join(cmd)}")

        def _exec_sync():
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )

        try:
            completed_proc = await asyncio.to_thread(_exec_sync)

            stdout_str = (completed_proc.stdout or "").strip()
            stderr_str = (completed_proc.stderr or "").strip()

            if completed_proc.returncode != 0:
                raise RuntimeError(f"OfficeCLI 执行失败: {stderr_str or stdout_str}")

            return stdout_str
        except FileNotFoundError:
            logger.exception("找不到 officecli 可执行文件，请检查系统 PATH 是否已配置。")
            raise RuntimeError("系统未安装 OfficeCLI 或无法在 PATH 中找到。")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning(f"执行 OfficeCLI 子进程产生未预期异常: {str(e)}")
            raise

    async def check_available(self) -> bool:
        """
        检查 OfficeCLI 是否正常可用
        """
        try:
            res = await self._run_command(["--version"])
            logger.info(f"OfficeCLI 版本检测正常: {res}")
            return True
        except Exception as e:
            logger.warning(f"OfficeCLI 可用性检测未通过: {str(e)}")
            return False

    async def create_blank_docx(self, file_path: str) -> str:
        """
        根据指定路径创建空白 Word (.docx) 文档
        """
        if not file_path:
            raise ValueError("文件路径不能为空")

        output = await self._run_command(["create", file_path])
        logger.info(f"成功创建空白 DOCX 文档: {file_path}")
        return output

    async def query_structure(self, file_path: str, selector: str = "paragraph") -> str:
        """
        查询 DOCX 文档中指定 CSS 样式的节点结构 (如 'paragraph' / 'table')
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"目标文档不存在: {file_path}")

        output = await self._run_command(["query", file_path, selector])
        return output

    async def apply_batch(self, file_path: str, commands: List[Dict[str, Any]]) -> str:
        """
        通过命令数组批量修改文档节点（单次磁盘 I/O，性能最高）。
        包含智能容错机制：若因合并单元格或 DOM 差异导致个别 Path 不存在，
        自动过滤排除错误 Path 并重试，确保其余 99% 有效槽位全部成功原位写入！
        """
        if not commands:
            logger.warning("批处理指令列表为空，忽略执行")
            return ""

        # 使用临时文件传递 JSON 数组
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(commands, tf, ensure_ascii=False, indent=2)
            temp_json_path = tf.name

        try:
            output = await self._run_command(["batch", file_path, "--input", temp_json_path])
            logger.info(f"OfficeCLI 批量执行成功 ({len(commands)} 条指令) 文件: {file_path}")
            return output
        except RuntimeError as err:
            err_str = str(err)
            import re
            # 正则匹配错误行，如 "[36] ERROR: Path not found: /body/tbl[2]/tr[20]/tc[2]"
            bad_indices = set(int(m) - 1 for m in re.findall(r'\[(\d+)\]\s+ERROR:', err_str))
            
            if bad_indices and len(commands) > len(bad_indices):
                logger.warning(f"⚠️ OfficeCLI 批处理中检测到 {len(bad_indices)} 条无效物理 Path (如合并单元格偏差)，开启智能容错剔除重试...")
                filtered_commands = [cmd for idx, cmd in enumerate(commands) if idx not in bad_indices]
                for idx in bad_indices:
                    if 0 <= idx < len(commands):
                        logger.warning(f"   └─ 已安全剔除无效 Path 指令: {commands[idx].get('path')}")
                
                # 递归重试剔除后的有效指令列表
                return await self.apply_batch(file_path, filtered_commands)
            else:
                # 若无法排除则向上抛出
                raise
        finally:
            if os.path.exists(temp_json_path):
                try:
                    os.remove(temp_json_path)
                except Exception as e:
                    logger.warning(f"清理批处理临时文件失败: {str(e)}")

    async def batch_update(self, file_path: str, commands_or_json: Any) -> str:
        """
        统一的批处理修改入口，兼容 List[Dict] 与 JSON 字符串格式
        """
        if isinstance(commands_or_json, str):
            try:
                commands = json.loads(commands_or_json)
            except Exception as e:
                logger.error(f"解析 batch_update JSON 指令产生异常: {e}")
                return ""
        elif isinstance(commands_or_json, list):
            commands = commands_or_json
        else:
            commands = []

        return await self.apply_batch(file_path, commands)


    async def save_and_close(self, file_path: str) -> str:
        """
        关闭驻留进程并刷盘落盘
        """
        try:
            output = await self._run_command(["close", file_path])
            logger.info(f"已刷盘并关闭 OfficeCLI 驻留进程: {file_path}")
            return output
        except Exception as e:
            logger.warning(f"关闭 OfficeCLI 驻留进程提示 (忽略非致命问题): {str(e)}")
            return ""

    async def merge_template(self, template_path: str, output_path: str, data: Dict[str, Any]) -> str:
        """
        使用数据合并 Word 模版里的 {{占位符}} 变量
        """
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"模版文件不存在: {template_path}")

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            temp_json_path = tf.name

        try:
            output = await self._run_command(["merge", template_path, output_path, "--input", temp_json_path])
            logger.info(f"模板数据合并完成: {output_path}")
            return output
        finally:
            if os.path.exists(temp_json_path):
                try:
                    os.remove(temp_json_path)
                except Exception:
                    pass


# 全局单例
office_cli_service = OfficeCLIService()
