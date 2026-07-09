from typing import TypeVar, Generic, Optional, Any
from pydantic import BaseModel, Field

T = TypeVar("T")

class ResponseModel(BaseModel, Generic[T]):
    """
    统一的 API 响应结构
    """
    code: int = Field(default=200, description="状态码，200 为成功")
    message: str = Field(default="success", description="返回信息提示")
    data: Optional[T] = Field(default=None, description="返回的具体数据")

def success_response(data: Any = None, message: str = "success") -> ResponseModel:
    """
    快捷构建成功响应
    """
    return ResponseModel(code=200, message=message, data=data)

def error_response(code: int, message: str, data: Any = None) -> ResponseModel:
    """
    快捷构建错误响应
    """
    return ResponseModel(code=code, message=message, data=data)
