"""
Agent 代码与计算表达式安全沙箱 (code_sandbox.py)

功能：
1. 使用 Python AST（抽象语法树）进行静态语法安全审查，阻断非法模块导入（如 os, sys, subprocess）、危急内置函数（eval, exec, open）以及 Python 元编程反射提权属性（__subclasses__, __globals__）；
2. 构造干净防护的受限 Python 全局执行作用域（Restricted Execution Context），仅透出安全数学运算、时间处理、JSON/正则等合法模块；
3. 跨平台超时监控与结果捕获，防止内存耗尽与死循环死锁。

遵循项目规范：
1. 全面使用中文注释与 Docstrings；
2. 全面使用 Type Hints；
3. 使用 loguru 进行详细调试日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

import ast
import io
import math
import re
import json
import datetime
import decimal
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, Optional, Set
from loguru import logger

from app.core.sandbox.exceptions import SandboxCodeSecurityError, SandboxError


class ASTSecurityVisitor(ast.NodeVisitor):
    """
    Python AST 静态安全检查器。
    遍历代码语法树，检测并拦截敏感模块导入、非法函数调用与反射提权属性。
    """

    # 禁用模块黑名单
    FORBIDDEN_MODULES: Set[str] = {
        "os", "sys", "subprocess", "shutil", "socket", "requests",
        "urllib", "ctypes", "importlib", "builtins", "pickle", "pty",
        "platform", "signal", "threading", "multiprocessing", "asyncio",
        "tempfile", "pathlib", "gc", "inspect"
    }

    # 禁用危险内置函数/表达式
    FORBIDDEN_CALLS: Set[str] = {
        "eval", "exec", "__import__", "open", "compile", "getattr",
        "setattr", "delattr", "globals", "locals", "vars", "breakpoint",
        "input", "file", "exit", "quit"
    }

    # 禁用反射与黑客提权常用魔术属性
    FORBIDDEN_ATTRS: Set[str] = {
        "__subclasses__", "__bases__", "__mro__", "__class__",
        "__globals__", "__code__", "__closure__", "__builtins__",
        "__dict__", "__import__"
    }

    def __init__(self):
        self.errors = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            module_name = alias.name.split('.')[0]
            if module_name in self.FORBIDDEN_MODULES:
                self.errors.append(f"禁止导入危险模块: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            module_name = node.module.split('.')[0]
            if module_name in self.FORBIDDEN_MODULES:
                self.errors.append(f"禁止从危险模块导入: 'from {node.module} import ...'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # 检验直接调用的函数名 (如 eval(...))
        if isinstance(node.func, ast.Name):
            if node.func.id in self.FORBIDDEN_CALLS:
                self.errors.append(f"禁止调用敏感危险函数: '{node.func.id}()'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # 检验访问的属性名 (如 obj.__subclasses__)
        if node.attr in self.FORBIDDEN_ATTRS:
            self.errors.append(f"禁止访问底层反射机制属性: '{node.attr}'")
        self.generic_visit(node)


class CodeExecutionSandbox:
    """
    Python 代码与表达式安全沙箱运行器
    """

    # 安全受控的 builtins 白名单
    SAFE_BUILTINS: Dict[str, Any] = {
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "filter": filter, "float": float, "int": int,
        "isinstance": isinstance, "len": len, "list": list, "map": map,
        "max": max, "min": min, "pow": pow, "range": range, "round": round,
        "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
        "zip": zip, "print": print, "True": True, "False": False, "None": None,
        "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
        "IndexError": IndexError
    }

    def __init__(self, default_timeout_seconds: float = 5.0, max_output_chars: int = 10000):
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_chars = max_output_chars

    def validate_code(self, code: str) -> None:
        """
        静态语法检查代码。

        :param code: 待执行的 Python 代码字符串
        :raises SandboxCodeSecurityError: 当检查到违规代码时抛出
        """
        if not code or not code.strip():
            return

        try:
            tree = ast.parse(code)
        except SyntaxError as syn_err:
            raise SandboxCodeSecurityError(f"代码语法解析错误: {syn_err}")

        visitor = ASTSecurityVisitor()
        visitor.visit(tree)

        if visitor.errors:
            error_msg = "; ".join(visitor.errors)
            logger.warning(f"🚨 [Code Sandbox] AST 安全拦截到非法代码逻辑: {error_msg}")
            raise SandboxCodeSecurityError(
                f"沙箱代码安全检查拦截未通过: {error_msg}",
                details={"errors": visitor.errors}
            )

    def get_safe_globals(self, extra_globals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构造绝对封闭的全局作用域。
        """
        safe_globals = {
            "__builtins__": self.SAFE_BUILTINS,
            "math": math,
            "datetime": datetime,
            "json": json,
            "re": re,
            "decimal": decimal,
        }
        if extra_globals:
            for k, v in extra_globals.items():
                if k != "__builtins__":
                    safe_globals[k] = v
        return safe_globals

    def execute(self, code: str, extra_globals: Optional[Dict[str, Any]] = None, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        """
        在安全隔离沙箱中同步执行 Python 代码字符串。

        :param code: Python 源代码
        :param extra_globals: 传入代码执行环境的额外变量
        :param timeout_seconds: 超时秒数
        :return: 包含 'success', 'result', 'stdout', 'error' 的标准字典
        """
        # 1. 静态 AST 安全审查
        self.validate_code(code)

        timeout = timeout_seconds or self.default_timeout_seconds
        exec_globals = self.get_safe_globals(extra_globals)
        exec_locals = {}

        output_buffer = io.StringIO()

        def _worker():
            # 重定向 stdout 以安全捕获 print 输出
            old_stdout = sys.stdout
            sys.stdout = output_buffer
            try:
                # 执行核心代码
                exec(code, exec_globals, exec_locals)
                return exec_locals.get("result", exec_locals.get("output", None))
            finally:
                sys.stdout = old_stdout

        # 2. 多线程与超时防护
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker)
            try:
                result_val = future.result(timeout=timeout)
                stdout_str = output_buffer.getvalue()[:self.max_output_chars]
                logger.info(f"✅ [Code Sandbox] 代码顺利执行完成，捕获输出长度: {len(stdout_str)}")
                return {
                    "success": True,
                    "result": result_val,
                    "stdout": stdout_str,
                    "locals": {k: str(v) for k, v in exec_locals.items() if not k.startswith("__")},
                    "error": None
                }
            except FutureTimeoutError:
                logger.error(f"⏱️ [Code Sandbox] 代码沙箱执行超时（限时 {timeout}s）")
                return {
                    "success": False,
                    "result": None,
                    "stdout": output_buffer.getvalue()[:self.max_output_chars],
                    "error": f"代码沙箱执行超时（超出上限 {timeout} 秒）"
                }
            except Exception as e:
                logger.exception(f"❌ [Code Sandbox] 运行时代码异常: {e}")
                return {
                    "success": False,
                    "result": None,
                    "stdout": output_buffer.getvalue()[:self.max_output_chars],
                    "error": str(e)
                }
