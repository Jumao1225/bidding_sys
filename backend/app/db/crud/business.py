from sqlalchemy.orm import Session
from app.db.models.business import MarketPriceReference
from app.schemas.business import PriceReferenceCreate, PriceReferenceUpdate
import uuid

class CRUDBusiness:
    def get_all_price_references(self, db: Session, tenant_id: str):
        """获取当前租户下的所有市场价格参考（绝对私有租户隔离）"""
        return db.query(MarketPriceReference).filter(
            MarketPriceReference.tenant_id == tenant_id
        ).all()

    def get_price_reference(self, db: Session, id: str, tenant_id: str):
        """获取当前租户下的指定市场价格参考"""
        return db.query(MarketPriceReference).filter(
            MarketPriceReference.id == id,
            MarketPriceReference.tenant_id == tenant_id
        ).first()



    def create_price_reference(self, db: Session, obj_in: PriceReferenceCreate, tenant_id: str, user_id: str = None):
        db_obj = MarketPriceReference(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            **obj_in.dict()
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj


    def update_price_reference(self, db: Session, db_obj: MarketPriceReference, obj_in: PriceReferenceUpdate):
        update_data = obj_in.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete_price_reference(self, db: Session, id: str, tenant_id: str):
        db_obj = self.get_price_reference(db, id, tenant_id)
        if db_obj:
            db.delete(db_obj)
            db.commit()
            return True
        return False

business_crud = CRUDBusiness()
