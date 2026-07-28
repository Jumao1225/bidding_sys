"""
TableAgent - 表格智能识别与动态列语义映射装配引擎 (table_agent.py)

功能：
彻底废除死板的 if-else 硬编码表格列对齐逻辑。
当在 Word 原生 OpenXML 中检测到表格 <w:tbl> 时：
1. 自动提取表头物理列名与上下文章节；
2. 调度 TableAgent LLM 自主思考：分析表格业务类型 (BOM报价清单/资格证书/人员表/偏离响应表)，并输出每一列的语义映射配置 (column_mapping)；
3. 通用矩阵填充引擎根据 Agent 决定的列映射配置，零硬编码动态将数据填充到 Word 单元格中。
"""

import re
import threading
from typing import Dict, Any, List, Optional, Literal
from loguru import logger
from pydantic import BaseModel, Field

from app.services.llm_service import llm_service


# ============================================================
# 1. 结构化表格决策 Schema
# ============================================================

class ColumnMapping(BaseModel):
    """单个列的语义映射规则"""
    col_index: int = Field(..., description="列索引 (从 0 开始)")
    header_name: str = Field(..., description="原文表头列名 (如 '生产厂家', '规格型号')")
    field_key: str = Field(
        ...,
        description=(
            "映射的数据字段 KEY:\n"
            "- seq: 序号 (1, 2, 3...)\n"
            "- name: 标的物/设备/项目/证书/人员名称\n"
            "- spec: 规格型号/品牌/等级/要求说明\n"
            "- brand: 品牌\n"
            "- manufacturer: 生产厂家/发行机构\n"
            "- unit: 单位 (台/套/项/块)\n"
            "- qty: 数量\n"
            "- price: 单价\n"
            "- subtotal: 总价/小计\n"
            "- remark: 备注/符合性说明\n"
            "- status: 响应状态 (如 '完全响应')\n"
            "- expiry: 有效期/截止时间\n"
            "- role: 职务/拟任岗位\n"
            "- unknown: 未知或保持原样"
        )
    )
    default_val: Optional[str] = Field(None, description="当数据缺失时的默认填充文本 (如 '满足招标文件要求', '知名品牌', '符合规范')")


class TableMappingDecision(BaseModel):
    """表格整体识别与填充决策"""
    table_type: Literal[
        "pricing_bom",          # BOM 分项报价/采购清单/设备表
        "opening_summary",      # 开标一览表
        "qualification_certs",  # 资格证明/资质证书表
        "clause_compliance",    # 实质性条款/偏离响应表
        "team_personnel",       # 项目团队/人员配备表
        "unknown"               # 保持原生模版框架
    ] = Field(..., description="表格业务类型分类")
    table_reason: str = Field(..., description="识别该表格类型的一句话理由")
    column_mappings: List[ColumnMapping] = Field(default_factory=list, description="列语义映射配置列表")


# 内存中缓存已识别过的表格表头决策 (按 (header_tuple, chapter) 隔离，线程安全，避免重复 LLM 调用)
_TABLE_DECISION_CACHE: Dict[tuple, TableMappingDecision] = {}
_TABLE_DECISION_CACHE_LOCK = threading.Lock()


def analyze_table_structure_and_map(
    header_texts: List[str],
    current_section: str,
    available_data_sources: Optional[List[str]] = None
) -> TableMappingDecision:
    """
    调度 TableAgent 分析表格表头列名与上下文章节，自主决策表格类型与各列的字段映射。

    参数:
      - header_texts: Word 原生表格第一行提取出的所有表头列名列表
      - current_section: 表格所在的当前章节标题 (如 "五、投标配置及分项报价表")
      - available_data_sources: 可选，当前系统中可用的数据源类型

    返回:
      TableMappingDecision 包含表格类型与列映射列表
    """
    if not header_texts:
        return TableMappingDecision(
            table_type="unknown",
            table_reason="表头列表为空",
            column_mappings=[]
        )

    # 1. 尝试命中内存缓存 (0ms 极速返回，线程安全)
    clean_headers = tuple(re.sub(r'\s+', '', h) for h in header_texts)
    cache_key = (clean_headers, current_section)
    with _TABLE_DECISION_CACHE_LOCK:
        if cache_key in _TABLE_DECISION_CACHE:
            logger.info(f"⚡ [TableAgent] 命中表格决策缓存 (章节: {current_section}, 列数: {len(header_texts)})")
            return _TABLE_DECISION_CACHE[cache_key]

    prompt = f"""
你是一位招投标 Word 表格智能分析专家 (TableAgent)。

【任务指令】
请根据输入的 Word 表格第一行【表头列名列表】以及表格所在的【章节标题】，
自主分析该表格属于哪种业务表格类型，并为每一列选择最精准的数据字段映射 (field_key)。

【输入信息】:
- 表格所在章节: "{current_section}"
- 表头列名列表 (共 {len(header_texts)} 列): {header_texts}

【表格类型 (table_type) 判定规则】:
1. pricing_bom: 包含 '名称'、'规格'、'单价'、'总价'、'数量'、'品牌'、'厂家'、'单位' 等报价要素；
2. opening_summary: 处于开标一览表章节，主要填写大写总价、小写总价、工期；
3. qualification_certs: 包含 '证书名称'、'资质等级'、'有效期'、'证书编号' 等资质要素；
4. clause_compliance: 包含 '招标文件要求'、'响应情况'、'偏离说明'、'符合性' 等条款要素；
5. team_personnel: 包含 '人员'、'姓名'、'岗位'、'职务'、'身份证'、'职称' 等团队要素；
6. unknown: 其它无法匹配的复杂表格。

【列映射字段 (field_key) 可选值】:
- seq: 序号列 (1, 2, 3...)
- name: 标的物名称 / 设备名称 / 证书名称 / 人员姓名
- spec: 规格型号 / 品牌 / 资质等级 / 要求说明
- brand: 品牌
- manufacturer: 生产厂家 / 颁发机构
- unit: 单位 (台/套/项/块)
- qty: 数量
- price: 单价
- subtotal: 总价 / 小计
- remark: 备注 / 响应说明
- status: 响应状态 (如 '完全响应')
- expiry: 有效期 / 到期日
- role: 职务 / 拟任岗位 / 角色
- unknown: 未知或无关列

请输出符合 JSON Schema 的映射决策。对于缺少数据源的列 (如生产厂家/备注)，可以在 default_val 中给出合规的默认填充词 (如 '知名品牌/符合要求' 或 '满足招标文件要求')。
"""

    try:
        logger.info(f"🧠 [TableAgent] 正在分析原生 Word 表格结构 (章节: '{current_section}', 表头: {header_texts})...")
        
        decision: TableMappingDecision = llm_service.generate_structured_output(
            prompt=prompt,
            schema_cls=TableMappingDecision,
            temperature=0.0
        )

        with _TABLE_DECISION_CACHE_LOCK:
            _TABLE_DECISION_CACHE[cache_key] = decision
        logger.info(f"✅ [TableAgent] 表格分析完成: 类型='{decision.table_type}', 原因='{decision.table_reason}', 列映射数={len(decision.column_mappings)}")
        return decision

    except Exception as e:
        logger.error(f"TableAgent 分析表格失败: {e}")
        # 兜底返回 unknown
        return TableMappingDecision(
            table_type="unknown",
            table_reason=f"分析发生异常: {str(e)}",
            column_mappings=[]
        )
