from typing import Optional
from pydantic import BaseModel, ConfigDict


class CompanyProfileBase(BaseModel):
    company_name: str = "四川石楠建设工程有限公司"
    legal_representative: Optional[str] = "张三"
    authorized_delegate: Optional[str] = "李四"
    credit_code: Optional[str] = "91510000MA6X12345X"
    registered_address: Optional[str] = "四川省成都市高新区天府大道北段128号"
    contact_phone: Optional[str] = "028-85123456"
    email: Optional[str] = "bidding@shinan-construction.com"
    bank_name: Optional[str] = "中国工商银行股份有限公司成都高新支行"
    bank_account: Optional[str] = "4402 2410 1910 0123 456"


class CompanyProfileUpdate(BaseModel):
    company_name: Optional[str] = None
    legal_representative: Optional[str] = None
    authorized_delegate: Optional[str] = None
    credit_code: Optional[str] = None
    registered_address: Optional[str] = None
    contact_phone: Optional[str] = None
    email: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None


class CompanyProfileResponse(CompanyProfileBase):
    id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
