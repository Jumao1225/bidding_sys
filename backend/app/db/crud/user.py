from typing import Optional, List
from sqlalchemy.orm import Session
from app.db.models.user import User, Tenant
from app.schemas.user import UserCreate, UserUpdate, TenantCreate, TenantUpdate
from app.core.security import get_password_hash

class CRUDTenant:
    def get(self, db: Session, id: str) -> Optional[Tenant]:
        return db.query(Tenant).filter(Tenant.id == id).first()

    def get_by_name(self, db: Session, name: str) -> Optional[Tenant]:
        return db.query(Tenant).filter(Tenant.name == name).first()

    def create(self, db: Session, obj_in: TenantCreate) -> Tenant:
        db_obj = Tenant(
            name=obj_in.name,
            domain=obj_in.domain,
            is_active=obj_in.is_active
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100) -> List[Tenant]:
        return db.query(Tenant).offset(skip).limit(limit).all()

    def update(self, db: Session, *, db_obj: Tenant, obj_in: TenantUpdate) -> Tenant:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field in update_data:
            setattr(db_obj, field, update_data[field])
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

class CRUDUser:
    def get(self, db: Session, id: str) -> Optional[User]:
        return db.query(User).filter(User.id == id).first()

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        return db.query(User).filter(User.email == email).first()

    def create(self, db: Session, obj_in: UserCreate) -> User:
        db_obj = User(
            email=obj_in.email,
            hashed_password=get_password_hash(obj_in.password),
            full_name=obj_in.full_name,
            role=obj_in.role,
            is_active=obj_in.is_active,
            tenant_id=obj_in.tenant_id
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100, tenant_id: Optional[str] = None) -> List[User]:
        query = db.query(User)
        if tenant_id:
            query = query.filter(User.tenant_id == tenant_id)
        return query.offset(skip).limit(limit).all()

    def update(self, db: Session, *, db_obj: User, obj_in: UserUpdate) -> User:
        update_data = obj_in.model_dump(exclude_unset=True)
        if "password" in update_data and update_data["password"]:
            update_data["hashed_password"] = get_password_hash(update_data["password"])
            del update_data["password"]
            
        for field in update_data:
            setattr(db_obj, field, update_data[field])
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

tenant = CRUDTenant()
user = CRUDUser()
