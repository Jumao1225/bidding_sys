from langchain_core.tools import tool
import json

from app.services.rag_service import rag_service
from app.services.metadata.qualification_service import qualification_service
from app.services.metadata.financial_service import financial_service
from app.services.metadata.timeline_service import timeline_service
from app.services.metadata.engineering_service import engineering_service
from app.services.metadata.evaluation_service import evaluation_service
from app.services.routing_service import routing_service

def _extract_and_format(service, document_id: str, search_keywords: str, section_title: str = None, context_mode: str = "window") -> str:
    """内部通用辅助方法：执行RAG并提取元数据"""
    try:
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access
        
        if not validate_document_access(document_id):
            return f"拒绝访问：您无权提取文档 {document_id} 的信息。"
            
        # 兜底补全逻辑：如果未传入限定章节，调用路由引擎进行动态意图识别
        if not section_title:
            emit_agent_log("info", "检测到未传入章节限定，正在启动 Routing 智能决策引擎...")
            decision = routing_service.analyze_intent_and_route(document_id, search_keywords)
            if decision.is_global_search:
                emit_agent_log("info", "Routing 引擎决策为【全局搜索】，不限制特定章节。")
                section_title = None
            elif decision.target_chapters:
                section_title = decision.target_chapters
                emit_agent_log("info", f"Routing 引擎决策为【局部锁定】，目标章节: {section_title}")
                
        log_msg = f"调用工具: 正在使用 '{search_keywords}' (模式: {context_mode}) 执行 RAG 检索..."
        if section_title:
            log_msg = f"调用工具: 正在限定章节 {section_title} 中使用 '{search_keywords}' (模式: {context_mode}) 执行 RAG 检索..."
        emit_agent_log("tool_call", log_msg)
        
        # 1. 精细化 RAG 检索 (使用分词多路召回与指定的 context_mode)
        # top_k 设为 5，平衡上下文大小与检索召回率
        context = rag_service.search_bidding_document(
            document_id=document_id,
            query=search_keywords,
            section_title=section_title,
            top_k=5,
            context_mode=context_mode,
            query_mode="split"
        )
        
        emit_agent_log("info", f"检索完成，开始进行大模型 {service.__class__.__name__} 结构化提取...")
        # 2. 专项领域提取与自动落盘
        metadata_obj = service.extract_metadata(context, document_id)
        
        emit_agent_log("success", f"✅ {service.__class__.__name__} 提取并落盘成功！")
        # 3. 格式化输出供大模型读取
        if hasattr(metadata_obj, "model_dump"):
            return json.dumps(metadata_obj.model_dump(), indent=2, ensure_ascii=False)
        else:
            return json.dumps(metadata_obj.dict(), indent=2, ensure_ascii=False)
            
    except Exception as e:
        emit_agent_log("error", f"❌ 执行提取时发生错误: {str(e)}")
        return f"执行提取时发生错误: {str(e)}"

@tool
def extract_qualification_info(document_id: str, search_keywords: str = "资质要求 特定资格要求 营业执照 失信被执行 证书 执业资格 历史业绩 同类项目 废标项 否决投标", section_title: str = None) -> str:
    """
    【资格合规提取工具】
    当你需要评估投标是否满足特定行业资质、特种许可证、核心人员证书或历史业绩门槛时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带资质相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道资质要求在哪个具体章节（如"投标人须知"），请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(qualification_service, document_id, search_keywords, section_title)

@tool
def extract_financial_info(document_id: str, search_keywords: str = "最高限价 预算 投标保证金 履约保证金 付款方式 支付比例", section_title: str = None) -> str:
    """
    【财务资金提取工具】
    当你需要了解项目的最高限价(红线)、预算、各类保证金金额/比例，或多阶段付款节点时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带财务相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道财务要求在哪个具体章节，请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(financial_service, document_id, search_keywords, section_title)

@tool
def extract_timeline_info(document_id: str, search_keywords: str = "项目编号 投标截止时间 开标时间 答疑截止 工期 交付时间 标书份数", section_title: str = None) -> str:
    """
    【商务时限提取工具】
    当你需要获取项目的唯一标识编号、时间排期（如开标时间、答疑死线）或要求的工期及标书装订份数时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带时限相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道时限要求在哪个具体章节，请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(timeline_service, document_id, search_keywords, section_title)

@tool
def extract_engineering_info(document_id: str, search_keywords: str = "主要设备 规格参数 特殊工况 现场施工难点 注意事项", section_title: str = None) -> str:
    """
    【技术工况提取工具】
    当你需要分析工程量清单中的核心设备数量，或排查现场施工是否具有特殊高危工况（如跨河、带电、高空）时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带施工相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道技术清单在哪个具体章节（如"项目需求"），请填入以缩小检索范围，防止幻觉
    """
    return _extract_and_format(engineering_service, document_id, search_keywords, section_title, context_mode="chapter")

@tool
def extract_evaluation_info(document_id: str, search_keywords: str = "评标办法 评分权重 商务分 技术分 质保期 售后响应 违约金 扣罚", section_title: str = None) -> str:
    """
    【评价与罚则提取工具】
    当你需要了解评标的打分权重分布，或者需要分析硬性的售后要求和违约罚金条款时，调用此工具。
    参数:
      - document_id: 必须提供，当前处理的招标文档ID
      - search_keywords: 默认自带评标罚则相关关键词，你可以根据需要补充
      - section_title: 可选，如果你知道评标要求在哪个具体章节（如"评标办法"），请填入以缩小检索范围，防止幻觉
    """
    try:
        import json
        from app.worker.tasks import emit_agent_log
        from app.agents.tools.security import validate_document_access
        
        if not validate_document_access(document_id):
            return f"拒绝访问：您无权提取文档 {document_id} 的评标与罚则信息。"
            
        if not section_title:
            emit_agent_log("info", "检测到未传入章节限定，正在启动 Routing 智能决策引擎进行导航...")
            # 仅针对“评标”部分进行意图识别，剥离罚则关键词，确保能够精确锁定评标章节
            decision = routing_service.analyze_intent_and_route(document_id, "评标办法 评分标准 商务分 技术分 价格分 权重")
            if decision.is_global_search:
                emit_agent_log("info", "Routing 引擎决策评标部分为【全局搜索】。")
                section_title = None
            elif decision.target_chapters:
                section_title = decision.target_chapters
                emit_agent_log("info", f"Routing 引擎决策评标部分锁定目标章节: {section_title}")
                
        emit_agent_log("tool_call", f"调用工具: 启动【评价与罚则】双路合并检索 (章节限定: {section_title})...")
        
        # 1. 检索评标部分 (受 section_title 限制)
        context_eval = rag_service.search_bidding_document(
            document_id=document_id,
            query="评标办法 评分权重 商务分 技术分 价格分",
            section_title=section_title,
            top_k=5,
            context_mode="window",
            query_mode="split"
        )
        
        # 2. 检索罚则部分 (不受 section_title 限制，强制全局搜索)
        context_penalty = rag_service.search_bidding_document(
            document_id=document_id,
            query="质保期 售后响应 违约金 扣罚 验收",
            section_title=None, 
            top_k=5,
            context_mode="window",
            query_mode="split"
        )
        
        combined_context = f"【评标标准相关上下文】\n{context_eval}\n\n================\n\n【合同售后及违约罚则相关上下文】\n{context_penalty}"
        
        emit_agent_log("info", "多路检索完成，开始进行大模型 EvaluationService 结构化提取...")
        metadata_obj = evaluation_service.extract_metadata(combined_context, document_id)
        
        emit_agent_log("success", "✅ EvaluationService (评标+罚则) 提取并落盘成功！")
        
        if hasattr(metadata_obj, "model_dump"):
            return json.dumps(metadata_obj.model_dump(), indent=2, ensure_ascii=False)
        else:
            return json.dumps(metadata_obj.dict(), indent=2, ensure_ascii=False)
            
    except Exception as e:
        emit_agent_log("error", f"❌ 执行评价提取时发生错误: {str(e)}")
        return f"执行提取时发生错误: {str(e)}"

# 统一暴露供 LangGraph Agent 绑定的工具集合
METADATA_TOOLS = [
    extract_qualification_info,
    extract_financial_info,
    extract_timeline_info,
    extract_engineering_info,
    extract_evaluation_info,
]
