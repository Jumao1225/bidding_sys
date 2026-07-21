from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime

# Schema for LLM Extraction
class QualificationExtractedData(BaseModel):
    name: str = Field(..., description="资质名称，如营业执照、安全生产许可证、各类施工资质等。如果有安全生产许可证，请务必作为单独的一个资质提取出来！")
    company_name: str | None = Field(..., description="该资质所属的公司名称，如XXX建筑工程有限公司。必须填写！如果找不到填 null。")
    level: str | None = Field(..., description="资质等级或级别，如 '一级', '特级', 'AAA'。如果原文没有明确说明等级或不知道，请统一填 '无'")
    expiry_date: date | None = Field(..., description="资质有效期至，如果是长期有效或原文中没有明确的到期日期，请直接填 null，严禁自行编造或推延日期！格式 YYYY-MM-DD")

class QualificationExtractionResult(BaseModel):
    qualifications: list[QualificationExtractedData] = Field(..., description="文档中提取出的所有独立资质列表")

# API Schemas
class QualificationBase(BaseModel):
    name: str
    company_name: Optional[str] = None
    level: Optional[str] = None
    expiry_date: Optional[date] = None
    file_url: Optional[str] = None

class QualificationCreate(QualificationBase):
    pass

class QualificationUpdate(BaseModel):
    name: Optional[str] = None
    company_name: Optional[str] = None
    level: Optional[str] = None
    expiry_date: Optional[date] = None
    file_url: Optional[str] = None

class QualificationResponse(QualificationBase):
    id: str
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
