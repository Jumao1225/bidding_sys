"""
Agent 命令行与外部子进程沙箱 (CommandSandbox) 单元测试

遵照项目 AGENTS.md 测试规范：
1. 包含正常情况、异常情况与边界情况；
2. 遵循 test_<功能>_<场景>_<期望结果> 命名规范；
3. 标记 @pytest.mark.asyncio。
"""

import os
import pytest
from app.core.sandbox import CommandSandbox, SandboxCommandError


def test_cmd_sandbox_sanitize_environment_should_remove_sensitive_keys():
    """正常场景：测试环境变量脱敏净化，擦除所有含 KEY/SECRET/TOKEN 的变量"""
    os.environ["TEST_MY_SECRET_KEY"] = "super_secret_123"
    os.environ["TEST_SAFE_VAR"] = "normal_val"

    try:
        cmd_box = CommandSandbox()
        clean_env = cmd_box.sanitize_environment()

        assert "TEST_MY_SECRET_KEY" not in clean_env
        assert clean_env.get("TEST_SAFE_VAR") == "normal_val"
    finally:
        os.environ.pop("TEST_MY_SECRET_KEY", None)
        os.environ.pop("TEST_SAFE_VAR", None)


def test_cmd_sandbox_unauthorized_command_should_be_blocked():
    """异常场景：测试非白名单二进制程序 (如 powershell / bash / netcat) 被阻断"""
    cmd_box = CommandSandbox(allowed_commands={"officecli", "python"})
    
    with pytest.raises(SandboxCommandError) as exc_info:
        cmd_box.validate_command(["powershell", "-Command", "Get-Process"])
        
    assert "不在允许调用的系统 CLI 白名单中" in str(exc_info.value)


def test_cmd_sandbox_command_injection_should_be_blocked():
    """攻击场景：测试命令入参中包含 ';' 或 '&&' 等 Shell 注入字符被阻断"""
    cmd_box = CommandSandbox(allowed_commands={"officecli"})
    
    with pytest.raises(SandboxCommandError) as exc_info:
        cmd_box.validate_command(["officecli", "query", "/body/p[1] && rmdir /s /q C:\\"])
        
    assert "检测到可能的 Shell 注入字符" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cmd_sandbox_whitelisted_python_command_should_succeed():
    """正常场景：测试白名单中的 python 指令异步运行成功"""
    cmd_box = CommandSandbox(allowed_commands={"python", "python.exe"})
    res = await cmd_box.execute_async(["python", "-c", "print('hello_sandbox')"])
    
    assert res["success"] is True
    assert "hello_sandbox" in res["stdout"]
