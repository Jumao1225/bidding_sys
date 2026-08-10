"""
Agent 代码与计算表达式沙箱 (CodeExecutionSandbox) 单元测试

遵照项目 AGENTS.md 测试规范：
1. 包含正常情况、异常情况与边界情况；
2. 遵循 test_<功能>_<场景>_<期望结果> 命名规范；
3. 验证 AST 安全语法审查拦截与受限环境运行能力。
"""

import pytest
from app.core.sandbox import CodeExecutionSandbox, SandboxCodeSecurityError


def test_code_sandbox_safe_math_expression_should_succeed():
    """正常场景：测试数学与数据格式处理代码在沙箱中正常运行并返回结果"""
    sandbox = CodeExecutionSandbox()
    code = """
x = 100
y = 200
result = math.sqrt(x) + y
"""
    res = sandbox.execute(code)
    assert res["success"] is True
    assert res["result"] == 210.0
    assert res["error"] is None


def test_code_sandbox_forbidden_import_os_should_be_blocked_by_ast():
    """异常/黑客注入场景：测试 import os 危险代码被 AST 静态拦截"""
    sandbox = CodeExecutionSandbox()
    code = "import os\nos.system('whoami')"
    
    with pytest.raises(SandboxCodeSecurityError) as exc_info:
        sandbox.execute(code)
        
    assert "禁止导入危险模块: 'os'" in str(exc_info.value)


def test_code_sandbox_forbidden_eval_call_should_be_blocked():
    """异常场景：测试调用危险内置函数 eval() 被拦截"""
    sandbox = CodeExecutionSandbox()
    code = "result = eval('1 + 1')"
    
    with pytest.raises(SandboxCodeSecurityError) as exc_info:
        sandbox.execute(code)
        
    assert "禁止调用敏感危险函数: 'eval()'" in str(exc_info.value)


def test_code_sandbox_forbidden_subclasses_reflection_should_be_blocked():
    """攻击场景：测试通过 __subclasses__() 底层反射提权代码被拦截"""
    sandbox = CodeExecutionSandbox()
    code = "classes = (1).__class__.__base__.__subclasses__()"
    
    with pytest.raises(SandboxCodeSecurityError) as exc_info:
        sandbox.execute(code)
        
    assert "禁止访问底层反射机制属性: '__subclasses__'" in str(exc_info.value)


def test_code_sandbox_infinite_loop_timeout_should_return_error():
    """边界场景：测试无限循环代码达到超时上限被强行截断"""
    sandbox = CodeExecutionSandbox(default_timeout_seconds=0.5)
    code = """
while True:
    pass
"""
    res = sandbox.execute(code)
    assert res["success"] is False
    assert "超时" in res["error"]
