from sqlalchemy.orm import Session
from app.db.models.business import CompanyQualification
from app.schemas.qualification import QualificationCreate, QualificationUpdate
from typing import List, Optional

class CRUDQualification:
    def get_qualifications(self, db: Session, tenant_id: str, skip: int = 0, limit: int = 100) -> List[CompanyQualification]:
        return db.query(CompanyQualification).filter(
            CompanyQualification.tenant_id == tenant_id
        ).order_by(CompanyQualification.created_at.desc()).offset(skip).limit(limit).all()

    def get_qualification_by_id(self, db: Session, qual_id: str, tenant_id: str) -> Optional[CompanyQualification]:
        return db.query(CompanyQualification).filter(
            CompanyQualification.id == qual_id,
            CompanyQualification.tenant_id == tenant_id
        ).first()

    def create_qualification(self, db: Session, obj_in: QualificationCreate, tenant_id: str, user_id: str) -> CompanyQualification:
        db_obj = CompanyQualification(
            tenant_id=tenant_id,
            user_id=user_id,
            name=obj_in.name,
            company_name=obj_in.company_name,
            level=obj_in.level,
            expiry_date=obj_in.expiry_date,
            file_url=obj_in.file_url
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update_qualification(self, db: Session, db_obj: CompanyQualification, obj_in: QualificationUpdate) -> CompanyQualification:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def delete_qualification(self, db: Session, db_obj: CompanyQualification):
        db.delete(db_obj)
        db.commit()

qualification_crud = CRUDQualification()
