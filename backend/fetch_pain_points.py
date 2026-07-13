import sys
import os
import json

sys.path.insert(0, os.path.abspath('.'))

from app.db.session import SessionLocal
from app.db.models.project import Document

db = SessionLocal()
try:
    doc = db.query(Document).filter(Document.parse_status == 'completed').order_by(Document.created_at.desc()).first()
    if doc and doc.parsed_metadata:
        pain_points = doc.parsed_metadata.get('pain_points', [])
        print("====== 提取的痛点工况 (pain_points) ======")
        print(json.dumps(pain_points, ensure_ascii=False, indent=2))
        print("===========================================")
    else:
        print("No parsed_metadata found")
finally:
    db.close()
