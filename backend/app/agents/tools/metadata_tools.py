from langchain_core.tools import tool
import json

from app.services.rag_service import rag_service
from app.services.metadata.qualification_service import qualification_service
from app.services.metadata.financial_service import financial_service
from app.services.metadata.timeline_service import timeline_service
from app.services.metadata.engineering_service import engineering_service
from app.services.metadata.evaluation_service import evaluation_service

def _extract_and_format(service, document_id: str, search_keywords: str) -> str:
    """内部通用辅助方法：执行RAG并提取元数据"""
    try:
        from app.worker.tasks import emit_agent_log
        emit_agent_log("tool_call", f"调用工具: 正在使用 '{search_keywords}' 执行 RAG 检索...")
        # 1. 精细化 RAG 检索 (使用分词多路召回与 ±1 局部滑窗)
        context = rag_service.search_bidding_document(
            document_id=document_id,
            query=search_keywords,
            top_k=3,
            context_mode="window",
            query_mode="split"
        )
        
        emit_agent_log("info", f"检索完成，开始进行大模型 {service.__class__.__name__} 结构化提取...")
        # 2. 专项领域提取与自动落盘
        metadata_obj = service.extract_metadata(context, document_id)
        
        emit_agent_log("success", f"✅ {service.__class__.__name__} 提取并落盘成功！")
        # 3. 格式化输出供大模型读取
        # 注意：Pydantic v2 的 model_dump_json 默认 ensure_ascii=True，会将中文序列化为 \uXXXX。
        # 统一改用 json.dumps(model_dump(), ensure_ascii=False) 保证中文原文透传。
        if hasattr(metadata_obj, "model_dump"):
            return json.dumps(metadata_obj.model_dump(), indent=2, ensure_ascii=False)
        else:
            return json.dumps(metadata_obj.dict(), indent=2, ensure_ascii=False)
            
    except Exception as e:
        emit_agent_log("error", f"❌ 执行提取时发生错误: {str(e)}")
        return f"执行提取时发生错误: {str(e)}"

@tool
def extract_qualification_info(document_id: str, search_keywords: str = "资质要求 证书 执业资格 历史业绩 同类项目") -> str:
    """
    【资格合规提取工具】
    当你需要评估投标是否满足特定行业资质、特种许可证、核心人员证书或历史业绩门槛时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带资质相关关键词，你可以根据需要补充
    """
    return _extract_and_format(qualification_service, document_id, search_keywords)

@tool
def extract_financial_info(document_id: str, search_keywords: str = "最高限价 预算 投标保证金 履约保证金 付款方式 支付比例") -> str:
    """
    【财务资金提取工具】
    当你需要了解项目的最高限价(红线)、预算、各类保证金金额/比例，或多阶段付款节点时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带财务相关关键词，你可以根据需要补充
    """
    return _extract_and_format(financial_service, document_id, search_keywords)

@tool
def extract_timeline_info(document_id: str, search_keywords: str = "项目编号 投标截止时间 开标时间 答疑截止 工期 标书份数") -> str:
    """
    【商务时限提取工具】
    当你需要获取项目的唯一标识编号、时间排期（如开标时间、答疑死线）或要求的工期及标书装订份数时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带时限相关关键词，你可以根据需要补充
    """
    return _extract_and_format(timeline_service, document_id, search_keywords)

@tool
def extract_engineering_info(document_id: str, search_keywords: str = "主要设备 规格参数 特殊工况 现场施工难点 注意事项") -> str:
    """
    【技术工况提取工具】
    当你需要分析工程量清单中的核心设备数量，或排查现场施工是否具有特殊高危工况（如跨河、带电、高空）时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带施工相关关键词，你可以根据需要补充
    """
    return _extract_and_format(engineering_service, document_id, search_keywords)

@tool
def extract_evaluation_info(document_id: str, search_keywords: str = "评标办法 评分权重 商务分 技术分 质保期 售后响应 违约金 扣罚") -> str:
    """
    【评价与罚则提取工具】
    当你需要了解评标的打分权重分布，或者需要分析硬性的售后要求和违约罚金条款时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带评标罚则相关关键词，你可以根据需要补充
    """
    return _extract_and_format(evaluation_service, document_id, search_keywords)

# 统一暴露供 LangGraph Agent 绑定的工具集合
METADATA_TOOLS = [
    extract_qualification_info,
    extract_financial_info,
    extract_timeline_info,
    extract_engineering_info,
    extract_evaluation_info,
]
