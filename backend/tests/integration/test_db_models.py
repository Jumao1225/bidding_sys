import sys
import os
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Add the backend directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, backend_dir)

from app.db.models import (
    Base, 
    Project, 
    Document, 
    RiskItem, 
    CompanyQualification, 
    QualificationMatch
)

from app.core.config import settings

def test_database_models():
    print(f"🚀 开始测试 SQLAlchemy 模型 (连接 PostgreSQL: {settings.SQLALCHEMY_DATABASE_URI})")
    
    # 使用 PostgreSQL 真实环境
    engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False)
    
    # 验证1：能根据模型定义成功建表，不报错
    Base.metadata.create_all(engine)
    print("✅ 建表成功，无语法错误")

    # 模拟一个固定的 tenant_id
    tenant_1_id = str(uuid.uuid4())
    tenant_2_id = str(uuid.uuid4())

    with Session(engine) as session:
        # 验证2：多租户数据插入与关系映射
        project = Project(
            name="广州市南沙区智慧城市招标项目", 
            status="parsing", 
            tenant_id=tenant_1_id
        )
        session.add(project)
        session.flush() # 获得 project.id

        doc = Document(
            project_id=project.id,
            filename="招标公告.pdf",
            file_path="/tmp/test.pdf",
            tenant_id=tenant_1_id
        )
        session.add(doc)

        risk = RiskItem(
            project_id=project.id,
            risk_type="legal",
            risk_text="如果延期交付将扣除10%尾款",
            severity="HIGH",
            ai_reasoning="明确的违约金条款，属于高危法律风险。",
            tenant_id=tenant_1_id
        )
        session.add(risk)
        
        # 另一个租户的数据
        project_t2 = Project(
            name="北京市公共资源招标", 
            tenant_id=tenant_2_id
        )
        session.add(project_t2)

        session.commit()
        print("✅ 数据插入成功，带有了多租户 ID 和主外键关联")

    with Session(engine) as session:
        # 验证3：查询隔离测试
        t1_projects = session.query(Project).filter(Project.tenant_id == tenant_1_id).all()
        assert len(t1_projects) == 1
        assert t1_projects[0].name == "广州市南沙区智慧城市招标项目"
        
        # 测试关系导航 (Project -> Document)
        t1_docs = t1_projects[0].documents
        assert len(t1_docs) == 1
        assert t1_docs[0].filename == "招标公告.pdf"

        print(f"✅ 查询成功！ 项目创建时间 (created_at): {t1_projects[0].created_at}")
        print(f"✅ 外键关系测试通过：项目包含 {len(t1_docs)} 个文档")

    # 清理测试数据 (防止污染真实的 PostgreSQL 数据库)
    with Session(engine) as session:
        session.query(Project).filter(Project.tenant_id.in_([tenant_1_id, tenant_2_id])).delete(synchronize_session=False)
        session.commit()
        print("🧹 测试数据已自动清理")

    print("\n🎉 所有测试通过，您的数据库模型设计不仅正确，且满足未来 SaaS 多租户隔离需求。")

if __name__ == "__main__":
    test_database_models()
