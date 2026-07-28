"""
章节子 Agent 专属工具集 (chapter_agent_tools.py)

@deprecated: 自 2026-07-27 起，ChapterAgent 工具集 (方案 A) 已被 bid_db_tools.py (统一 DB 直查工具) 替代。
本文件保留以备参考，请勿在新代码中引用。

功能：
提供给各章节 ReAct 子 Agent 独立调用的共享工具库。
子 Agent 可通过这些工具查询招标原文、项目元数据、资质中心 DB、成本分析以及提交生成的章节内容。
"""

import json
import threading
from typing import Dict, Any, List, Optional
from loguru import logger
from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models.project import Document
from app.db.models.metadata import (
    QualificationMetadata, FinancialMetadata, TimelineMetadata,
    EngineeringMetadata, EvaluationMetadata
)
from app.services.rag_service import rag_service
from app.agents.tools.writer_tools import (
    get_company_qualifications_tool,
    retrieve_chapter_clause_requirements
)

# 内存运行态章节结果存储池 (按 document_id 隔离，线程安全)
_RUNNING_CHAPTER_RESULTS: Dict[str, Dict[str, Any]] = {}
_RUNNING_CHAPTER_RESULTS_LOCK = threading.Lock()


def get_document_chapter_results(document_id: str) -> Dict[str, Any]:
    """获取指定文档已提交的所有章节结果（线程安全）"""
    with _RUNNING_CHAPTER_RESULTS_LOCK:
        return dict(_RUNNING_CHAPTER_RESULTS.get(document_id, {}))


def clear_document_chapter_results(document_id: str) -> None:
    """清理指定文档的章节结果缓存（线程安全）"""
    with _RUNNING_CHAPTER_RESULTS_LOCK:
        if document_id in _RUNNING_CHAPTER_RESULTS:
            del _RUNNING_CHAPTER_RESULTS[document_id]


@tool
def search_chapter_requirements(document_id: str, chapter_title: str, query: str = "") -> str:
    """
    【章节原文与限制条款检索工具】
    从招标文档中检索特定章节的具体填写要求、格式说明、限制条款与特定约束。
    当你需要了解甲方对某章节的具体要求时，请调用此工具。

    参数:
      - document_id: 当前处理的招标文档 ID
      - chapter_title: 章节标题 (如 "投标函", "开标一览表", "法定代表人授权书")
      - query: 可选，具体的补充查询词
    """
    search_query = f"{chapter_title} {query} 填写说明 格式要求 注 注意事项".strip()
    return retrieve_chapter_clause_requirements(document_id, search_query)


@tool
def query_metadata(document_id: str, metadata_type: str) -> str:
    """
    【项目基础元数据查询工具】
    查询已从招标文件中提取的五大核心元数据。

    参数:
      - document_id: 当前处理的招标文档 ID
      - metadata_type: 元数据类型，可选值:
        * timeline: 项目名称、招标编号、投标截止时间、工期等
        * financial: 保证金、限价、付款节点等
        * engineering: 主要设备清单、特殊工况、技术标准等
        * qualification: 强制性资质门槛、人员要求、业绩要求等
        * evaluation: 评分权重、硬性服务要求等
    """
    db: Session = SessionLocal()
    try:
        meta_type = metadata_type.lower().strip()
        model_map = {
            "timeline": TimelineMetadata,
            "financial": FinancialMetadata,
            "engineering": EngineeringMetadata,
            "qualification": QualificationMetadata,
            "evaluation": EvaluationMetadata,
        }

        target_model = model_map.get(meta_type)
        if not target_model:
            return f"无效的元数据类型 '{metadata_type}'。可选: timeline, financial, engineering, qualification, evaluation"

        record = db.query(target_model).filter(target_model.document_id == document_id).first()
        if not record:
            return f"未找到该文档的 {metadata_type} 元数据记录。"

        result_dict = {k: v for k, v in record.__dict__.items() if not k.startswith('_')}
        return json.dumps(result_dict, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.error(f"查询元数据异常 [{metadata_type}]: {e}")
        return f"查询元数据发生错误: {str(e)}"
    finally:
        db.close()


@tool
def query_company_qualifications(tenant_id: str = None) -> str:
    """
    【我方资质中心数据库查询工具】
    查询资质中心数据库中我方公司已上传并解析的所有有效资质证书、等级、有效期等信息。

    参数:
      - tenant_id: 可选，租户 ID。不传则自动使用当前会话租户。
    """
    quals = get_company_qualifications_tool(tenant_id)
    if not quals:
        return "资质中心数据库中暂无记录。"
    return json.dumps(quals, ensure_ascii=False, indent=2)


@tool
def query_cost_estimation(document_id: str) -> str:
    """
    【成本测算与报价数据查询工具】
    获取前序成本分析 Agent 算出的 BOM 采购清单、指导单价、分项小计和总报价。

    参数:
      - document_id: 当前处理的招标文档 ID
    """
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc or not doc.parsed_metadata:
            return "数据库中暂无该项目的成本测算数据。"

        cost_analysis = doc.parsed_metadata.get("cost_analysis")
        if not cost_analysis:
            return "该项目尚未进行成本测算分析。"

        return json.dumps(cost_analysis, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"查询成本测算数据异常: {e}")
        return f"查询成本数据发生错误: {str(e)}"
    finally:
        db.close()


@tool
def query_strategy_analysis(document_id: str, analysis_type: str) -> str:
    """
    【前序策略分析结果查询工具】
    查询资质匹配度评估结果或风险与偏离扫描结果。

    参数:
      - document_id: 当前处理的招标文档 ID
      - analysis_type: 分析类型，可选值:
        * qualifications_analysis: 资质评估与匹配分
        * risks_analysis: 风险条款与偏离扫描清单
    """
    db: Session = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc or not doc.parsed_metadata:
            return "数据库中暂无该项目的策略分析数据。"

        target_type = analysis_type.lower().strip()
        analysis_data = doc.parsed_metadata.get(target_type)
        if not analysis_data:
            return f"暂无 {analysis_type} 的分析结果。"

        return json.dumps(analysis_data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"查询策略分析数据异常: {e}")
        return f"查询策略数据发生错误: {str(e)}"
    finally:
        db.close()


@tool
def write_chapter_content(
    document_id: str,
    chapter_title: str,
    mapping_hint: str,
    filled_content: str,
    table_rows_json: str = "[]"
) -> str:
    """
    【章节撰写结果提交工具】
    当子 Agent 完成该章节的分析、填空或表格装配后，必须调用此工具将结果写入全局存储。

    参数:
      - document_id: 招标文档 ID
      - chapter_title: 章节标题 (如 "一、投标函")
      - mapping_hint: 映射标签 (如 "bid_letter", "qualification", "pricing")
      - filled_content: 撰写或填空完成后的正文内容 (Markdown 格式)
      - table_rows_json: 可选，生成的表格行数据 JSON 字符串数组/对象
    """
    try:
        try:
            table_rows = json.loads(table_rows_json) if isinstance(table_rows_json, str) else table_rows_json
        except Exception:
            table_rows = []

        with _RUNNING_CHAPTER_RESULTS_LOCK:
            if document_id not in _RUNNING_CHAPTER_RESULTS:
                _RUNNING_CHAPTER_RESULTS[document_id] = {}

            task_key = f"task_{mapping_hint}_{chapter_title}"
            _RUNNING_CHAPTER_RESULTS[document_id][task_key] = {
            "chapter_title": chapter_title,
            "mapping_hint": mapping_hint,
            "filled_content": filled_content,
            "table_rows": table_rows,
            "status": "success"
        }

        logger.info(f"✅ 章节 [{chapter_title}] 结果已成功落盘 (document_id={document_id})")
        return f"章节 [{chapter_title}] 内容提交成功！"
    except Exception as e:
        logger.error(f"提交章节 [{chapter_title}] 结果失败: {e}")
        return f"提交章节结果失败: {str(e)}"
