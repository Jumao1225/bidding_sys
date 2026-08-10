"""
Agent 文件系统沙箱 (FileSystemSandbox) 单元测试

遵照项目 AGENTS.md 测试规范：
1. 包含正常情况、异常情况与边界情况；
2. 遵循 test_<功能>_<场景>_<期望结果> 命名规范；
3. 验证路径防越界跨越拦截与物理快照事务回滚功能。
"""

import os
import tempfile
import pytest
from app.core.sandbox import FileSystemSandbox, SandboxPathViolationError


def test_fs_sandbox_workspace_creation_should_succeed():
    """正常场景：测试文件系统沙箱初始化并自动创建隔离工作区目录"""
    with tempfile.TemporaryDirectory() as tmp_base:
        sandbox = FileSystemSandbox(session_id="test_sess_001", base_dir=tmp_base)
        ws_dir = sandbox.ensure_workspace()
        
        assert os.path.exists(ws_dir)
        assert ws_dir.endswith("test_sess_001")


def test_fs_sandbox_resolve_path_within_workspace_should_pass():
    """正常场景：测试解析工作区内部路径合规透出"""
    with tempfile.TemporaryDirectory() as tmp_base:
        sandbox = FileSystemSandbox(session_id="test_sess_002", base_dir=tmp_base)
        sandbox.ensure_workspace()
        
        target_path = os.path.join(sandbox.workspace_dir, "doc1.docx")
        resolved = sandbox.resolve_path(target_path)
        
        assert resolved == os.path.realpath(os.path.abspath(target_path))


def test_fs_sandbox_resolve_path_traversal_should_raise_violation():
    """异常与攻击场景：测试路径跨越 (..) 访问工作区外部非法目录应被拦截"""
    with tempfile.TemporaryDirectory() as tmp_base:
        sandbox = FileSystemSandbox(session_id="test_sess_003", base_dir=tmp_base)
        sandbox.ensure_workspace()
        
        illegal_path = os.path.join(sandbox.workspace_dir, "..", "..", "etc", "passwd")
        
        with pytest.raises(SandboxPathViolationError) as exc_info:
            sandbox.resolve_path(illegal_path)
            
        assert "沙箱路径越界拦截" in str(exc_info.value)


def test_fs_sandbox_allowed_path_white_list_should_pass():
    """边界场景：测试添加到白名单的外部路径可以合规访问"""
    with tempfile.TemporaryDirectory() as tmp_base, tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
        tmp_file_path = tmp_file.name
        try:
            sandbox = FileSystemSandbox(session_id="test_sess_004", base_dir=tmp_base, allowed_paths=[tmp_file_path])
            sandbox.ensure_workspace()
            
            resolved = sandbox.resolve_path(tmp_file_path)
            assert resolved == os.path.realpath(os.path.abspath(tmp_file_path))
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)


def test_fs_sandbox_transaction_rollback_on_error_should_restore_file():
    """异常场景：测试在事务块内写入失败抛异常时，快照备份能够自动原子回滚原文件"""
    with tempfile.TemporaryDirectory() as tmp_base:
        sandbox = FileSystemSandbox(session_id="test_sess_005", base_dir=tmp_base)
        sandbox.ensure_workspace()
        
        doc_path = os.path.join(sandbox.workspace_dir, "test_doc.txt")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("原始未修改文本")
            
        # 尝试在事务中被破坏性修改，然后触发 Exception
        with pytest.raises(RuntimeError):
            with sandbox.transaction([doc_path]):
                with open(doc_path, "w", encoding="utf-8") as f:
                    f.write("破坏性的中间篡改文本")
                raise RuntimeError("模拟 Agent 填报失败报错！")

        # 校验文件恢复为原始未修改文本
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert content == "原始未修改文本"
