import sys
import os

# Add the backend path to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.crud import user as crud_user
from app.schemas.user import UserCreate, TenantCreate

def main():
    db = SessionLocal()
    try:
        # Create an admin tenant
        tenant = crud_user.tenant.get_by_name(db, name="System Admin")
        if not tenant:
            tenant = crud_user.tenant.create(db, obj_in=TenantCreate(name="System Admin"))
            print(f"Created tenant: {tenant.name} (ID: {tenant.id})")
        else:
            print(f"Found existing tenant: {tenant.name} (ID: {tenant.id})")

        # Create the admin user
        user = crud_user.user.get_by_email(db, email="admin")
        if not user:
            user = crud_user.user.create(
                db, 
                obj_in=UserCreate(
                    email="admin", 
                    password="20260610", 
                    tenant_id=tenant.id,
                    role="admin"
                )
            )
            print(f"Created admin user: {user.email} (ID: {user.id})")
        else:
            print("Admin user already exists. Checking password (won't update directly here).")
            # We can update the password if necessary, but assuming creation is sufficient
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
