from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

import json

def custom_json_serializer(obj):
    return json.dumps(obj, ensure_ascii=False)

# 直接使用配置中的 PostgreSQL URI
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI, 
    # pool_pre_ping=True 可以在每次从连接池获取连接时测试连通性，防止断连报错
    pool_pre_ping=True,
    # ---------------- 数据库连接池配置 ----------------
    pool_size=settings.DB_POOL_SIZE,           # 连接池基础大小 (常驻连接数)
    max_overflow=settings.DB_MAX_OVERFLOW,     # 突发流量时，允许额外创建的最大连接数
    pool_recycle=3600,                         # 定期回收连接 (防止数据库服务端主动断开长时间闲置的连接)
    pool_timeout=30,         # 获取连接时的最大等待时间(秒)
    json_serializer=custom_json_serializer     # 禁用 ASCII 编码，让数据库里直接存中文而不是 \uXXXX
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
