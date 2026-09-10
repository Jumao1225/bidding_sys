from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.text_normalizer import normalize_markup_text
from .engineering_helpers import (
    GroupingMode,
    _normalize_source_cell,
    is_valid_engineering_section_name,
    normalize_engineering_section_name,
)

logger = logging.getLogger(__name__)

class EquipmentItem(BaseModel):
    """设备/软件/材料清单明细（支持生成技术偏离表与多级精细化 BOM 成本核算）"""
    # 禁止模型返回未定义字段，避免字段名写错后被静默丢弃。
    model_config = ConfigDict(extra="forbid")

    item_code: Optional[str] = Field(None, description="招标文件工程量清单表格【第一列序号】中的原始编码（如'(一)'、'1'、'1.1'、'1.2'等，必须 100% 原样摘录；点号编码只有在表格同时明确展示成套组成关系时才作为层级线索）")
    item_name: str = Field(..., description="设备/软件/材料/元器件名称")
    specifications: Optional[str] = Field(None, description="规格型号或详细技术参数要求")
    quantity: Optional[float] = Field(None, description="项目总采购数量或工程量，纯数字。对于设备/材料表示物理采购数量，对于施工/服务项目表示原文工程量或服务次数。若为多级嵌套子项，必须严格按照穿透连乘公式计算：顶层数量 * 各层级单套定额！若原文仅给出计价单位而未写明具体数量，必须输出 null！绝对禁止脑补填 1！")
    unit: Optional[str] = Field(None, description="物理/计价单位（如：平方米、块、台、套、面、组、只、人月）")
    brand_requirements: Optional[str] = Field(None, description="品牌或产地要求（如：'进口原装'、'指定某品牌/某品牌或同等及以上品牌'、'国产自主可控'）")
    key_parameters: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件明确要求的核心技术指标/关键星号(*)参数"
    )
    parent_item: Optional[str] = Field(None, description="真实 BOM 成套设备/总成的直接父级名称；纯 BOQ 分部、专业分项和材料分类不得填写")
    root_item: Optional[str] = Field(None, description="真实 BOM 父子关系中的顶层主要标的物名称；纯 BOQ 分类行及其下平级明细填 null")
    tree_level: Optional[int] = Field(1, description="真实 BOM 层级深度；纯 BOQ 分类及平级计价明细统一为 1；不能仅按点号数量推断")
    per_set_quantity: Optional[float] = Field(None, description="真实成套父项内部的单套定额；普通工程量清单或无法确认组成关系的行填 null")
    part_name: Optional[str] = Field(None, description="表内 BOQ 一级分部/报价部分名称；仅用于分类，不是 BOM 父项")
    group_path: list[str] = Field(default_factory=list, description="表内 BOQ 分组路径，从一级分部到当前明细的分类名称；仅用于分类展示，不参与成本父子汇总")
    section_name: Optional[str] = Field(None, description="当前清单行明确所属的区域/分标段/分项工程/子系统名称；必须来自当前表格或其前置标题，原文未划分时为 null")
    section_evidence: Optional[str] = Field(None, description="支持 section_name 的原文短标题或表内分区文字，必须逐字摘录当前上下文；无法确认时为 null")
    source_table_index: Optional[int] = Field(
        None,
        description="后端依据原文顺序写入的来源表格索引，仅用于保持不同表格的边界，不由模型推断",
    )
    grouping_mode: GroupingMode = Field(
        default="none",
        description="后端依据当前原始表格结构写入的主分组模式：external、internal 或 none",
    )

    @field_validator("item_name", "specifications", "brand_requirements", "part_name", mode="before")
    @classmethod
    def normalize_markup_fields(cls, value: object) -> object:
        """在工程元数据落库前统一清理模型输出的展示标记。"""
        return normalize_markup_text(value)

    @field_validator("group_path", mode="before")
    @classmethod
    def normalize_group_path_fields(cls, value: object) -> list[str]:
        """清理表内分组路径中的实体和公式标记。"""
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        return [normalized for item in values if (normalized := normalize_markup_text(item))]

    @field_validator("section_name", mode="before")
    @classmethod
    def validate_section_name(cls, value: object) -> Optional[str]:
        """校验模型返回的所属分项字段，无法确认时统一置空。"""
        if value is None:
            return None
        if not isinstance(value, str):
            logger.warning(
                "[EngineeringService] section_name 类型无效，已置空：类型=%s",
                type(value).__name__,
            )
            return None

        normalized_value = normalize_engineering_section_name(normalize_markup_text(value))
        if not is_valid_engineering_section_name(normalized_value):
            logger.warning(
                "[EngineeringService] section_name 未通过通用字段校验，已置空：值=%s",
                value,
            )
            return None
        return normalized_value

    @field_validator("section_evidence", mode="before")
    @classmethod
    def validate_section_evidence(cls, value: object) -> Optional[str]:
        """清理分区证据字段，避免把整段上下文写入结构化结果。"""
        if value is None:
            return None
        if not isinstance(value, str):
            logger.warning(
                "[EngineeringService] section_evidence 类型无效，已置空：类型=%s",
                type(value).__name__,
            )
            return None
        normalized_value = re.sub(r"\s+", " ", normalize_markup_text(value)).strip()
        if not normalized_value or len(normalized_value) > 160:
            logger.warning(
                "[EngineeringService] section_evidence 长度无效，已置空：长度=%d",
                len(normalized_value),
            )
            return None
        return normalized_value


def _equipment_item_identity(item: EquipmentItem) -> tuple[object, ...]:
    """生成有可靠原始编码的重试结果去重键。"""
    return (
        item.source_table_index,
        _normalize_source_cell(item.item_code),
        _normalize_source_cell(item.item_name),
        _normalize_source_cell(item.specifications),
        _normalize_source_cell(item.unit),
        item.quantity,
    )


def _merge_equipment_item_metadata(
    current: EquipmentItem,
    candidate: EquipmentItem,
) -> None:
    """合并同一来源行的补充字段，避免重试结果覆盖已有有效信息。"""
    optional_fields = (
        "brand_requirements",
        "parent_item",
        "root_item",
        "section_name",
        "section_evidence",
        "part_name",
    )
    for field_name in optional_fields:
        current_value = getattr(current, field_name)
        candidate_value = getattr(candidate, field_name)
        if not current_value and candidate_value:
            setattr(current, field_name, candidate_value)

    if current.tree_level == 1 and candidate.tree_level not in (None, 1):
        current.tree_level = candidate.tree_level
    if current.per_set_quantity is None and candidate.per_set_quantity is not None:
        current.per_set_quantity = candidate.per_set_quantity
    if not current.group_path and candidate.group_path:
        current.group_path = list(candidate.group_path)
    # 模型允许关键参数为空，合并前统一转换为空列表，避免 None 被当作可迭代对象。
    current_parameters = list(current.key_parameters or [])
    candidate_parameters = list(candidate.key_parameters or [])
    for parameter in candidate_parameters:
        if parameter not in current_parameters:
            current_parameters.append(parameter)
    current.key_parameters = current_parameters


def _deduplicate_equipment_items(items: list[EquipmentItem]) -> list[EquipmentItem]:
    """按来源字段和 BOM 分支合并重复项，无编码行保持独立。"""
    unique_items: list[EquipmentItem] = []
    item_positions: dict[tuple[object, ...], list[int]] = {}

    def same_bom_branch(current: EquipmentItem, candidate: EquipmentItem) -> bool:
        """仅合并同一根项、同一直接父项下的重复节点。"""
        for field_name in ("root_item", "parent_item"):
            current_value = _normalize_source_cell(getattr(current, field_name))
            candidate_value = _normalize_source_cell(getattr(candidate, field_name))
            if current_value and candidate_value and current_value != candidate_value:
                return False
        current_level = current.tree_level or 1
        candidate_level = candidate.tree_level or 1
        if current_level > 1 and candidate_level > 1 and current_level != candidate_level:
            return False
        return True

    for item in items:
        # 没有原始编码时无法证明两行来自同一来源行，不能用相同内容代替行身份。
        # 这类清单中出现名称、规格、单位和数量完全相同的并列项是合法情况，必须全部保留。
        if not _normalize_source_cell(item.item_code):
            unique_items.append(item)
            continue
        identity = _equipment_item_identity(item)
        compatible_position = next(
            (
                position
                for position in item_positions.get(identity, [])
                if same_bom_branch(unique_items[position], item)
            ),
            None,
        )
        if compatible_position is None:
            item_positions.setdefault(identity, []).append(len(unique_items))
            unique_items.append(item)
            continue
        _merge_equipment_item_metadata(unique_items[compatible_position], item)
    return unique_items


class TechValidationRequirement(BaseModel):
    """技术验证、样品与演示要求（一票否决/高分项）"""
    # 严格限制结构化输出字段，便于及时发现模型输出协议漂移。
    model_config = ConfigDict(extra="forbid")

    sample_required: Optional[bool] = Field(False, description="开标现场是否需要提供物理样品/样机")
    sample_description: Optional[str] = Field(None, description="样品/样机送达与封样要求")
    poc_demo_required: Optional[bool] = Field(False, description="是否需要现场 POC 演示或软件系统功能答辩")
    test_report_requirements: Optional[list[str]] = Field(
        default_factory=list, 
        description="要求的第三方检测/测试报告明细（如：['须具备某种第三方认证机构出具的检测报告']）"
    )

class EngineeringSchema(BaseModel):
    # 顶层字段必须严格匹配 EngineeringSchema，禁止错误字段名被忽略后变成默认空数组。
    model_config = ConfigDict(extra="forbid")

    # --- 1. 主要标的物与设备清单 (生成《技术偏离表》与精细化 BOM) ---
    main_equipment_list: list[EquipmentItem] = Field(
        default_factory=list, 
        description="设备、材料以及有明确计价依据的施工/服务工程量清单明细"
    )

    # --- 2. 施工工况与技术实施难点 (检索工艺知识库) ---
    special_working_conditions: Optional[list[str]] = Field(
        default_factory=list, 
        description="特殊/高难度施工/实施工况（如：['高空/跨区域布线', '不停机业务迁移', '夜间施工']）"
    )
    site_environment_constraints: Optional[str] = Field(
        None, 
        description="现场环境与施工限制说明"
    )

    # --- 3. 规范、标准与技术依据 ---
    mandatory_standards: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件要求的强制性国家/行业/技术标准"
    )

    # --- 4. 技术验证、样品与检测报告 ---
    tech_validation: Optional[TechValidationRequirement] = Field(
        None, 
        description="样品送样、现场 POC 答辩演示及第三方权威检测报告要求"
    )

    # --- 5. 安全防护与文明施工要求 ---
    safety_and_env_requirements: Optional[list[str]] = Field(
        default_factory=list,
        description="安全生产、文明施工及环保特别约束"
    )

    # --- 推导过程 ---
    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")


