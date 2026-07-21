import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.session import SessionLocal
from app.db.models.project import Document

def main():
    db = SessionLocal()
    try:
        # Assuming Ming's user id:
        ming_user_id = 'fa58e2fe-2388-4ec9-95bf-e69f908bf7b1'
        
        # Update all documents to have the correct tenant_id based on their user
        from app.db.models.user import User
        users = db.query(User).all()
        user_tenant_map = {u.id: u.tenant_id for u in users}
        
        docs = db.query(Document).all()
        updated = 0
        for doc in docs:
            if doc.user_id in user_tenant_map:
                correct_tenant = user_tenant_map[doc.user_id]
                if doc.tenant_id != correct_tenant:
                    print(f"Updating document {doc.id} tenant_id from '{doc.tenant_id}' to '{correct_tenant}'")
                    doc.tenant_id = correct_tenant
                    updated += 1
            
        db.commit()
        print(f"Migration complete! Updated {updated} documents.")
    finally:
        db.close()

if __name__ == '__main__':
    main()
