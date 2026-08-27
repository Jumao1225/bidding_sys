"""
企业基础档案 Schema 定义。

支持多主体列表式管理，包含创建、更新、响应与列表响应模型。
"""

from datetime import datetime
from typing import Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class CompanyProfileBase(BaseModel):
    """企业档案基础字段"""
    profile_name: Optional[str] = Field(default=None, description="档案显示名称")
    company_name: Optional[str] = Field(default=None, description="投标人公司全称")
    legal_representative: Optional[str] = Field(default=None, description="法定代表人姓名")
    authorized_delegate: Optional[str] = Field(default=None, description="授权委托代理人姓名")
    credit_code: Optional[str] = Field(default=None, description="统一社会信用代码")
    registered_address: Optional[str] = Field(default=None, description="注册/通信地址")
    contact_phone: Optional[str] = Field(default=None, description="联系电话")
    email: Optional[str] = Field(default=None, description="电子邮箱")
    bank_name: Optional[str] = Field(default=None, description="开户银行名称")
    bank_account: Optional[str] = Field(default=None, description="银行账号")


class CompanyProfileCreate(CompanyProfileBase):
    """创建企业档案请求体"""
    profile_name: str = Field(..., min_length=1, max_length=100, description="档案显示名称（必填）")


class CompanyProfileUpdate(CompanyProfileBase):
    """更新企业档案请求体（所有字段可选）"""
    pass


class CompanyProfileResponse(CompanyProfileBase):
    """单条企业档案响应"""
    id: Optional[str] = None
    is_default: bool = Field(default=False, description="是否为默认档案")
    created_at: Optional[Union[datetime, str]] = Field(default=None, description="创建时间")
    updated_at: Optional[Union[datetime, str]] = Field(default=None, description="更新时间")
    model_config = ConfigDict(from_attributes=True)


class CompanyProfileListResponse(BaseModel):
    """企业档案列表响应"""
    profiles: list[CompanyProfileResponse] = Field(default_factory=list, description="档案列表")
    total: int = Field(default=0, description="总数")
