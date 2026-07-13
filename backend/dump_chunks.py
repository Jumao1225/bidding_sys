import sys, os
sys.path.insert(0, os.path.abspath('.'))
from app.db.session import SessionLocal
from app.db.models.project import DocChunk

db = SessionLocal()
chunks = db.query(DocChunk).order_by(DocChunk.id.asc()).all()
res = []
for i, c in enumerate(chunks):
    title = c.section_title
    length = len(c.content)
    snippet = c.content[:150].replace('\n', ' ')
    res.append(f"[{i}] Title: {title} | Len: {length} | Content: {snippet}")

with open('db_dump2.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(res))
print("Done")
