import sys
import os
import uuid
import pytest

# Add the backend directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, backend_dir)

from app.db.models.base import Base
from app.db.models import metadata 
from app.db.session import engine, SessionLocal
from app.services.metadata.financial_service import financial_service

def test_financial_extraction_integration():
    """测试大模型提取和数据库入库的全流程 (Integration Test)"""
    print("正在同步数据库表结构...")
    Base.metadata.create_all(bind=engine)

    doc_id = str(uuid.uuid4())
    # 我们随便生成一个 tenant_id 因为基类可能需要
    tenant_id = str(uuid.uuid4())
    
    fake_context = """
    第三章 评标办法与商务条款
    1. 资金情况：本项目预算金额为人民币 2,500,000.00 元。
    2. 最高投标限价：所有投标人的报价不得超过人民币 2,450,000.00 元，超过此限价的投标将被否决。
    3. 投标保证金：金额为 45,000 元，需在开标前汇入公共资源交易中心指定账户。
    4. 履约保证金：中标人需在合同签订前缴纳中标金额 10% 的履约保证金。
    5. 付款方式及进度：
       (1) 预付款：合同签订且收到等额收据后7个工作日内支付合同总价的 20%。
       (2) 进度款：所有设备到场并安装调试完成后，支付至合同总价的 70%。
       (3) 验收款：项目并网验收合格且移交后，支付至合同总价的 95%。
       (4) 质保金：剩余 5% 作为质量保证金，缺陷责任期（2年）满后无息返还。
    """
    
    print(f"\n开始测试 FinancialService 专项提取... \n模拟 Document ID: {doc_id}")
    
    # 模拟给 service 设置 tenant_id 的能力（如果存在该依赖）
    # 大部分数据是依靠 BaseMetadataService 的 _save_to_db，
    # 但模型继承了 TenantBase，所以它需要有个默认或传入的 tenant_id，
    # 若模型定义里未默认赋值，入库时可能报错 nullable=False。
    # 这里我们只验证提取和服务过程，所以即使入库因为缺失外键抛错也足以证明结构化成功。
    try:
        result = financial_service.extract_metadata(fake_context, doc_id)
        
        print("\n=== 提取成功，以下为返回的结构化 Pydantic 数据 ===")
        print(f"【思维链推理】: {result.reasoning}")
        print("-" * 50)
        
        if hasattr(result, "model_dump_json"):
            print(result.model_dump_json(indent=2)) 
        else:
            print(result.json(indent=2, ensure_ascii=False)) 
            
        print("\n=== 数据已自动落盘至 PostgreSQL! ===")
        
        # 验证提取的正确性
        assert result.max_price_limit is not None, "应当成功提取到最高限价"
        assert result.bid_bond_ratio is not None, "应当成功提取到投标保证金"
        
    except Exception as e:
        print(f"\n测试过程出现异常: {e}")
        # 如果是 tenant_id 外键报错，可视为LLM提取通过但多租户外键检查拦截
        raise e

if __name__ == "__main__":
    test_financial_extraction_integration()
