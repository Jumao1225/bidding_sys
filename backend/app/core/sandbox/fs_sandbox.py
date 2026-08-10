"""
Agent 文件系统与工作区隔离沙箱 (fs_sandbox.py)

功能：
1. 为 Agent 实例分配并管理独立安全的隔离工作区目录；
2. 校验文件访问路径，防止路径穿透（Path Traversal）与系统违规越界读写；
3. 提供原子事务（Transaction）与增量快照回滚机制，保护 Word/Excel 等标书文件在 Agent 异常时可一键恢复。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import os
import shutil
import uuid
from typing import List, Optional, Set
from contextlib import contextmanager
from loguru import logger

from app.core.sandbox.exceptions import SandboxPathViolationError, SandboxError


class FileSystemSandbox:
    """
    Agent 文件系统沙箱
    提供隔离工作区管理、路径越界校验以及事务快照/回滚支持。
    """

    def __init__(self, session_id: Optional[str] = None, base_dir: Optional[str] = None, allowed_paths: Optional[List[str]] = None):
        """
        初始化文件系统沙箱。

        :param session_id: 当前 Agent 会话/任务标识，默认为自动生成的 UUID
        :param base_dir: 沙箱根临时目录，默认位于项目 data/sandbox_workspaces 下
        :param allowed_paths: 允许读写的显式授权外部文件/目录列表（如上传的原始标书 Word 路径）
        """
        self.session_id: str = session_id or str(uuid.uuid4())
        
        # 定位根沙箱工作区目录
        if not base_dir:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            self.base_dir = os.path.abspath(os.path.join(project_root, "data", "sandbox_workspaces"))
        else:
            self.base_dir = os.path.abspath(base_dir)

        # 当前 session 的专用隔离工作目录
        self.workspace_dir: str = os.path.abspath(os.path.join(self.base_dir, self.session_id))
        
        # 允许访问的受信任文件列表
        self._allowed_paths: Set[str] = set()
        if allowed_paths:
            for p in allowed_paths:
                if p:
                    self._allowed_paths.add(os.path.realpath(os.path.abspath(p)))

        logger.debug(f"📦 [FS Sandbox] 初始化沙箱环境 session_id={self.session_id}, workspace={self.workspace_dir}")

    def ensure_workspace(self) -> str:
        """
        创建并确保专用工作区目录存在。

        :return: 规范化后的工作区目录路径
        """
        if not os.path.exists(self.workspace_dir):
            os.makedirs(self.workspace_dir, exist_ok=True)
            logger.info(f"📁 [FS Sandbox] 已创建会话隔离工作区目录: {self.workspace_dir}")
        return self.workspace_dir

    def add_allowed_path(self, path: str) -> None:
        """
        添加显式授权的访问路径（如用户上传的源文件）。

        :param path: 目标文件或目录路径
        """
        if not path:
            return
        real_p = os.path.realpath(os.path.abspath(path))
        self._allowed_paths.add(real_p)
        logger.debug(f"🔑 [FS Sandbox] 添加显式授权访问路径: {real_p}")

    def resolve_path(self, input_path: str, must_exist: bool = False) -> str:
        """
        规范化并严格校验输入路径是否在隔离工作区或授权白名单中。

        :param input_path: Agent 试图访问的目标文件路径
        :param must_exist: 是否强制要求目标路径必须存在
        :return: 规范化后的绝对路径 (Realpath)
        :raises SandboxPathViolationError: 当路径超出沙箱安全边界时抛出
        """
        if not input_path:
            raise SandboxPathViolationError("无法校验空路径")

        # 规范化绝对路径，解析相对路径与符号链接
        target_real = os.path.realpath(os.path.abspath(input_path))
        ws_real = os.path.realpath(os.path.abspath(self.workspace_dir))

        # 校验 1：路径是否属于专属工作区 (commonpath 判断)
        is_in_workspace = False
        try:
            common = os.path.commonpath([ws_real, target_real])
            if common == ws_real:
                is_in_workspace = True
        except ValueError:
            # 发生在跨不同盘符时（如 Windows C:\ 与 D:\）
            is_in_workspace = False

        # 校验 2：路径是否属于显式授权的白名单路径
        is_allowed = False
        if not is_in_workspace:
            for allowed in self._allowed_paths:
                try:
                    if os.path.commonpath([allowed, target_real]) == allowed:
                        is_allowed = True
                        break
                except ValueError:
                    continue

        # 如果既不在工作区也不在白名单中，拒绝访问
        if not is_in_workspace and not is_allowed:
            logger.warning(f"🚨 [FS Sandbox] 路径越界违规阻断: {input_path} (解析为: {target_real}), workspace={ws_real}")
            raise SandboxPathViolationError(
                f"沙箱路径越界拦截：禁止访问工作区外未经授权的路径 '{input_path}'",
                details={"target_path": target_real, "workspace_dir": ws_real}
            )

        # 如果要求文件必须存在
        if must_exist and not os.path.exists(target_real):
            raise SandboxPathViolationError(f"沙箱校验目标文件不存在: '{target_real}'")

        return target_real

    def create_snapshot(self, target_path: str) -> str:
        """
        为指定标书文件创建物理快照备份。

        :param target_path: 欲备份的文件路径
        :return: 快照文件路径
        """
        real_path = self.resolve_path(target_path, must_exist=True)
        snap_name = f".snap_{uuid.uuid4().hex[:8]}_{os.path.basename(real_path)}"
        snap_path = os.path.join(os.path.dirname(real_path), snap_name)

        try:
            shutil.copy2(real_path, snap_path)
            logger.info(f"📸 [FS Sandbox] 成功创建快照备份: {os.path.basename(real_path)} -> {snap_name}")
            return snap_path
        except Exception as e:
            logger.error(f"❌ [FS Sandbox] 创建快照失败: {e}")
            raise SandboxError(f"创建物理文件快照失败: {str(e)}")

    def restore_snapshot(self, target_path: str, snapshot_path: str) -> bool:
        """
        使用快照物理还原目标文件。

        :param target_path: 欲还原的文件路径
        :param snapshot_path: 快照文件路径
        :return: 是否恢复成功
        """
        if not snapshot_path or not os.path.exists(snapshot_path):
            logger.warning(f"⚠️ [FS Sandbox] 快照文件不存在，无法还原: {snapshot_path}")
            return False

        try:
            shutil.copy2(snapshot_path, target_path)
            logger.info(f"🔄 [FS Sandbox] 成功利用快照恢复文件: {target_path}")
            return True
        except Exception as e:
            logger.exception(f"❌ [FS Sandbox] 恢复文件快照异常: {e}")
            return False

    @contextmanager
    def transaction(self, target_files: Optional[List[str]] = None):
        """
        标书文件修改的原子事务上下文管理器。
        自动在进入时备份 target_files，若发生异常或主动回滚，自动全量恢复原文件；若正常结束则清除快照。

        示例用法：
        with sandbox.transaction(["/path/to/bid_document.docx"]):
            # Agent 执行填报修改
            ...
        """
        snapshots = {}
        target_files = target_files or []

        # 1. 事务开始：创建所有目标文件的物理快照
        for fpath in target_files:
            if fpath and os.path.exists(fpath):
                try:
                    snap_p = self.create_snapshot(fpath)
                    snapshots[fpath] = snap_p
                except Exception as exc:
                    logger.warning(f"⚠️ [FS Sandbox] 准备事务时创建快照跳过: {fpath}, err: {exc}")

        try:
            yield self
            # 2. 正常完成：成功处理，销毁快照文件
            logger.debug(f"✅ [FS Sandbox] 事务正常提交，清理 {len(snapshots)} 个快照备份")
            for fpath, snap_p in snapshots.items():
                if snap_p and os.path.exists(snap_p):
                    try:
                        os.remove(snap_p)
                    except Exception:
                        pass
        except Exception as err:
            # 3. 发生异常：回滚所有包含快照的文件
            logger.error(f"💥 [FS Sandbox] 事务捕获异常，触发原子回滚机制! 错误: {err}")
            for fpath, snap_p in snapshots.items():
                self.restore_snapshot(fpath, snap_p)
                if snap_p and os.path.exists(snap_p):
                    try:
                        os.remove(snap_p)
                    except Exception:
                        pass
            # 重新抛出原始异常，供上层处理
            raise err

    def clean_workspace(self) -> None:
        """
        清理销毁当前 Session 的工作区及其所有临时文件。
        """
        if os.path.exists(self.workspace_dir):
            try:
                shutil.rmtree(self.workspace_dir)
                logger.info(f"🧹 [FS Sandbox] 已经成功清理会话隔离工作区: {self.workspace_dir}")
            except Exception as e:
                logger.warning(f"⚠️ [FS Sandbox] 清理工作区异常: {e}")
