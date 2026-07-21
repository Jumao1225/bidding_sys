import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.routing_service import routing_service

def test_analyze_intent_and_route():
    """
    测试动态意图路由服务
    使用真实的数据库中的 document_id 进行测试。
    在执行前，请确保此 document_id 在数据库中存在并且包含解析好的 table_of_contents。
    """
    # 这个 document_id 由之前找出的真实 ID 替换，或者在运行测试时动态查询。
    document_id = "a47b6872-9600-4b30-abcb-4bf3692ec9ae"
    
    # 意图 1：财务类
    query_financial = "最高限价 预算 投标保证金"
    chapters_financial = routing_service.analyze_intent_and_route(document_id, query_financial)
    print(f"意图: {query_financial} -> 路由章节: {chapters_financial}")
    assert isinstance(chapters_financial, list)
    
    # 意图 2：技术/工况类
    query_engineering = "是否有夜间施工、跨河施工等要求？"
    chapters_engineering = routing_service.analyze_intent_and_route(document_id, query_engineering)
    print(f"意图: {query_engineering} -> 路由章节: {chapters_engineering}")
    assert isinstance(chapters_engineering, list)

    # 意图 3：评标罚则类
    query_eval = "评分标准里商务分和技术分各占多少？"
    chapters_eval = routing_service.analyze_intent_and_route(document_id, query_eval)
    print(f"意图: {query_eval} -> 路由章节: {chapters_eval}")
    assert isinstance(chapters_eval, list)

if __name__ == "__main__":
    test_analyze_intent_and_route()
