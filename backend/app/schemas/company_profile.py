from typing import Optional
from pydantic import BaseModel, ConfigDict


class CompanyProfileBase(BaseModel):
    company_name: Optional[str] = None
    legal_representative: Optional[str] = None
    authorized_delegate: Optional[str] = None
    credit_code: Optional[str] = None
    registered_address: Optional[str] = None
    contact_phone: Optional[str] = None
    email: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account: Optional[str] = None


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
