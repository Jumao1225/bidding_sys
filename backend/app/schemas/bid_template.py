"""外部投标模板 API Schema。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BidTemplateResponse(BaseModel):
    """外部投标模板返回结构。"""

    id: str
    filename: str
    file_size: int
    file_sha256: str
    content_type: Optional[str] = None
    template_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BidTemplateBindingRequest(BaseModel):
    """将模板绑定到指定招标文档的请求。"""

    template_id: str = Field(..., min_length=1, description="已上传的外部模板 ID")
    note: Optional[str] = Field(default=None, max_length=1000, description="绑定备注")


class BidTemplateBindingResponse(BaseModel):
    """模板绑定返回结构。"""

    id: str
    document_id: str
    template_id: str
    status: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
