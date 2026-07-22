from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class PriceReferenceBase(BaseModel):
    item_name: str = Field(..., description="设备/物料名称")
    category: Optional[str] = Field(None, description="分类")
    brand: Optional[str] = Field(None, description="品牌")
    spec: Optional[str] = Field(None, description="规格")
    model: Optional[str] = Field(None, description="型号")
    manufacturer: Optional[str] = Field(None, description="生产厂商")
    unit_price: float = Field(..., description="指导单价")
    unit: str = Field(..., description="单位")
    remark: Optional[str] = Field(None, description="备注")

class PriceReferenceCreate(PriceReferenceBase):
    pass

class PriceReferenceUpdate(BaseModel):
    item_name: Optional[str] = Field(None, description="设备/物料名称")
    category: Optional[str] = Field(None, description="分类")
    brand: Optional[str] = Field(None, description="品牌")
    spec: Optional[str] = Field(None, description="规格")
    model: Optional[str] = Field(None, description="型号")
    manufacturer: Optional[str] = Field(None, description="生产厂商")
    unit_price: Optional[float] = Field(None, description="指导单价")
    unit: Optional[str] = Field(None, description="单位")
    remark: Optional[str] = Field(None, description="备注")

class PriceReferenceResponse(PriceReferenceBase):
    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

