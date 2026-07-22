import pytest
from pydantic import BaseModel, Field
from app.services.llm_service import LLMService

class SampleSchema(BaseModel):
    title: str = Field(..., description="标题")
    count: int = Field(1, description="数量")

def test_root_key_unwrapping(monkeypatch):
    """验证智能根节点解包逻辑 (Root Key Unwrap)"""
    service = LLMService()
    
    # 模拟大模型返回带有外层包名的 JSON 字典 (例如 {"SampleSchema": {"title": "测试项目", "count": 5}})
    fake_wrapped_dict = {
        "SampleSchema": {
            "title": "测试项目",
            "count": 5
        }
    }
    
    monkeypatch.setattr(service, "generate_structured_json", lambda prompt, temperature=0.1: fake_wrapped_dict)
    monkeypatch.setattr(service, "is_configured", True)
    
    result = service.generate_structured_output("dummy prompt", SampleSchema)
    assert result.title == "测试项目"
    assert result.count == 5

def test_single_key_unwrapping(monkeypatch):
    """验证单个外层 Key 自动解包逻辑"""
    service = LLMService()
    
    fake_single_key_dict = {
        "result": {
            "title": "单节点测试",
            "count": 10
        }
    }
    
    monkeypatch.setattr(service, "generate_structured_json", lambda prompt, temperature=0.1: fake_single_key_dict)
    monkeypatch.setattr(service, "is_configured", True)
    
    result = service.generate_structured_output("dummy prompt", SampleSchema)
    assert result.title == "单节点测试"
    assert result.count == 10
