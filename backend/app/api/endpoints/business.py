from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.db.crud.business import business_crud
from app.schemas.business import PriceReferenceCreate, PriceReferenceUpdate, PriceReferenceResponse
from app.schemas.response.common import ResponseModel

from typing import List, Optional
from app.api import deps
from app.db.models.user import User

router = APIRouter()

def resolve_tenant_id(
    x_tenant_id: str = Header("default-tenant"),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
) -> str:
    if current_user and current_user.tenant_id:
        return current_user.tenant_id
    return x_tenant_id or "default-tenant"

@router.get("/price-references", response_model=ResponseModel)
def get_price_references(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id)
):
    items = business_crud.get_all_price_references(db, tenant_id)
    data = [PriceReferenceResponse.model_validate(item) for item in items]
    return ResponseModel(code=200, message="Success", data=data)

@router.post("/price-references", response_model=ResponseModel)
def create_price_reference(
    item_in: PriceReferenceCreate,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id),
    current_user: Optional[User] = Depends(deps.get_current_user_optional)
):
    user_id = current_user.id if current_user else None
    item = business_crud.create_price_reference(db, item_in, tenant_id, user_id=user_id)
    return ResponseModel(code=200, message="Success", data=PriceReferenceResponse.model_validate(item))

@router.put("/price-references/{item_id}", response_model=ResponseModel)
def update_price_reference(
    item_id: str,
    item_in: PriceReferenceUpdate,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id)
):
    db_item = business_crud.get_price_reference(db, item_id, tenant_id)
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    item = business_crud.update_price_reference(db, db_item, item_in)
    return ResponseModel(code=200, message="Success", data=PriceReferenceResponse.model_validate(item))

@router.delete("/price-references/{item_id}", response_model=ResponseModel)
def delete_price_reference(
    item_id: str,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(resolve_tenant_id)
):
    success = business_crud.delete_price_reference(db, item_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found")
    return ResponseModel(code=200, message="Success", data={"id": item_id})


