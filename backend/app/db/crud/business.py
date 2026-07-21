from sqlalchemy.orm import Session
from app.db.models.business import MarketPriceReference

class CRUDBusiness:
    def get_all_price_references(self, db: Session, tenant_id: str):
        """获取当前租户下的所有市场价格参考"""
        return db.query(MarketPriceReference).filter(
            MarketPriceReference.tenant_id == tenant_id
        ).all()

business_crud = CRUDBusiness()
