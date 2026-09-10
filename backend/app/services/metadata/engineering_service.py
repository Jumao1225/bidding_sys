from __future__ import annotations

import logging
import json
import os
import re
from collections import Counter
from typing import Literal, Optional
from pydantic import BaseModel

from .base import BaseMetadataService
from .engineering_helpers import (
    _build_semantic_engineering_chunks,
    _build_table_scoped_engineering_chunks,
    _collect_source_measurement_names,
    _deduplicate_equipment_items,
    _extract_section_evidence_from_heading,
    _get_engineering_chunk_retry_depth,
    _get_engineering_context_limit,
    _inherit_external_table_context,
    _is_engineering_length_limit_error,
    _normalize_source_cell,
    _schema_to_log_json,
    _split_engineering_chunk_for_retry,
    build_engineering_table_section_hints,
    extract_engineering_section_name_from_heading,
    is_valid_engineering_section_name,
    normalize_engineering_section_name,
    resolve_engineering_table_grouping_mode,
    validate_engineering_section_evidence,
)
from .engineering_helpers import *  # noqa: F401,F403，兼容历史辅助函数导入路径
from .engineering_models import (
    EquipmentItem,
    EngineeringSchema,
    TechValidationRequirement,
)
from .engineering_source_mixin import EngineeringSourceRepairMixin
from .engineering_hierarchy_mixin import EngineeringHierarchyMixin
from app.db.models.metadata import EngineeringMetadata
from app.services.llm_service import llm_service
from app.utils.text_normalizer import normalize_markup_text

logger = logging.getLogger(__name__)

# 分组模式是解析结果的技术元数据，不承载任何项目名称或固定业务值。
GroupingMode = Literal["external", "internal", "none"]


def _is_source_bom_postprocessing_enabled() -> bool:
    """读取源表 BOM 校验与恢复开关，默认关闭以完全采用模型层级结果。"""
    return os.getenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }


class EngineeringService(EngineeringSourceRepairMixin, EngineeringHierarchyMixin, BaseMetadataService):
    def __init__(self):
        # 保持工程元数据服务原有的数据库模型绑定行为。
        super().__init__(db_model_cls=EngineeringMetadata)

    def _save_to_db(self, document_id: str, pydantic_obj: BaseModel) -> None:
        """防止一次异常的空提取覆盖数据库中已有的有效工程清单。"""
        equipment_list = getattr(pydantic_obj, "main_equipment_list", None)
        if equipment_list == [] and document_id:
            from app.db.session import SessionLocal

            db = SessionLocal()
            try:
                existing_record = (
                    db.query(EngineeringMetadata)
                    .filter(EngineeringMetadata.document_id == document_id)
                    .first()
                )
                if existing_record and existing_record.main_equipment_list:
                    logger.warning(
                        "[EngineeringService] 本次提取结果为空，保留数据库已有工程清单：文档ID=%s，已有明细=%d",
                        document_id,
                        len(existing_record.main_equipment_list),
                    )
                    return
            finally:
                db.close()

        super()._save_to_db(document_id, pydantic_obj)


    def extract_metadata(
        self,
        context: str,
        document_id: str,
        tenant_id: Optional[str] = None,
    ) -> EngineeringSchema:
        from app.utils.table_utils import extract_equipment_tables_and_context
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import re
        from app.core.context import current_tenant_id

        # 在线程池中显式传递租户，避免 ContextVar 未继承时回退到 global 配置。
        effective_tenant_id = tenant_id or current_tenant_id.get()

        # 仅按表格语法提取上下文，保留检索结果中的完整表格，不在送模前按业务规则过滤清单行。
        clean_context = extract_equipment_tables_and_context(context)

        system_prompt = r"""
你是资深的【项目总工与工程造价清单专家】。你的任务是从传入的技术图纸说明、工程量清单、《项目需求》、《技术规格书》和《货物需求一览表》中，提取出**设备、材料以及有明确计价依据的施工/服务 BOQ 行项目**。

【零容忍数字幻觉（最高指令）】
系统对参数极为严格，你提取的任何设备数量、技术指标必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。
- **关于数量 `quantity`**：若标书原文中仅给出了计价单位（如“平方米”、“米”），但未标注具体物理采购数量，`quantity` 必须输出为 null，绝对禁止脑补填 1！

【提取指南】
1. **完整工程量清单行项目提取（最高优先级）**：
   - 当前任务目标是逐行完整提取 BOM/BOQ 表格中的设备、材料、安装、施工、运输、调试、检测和其他服务项目，不仅提取核心设备或已经明确数量的项目。只要原文行具有独立的项目名称、组成部件名称、规格描述、计量单位、数量/工程量或明确的成套组成语义，就必须输出一个 `EquipmentItem`。
   - **逐行核对要求（必须执行）**：从表头下一行开始，按照原文表格顺序逐行检查，不能因为前面已经识别出主要设备、当前行缺数量、当前行没有独立编码或当前行位于 `rowspan`/`colspan` 跨行结构中就跳过。模型返回结果必须覆盖当前表格中所有可识别的独立清单行；只有空行、表头、纯分组标题、纯备注和不代表独立项目的连续说明可以不输出。
   - **数量与计价字段规则**：数量/工程量明确写出时原样填入；原文未写出时 `quantity` 必须为 null，不能脑补。缺少数量或单位不等于该行无效，若该行是独立设备、材料、服务或明确的 BOM 组成项，仍必须保留，其缺失字段分别填 null。
   - 对于表格中的施工/服务行，即使单位是“项”“批”“次”“日”“人月”，或名称看起来像施工工序，也必须保留；数量没有填写时只将 `quantity` 设为 null，不得因此跳过该行。
   - 表格中的纯分组标题/分类行（不代表设备、材料、服务或任何层级结构）不是清单项，不得输出为 `EquipmentItem`。但是，原文明确展示内部组成关系的成套设备父项、子系统节点和组成部件必须保留，即使其中部分行没有独立数量或单位。
   - **表内 BOQ 分组与 BOM 父项必须分开**：如果某行的编码是中文大序号（如“一”“二”“三”）或点号目录（如“2.1”“3.1.1”），该行没有明确数量/单位，且后续存在以它为前缀的递进编码子行，则将其名称写入当前明细的 `part_name`/`group_path` 作为分类路径；这类报价分部、专业分项和材料分类行不得填入 `parent_item`、`root_item`。如果为了还原原表目录而输出该分类行，只能作为无计量结构行，不能把其下明细挂成 BOM 子项。只有原文明确出现“每套包含/含有/配置/组成”等成套证据时，才允许建立真实 BOM 父节点。
   - **明确排除非项目叙述**：安全生产制度、文明施工要求、岗位职责、人员分工、作业票要求、风险提示、违章分类、施工方法、管理流程、培训要求、验收说明、处罚条款、评标规则、合规承诺和一般技术规范，均不得作为 BOM/BOQ 项目；只有当原文明确把它们列为独立工程量、报价或服务项目时才保留。
   - 只有表头、空白行、纯注释、纯说明、合计/小计行（且不代表实际工作内容）可以不作为清单项输出。禁止把“在某区域内使用某种作业票”“工作负责人不在现场”“满足某安全要求”等句子提取为项目。
   - 设备、材料、施工和服务项目统一使用同一套 `EquipmentItem` 结构：项目名称或工作内容填入 `item_name`，原文技术要求/施工内容/服务范围填入 `specifications`，原文数量填入 `quantity`，原文单位填入 `unit`。数量必须是纯数字；原文没有数量时必须为 `null`。
   - **完整保留表格上下文**：必须结合当前表格的全部列、跨行表头、合并单元格内容、表格前后的章节标题和技术说明判断每一行含义；不得只依据“设备名称”列筛选，也不得因为某行名称与设备无关而跳过。
   - **【主要标的物聚焦与宏观大类归口原则（最高指令）】**：
     - 清单提取应紧紧围绕招标文件中的《货物需求一览表》、《工程量清单》、《采购清单》、《报价清单》和核心设备材料表；其他章节只作为技术上下文，不能仅凭其中的要求、制度或说明生成 BOM 项目。
       - **关于 `section_name`（当前清单表的外层所属分区）**：
       - `section_name` 只表示当前清单表所属的外层区域、标段、部分或分项名称；同一张表中的所有清单行原则上必须保持一致。
       - 表格标题中的“项目需求清单/报价清单”等包装文字不是展示名称；若其括号中包含明确的外层部分名称，可以提取括号内语义名称。
       - 每条 `EquipmentItem` 都必须返回 `section_name` 和 `section_evidence`；证据必须逐字摘录当前表格前的外层标题，且必须包含 `section_name`。禁止把表内“某设备分类”“某材料分类”等内部分类写入 `section_name`。
       - 表内报价分部、专业分项、材料分类及其递进目录属于 BOQ 分类信息，必须通过 `part_name`、`group_path` 表达，不属于 `section_name`，也不自动形成 `parent_item`。只有原文存在明确成套组成证据时，设备总成及其递进明细才通过 `parent_item`、`root_item`、`tree_level` 表达。
       - 大模型可以先筛选清单行并返回候选分区供后端核验，但最终 `section_name` 必须归一到当前表格的外层分区，不得使用更具体的表内分组覆盖外层分区。
   - **【真实 BOM 层级与普通 BOQ 编号严格区分（最高优先级）】**：
     - 不能仅因点号编号、行号连续、名称相似或前一行刚好出现就建立父子关系。普通工程量清单中同一分组下的连续编号行应保持平级，例如抽象形式 `A.1`、`A.2`、`A.3` 的多个计价行统一输出 `parent_item=null`、`root_item=null`、`tree_level=1`、`per_set_quantity=null`。
     - 若表格出现“根项数量 + 每套包含/含有/配置”等成套语义，并且通过视觉缩进、合并单元格、独立物料清单结构或递进编码展示组成关系，则这些结构证据共同确认真实 BOM。此时必须保留根项、成套分项和所有递进子项，不能把子项合并进父项规格。
     - 真实 BOM 的抽象结构可能是：`(二) 成套系统（数量 Q）` → `1 总成（每套包含）` → `1.1 子件`、`1.2 子件`；或 `2 功能单元` → `2.1 元件`。其中 `1`、`2` 是根项的直接子级，`1.1`、`1.2` 是 `1` 的直接子级，`2.1` 是 `2` 的直接子级，不能把所有点号行都挂到根项，也不能把兄弟项串成链。
     - 无数量/单位但被真实 BOM 子项引用、且有成套组成证据的结构父级（例如“某功能单元”）必须保留为父节点；仅承担报价目录作用的分组标题不得被当成成本父项。
     - 表内 BOQ 分类标题只用于填充 `part_name`/`group_path`，其下有数量或单位的明细保持平级，`parent_item`、`root_item` 填 null，`tree_level` 填 1；分类标题如被输出为无计量结构行，也必须保持无子项挂载，避免分类标题参与成本汇总。
     - 表格中带有独立分组编码、且同行存在单位或数量的行，不属于纯分组标题，必须作为有效工程量清单行保留；即使该行没有“每套包含/含有/配置/组成”等字样，也不能因为名称像分类而省略。没有计量数据但有独立编码、且原文明确用它界定后续子项范围的结构行，也必须保留，数量和单位填 null；只有没有后续项目或仅为说明文字的纯标题才可以不输出。是否把它与后续普通整数编码明细建立 BOM 父子关系，仍须依据原文的成套、视觉或表格边界证据判断。
     - 只有在上述结构证据成立时，才填写 `parent_item`、`root_item`、`tree_level` 和 `per_set_quantity`；仅有编号层级时按扁平清单处理。
   - **【任意深度多级嵌套 BOM 设备树（Multi-Level BOM 任意 N 级递归穿透提取，最高指令）】**：
     - 当工程量清单表格中出现包含任意多层嵌套缩进、层级递进编号（如顶层复合系统 $\\rightarrow$ 二级总成 $\\rightarrow$ 三级组件 $\\rightarrow$ 四级模块 $\\rightarrow$ 五级元器件等任意 $N$ 级树状结构）时，必须严格按以下【通用递归归纳法则】逐级完整拆解：
     
     - **【零文本合并红线（通用递归约束）】**：
       - **凡是在表格中带有独立层级编码（如点号递进序号、缩进编号）、独立计量单位或独立单台定额的任何部件/元器件，无论嵌套层级有多深（Level 1 至 Level N），必须 100% 逐行拆解输出为独立的 `EquipmentItem` 记录！**
       - **绝对禁止将第 $L+1$ 级或更深层的子部件合并压缩成一段概括性文字塞进第 $L$ 级父节点的 `specifications` 描述中！**

     - **【通用 N 级递归字段赋值与连乘规则（数学归纳法）】**：
       1. **层级深度判定 (`tree_level`)**：
          - 设最顶层主要标的物为 Level 1（`tree_level = 1`）；
          - 依据真实的父项组成语义、视觉缩进、合并单元格或独立 BOM 结构确定当前节点层级；序号点号数量只能作为辅助线索，不能单独决定 `tree_level`。
       2. **直接父级绑定 (`parent_item`)**：
          - 若 $L = 1$（顶层根节点），`parent_item` 必须为 null；
          - 若 $L \\ge 2$（任意子项/孙项节点），`parent_item` **必须且仅能严格指向其直接所属的上一级（Level $L-1$）父节点的完整名称**。
       3. **顶层根设备绑定 (`root_item`)**：
          - 整个分支树下的所有层级节点（Level 1 至 Level $N$），其 `root_item` **必须全部统一填入该分支最顶层 Level 1 根标的物的名称**。
       4. **单台配置定额 (`per_set_quantity`)**：
          - 若 $L = 1$，`per_set_quantity` 填 null；
          - 若 $L \\ge 2$，`per_set_quantity` **必须准确填入在单台直接父级（Level $L-1$ 设备）中的物理配置数量**（纯数字 $q_L$）。
       5. **项目总需求量/工程量递归穿透连乘换算 (`quantity`)**：
          - 若 $L = 1$，`quantity` 填该顶层标的物、施工项目或服务项目在整个项目中的原文总数量/工程量（纯数字 $Q_1$）；
          - 若 $L \ge 2$，当前子项在整个项目中的总需求量或工程量 **必须通过从顶层至当前层级的全链路单套定额递归连乘公式准确换算**：
            $$\text{quantity} = Q_1 \times q_2 \times q_3 \times \dots \times q_L$$
            （即：顶层总套数 $Q_1$ 乘以该分支路径上各级单套定额的乘积）。
       6. **规格与技术参数 (`specifications`)**：
          - 每一个节点（无论处于哪一层级）的 `specifications` **仅摘录其自身的物理型号、尺寸、电气指标与材质参数**，严禁掺杂下级子部件清单文字。
     - 若清单为普通扁平表格，或无法确认真实组成关系，则所有条目的 `parent_item`、`root_item` 和 `per_set_quantity` 统一输出为 null，`tree_level` 统一填 1，`quantity` 为原文物理采购数量/工程量。
   - **【明细表格精确数值优先原则】**：当清单表格中列出的具体型号或精确数量与前言概述文字存在出入时，**一律以明细表格中的精确数值为准**。
   - **关于 `specifications`（规格参数要求）**：**必须 100% 原汁原味完整摘录标书原文中的详细技术参数描述**（包含所有型号参数、材质、尺寸、物理/电气指标等）。
   - **拒绝“详见XXX”废话（最高指令）**：若清单表格中写有“详见技术规格”、“详见项目需求”、“详见第五章”等引用说明，**绝不能直接把“详见XXX”当作规格参数！你必须从后文《技术规格书/项目需求》章节中找到该设备真实的详细规格与技术要求完整摘录填入！**
   - **关于 `key_parameters`**：请从原文中提炼具体的**技术参数指标**（如精确的厚度、材质要求、功率、吞吐量等具有明确物理/化学测量依据的约束），**绝对禁止**提取诸如“使用寿命长”、“防腐防水防火”、“风格协调”之类的假大空废话或主观描述！
   - **极度注意（防止断章取义）**：提取参数时，**必须将该指标生效的【前置条件/测试环境】一并提取**！例如，绝不能只提取“某指标≥某数值”，必须完整提取“在XXX温度、XXX压力、XXX测试条件约束下，该指标≥某数值”。必须将所有带 '*' 号的参数以及带有完整条件的明确技术门槛原汁原味地填入该数组。
2. **特殊工况**：排查“现场踏勘”、“注意事项”。提取特殊的高成本/高风险工况（如“高空作业”、“带电施工”、“特殊环境防护”等）。
3. **技术标准**：提取明确规定的“国家标准”、“行业标准”。这决定了我们的编制依据。
4. **技术验证与样品（死亡雷区）**：重点去《评标办法》或《投标人须知》中寻找“样品”、“检测报告”、“CMA”、“CNAS”、“现场演示(POC)”的字眼，这关乎是否废标。
5. **安全与环保**：提取现场必须遵守的安全红线。

请在 `reasoning` 字段中简要说明你是如何找出这些痛点和核心物资的。
如果上下文中没有任何相关的配置或要求信息，请严格将其输出为 null。绝对不可根据常识盲目瞎编。
"""
        # 识别正文中的所有表格
        html_tables = list(re.finditer(r'<table[\s\S]*?</table>', clean_context, re.IGNORECASE))
        md_tables = list(re.finditer(r'(?:(?:^|\n)\|[^\n]+\|\n(?:\|[-:\s|]+\|\n)(?:\|[^\n]+\|\n?)+)', clean_context, re.MULTILINE))
        all_tables = sorted(html_tables + md_tables, key=lambda x: x.start())
        table_section_titles: list[Optional[str]] = []
        table_section_evidences: list[Optional[str]] = []
        last_table_end = 0
        for table_match in all_tables:
            heading = clean_context[last_table_end:table_match.start()].strip()
            section_title = extract_engineering_section_name_from_heading(heading)
            table_section_titles.append(section_title)
            table_section_evidences.append(
                _extract_section_evidence_from_heading(heading, section_title)
            )
            last_table_end = table_match.end()
        table_grouping_modes: dict[int, GroupingMode] = {
            table_index: resolve_engineering_table_grouping_mode(
                table_section_titles[table_index],
                table_match.group(0),
            )
            for table_index, table_match in enumerate(all_tables)
        }
        _inherit_external_table_context(
            all_tables,
            table_section_titles,
            table_section_evidences,
            table_grouping_modes,
        )
        if table_grouping_modes:
            logger.info(
                "[EngineeringService] 已按原文表格确定主分组模式：表格数=%d，模式=%s",
                len(table_grouping_modes),
                table_grouping_modes,
            )
        table_section_hints = build_engineering_table_section_hints(
            clean_context,
            all_tables,
            table_grouping_modes,
            table_section_titles,
        )
        table_section_hint_text = "\n".join(table_section_hints) or "- 未从表格前置标题确认到分区，请仅依据表内明确分区文字判断"
        context_limit = _get_engineering_context_limit()
        if len(all_tables) > 1:
            # 多表文件无论是否能识别出外层标题，都必须逐表提交，保证模型返回的
            # section_name 和后续层级修复始终带有表格边界。
            chunks, chunk_sections, chunk_table_indexes = _build_table_scoped_engineering_chunks(
                clean_context,
                all_tables,
                context_limit,
                table_grouping_modes,
                table_section_titles,
            )
        else:
            # 单表仍沿用原有拆分策略，表格内部的长表只按完整行拆分。
            chunks, chunk_sections = _build_semantic_engineering_chunks(
                clean_context,
                all_tables,
                context_limit,
                include_internal_group_state=(
                    table_grouping_modes.get(0, "none") != "external"
                ),
            )
            # 单表超长拆分后仍属于同一张原始表，保留表格编号才能执行逐行对账。
            chunk_table_indexes = [0 if all_tables else None] * len(chunks)
        if not chunks:
            chunks = [clean_context]
            chunk_sections = [None]
            chunk_table_indexes = [None]

        logger.info(
            f"🚀 [EngineeringService] 发现 {len(all_tables)} 个原文表格块，"
            f"组装为 {len(chunks)} 个语义上下文分块后交由模型判断清单范围。"
        )

        def process_chunk(
            idx: int,
            chunk_text: str,
            section_title: Optional[str],
            table_index: Optional[int],
            retry_depth: int = 0,
        ) -> tuple[int, list[EngineeringSchema]]:
            grouping_mode = (
                table_grouping_modes.get(table_index, "none")
                if table_index is not None
                else "none"
            )
            chunk_hint_text = (
                table_section_hints[table_index]
                if table_index is not None and table_index < len(table_section_hints)
                else table_section_hint_text
            )
            section_hint = f"""
【所属分项定位证据】
以下索引由当前上下文中每张表格前的原文标题生成，仅用于帮助模型把表格与最近分区对应起来，不得把候选值当作无证据结论：
{chunk_hint_text}
当前分块候选分区：{section_title or '未单独确认'}
请由模型结合对应表格、表内分区文字及其前置标题，逐条决定 `EquipmentItem.section_name`，并逐字返回对应的 `section_evidence`；原文不能确认时两个字段都必须返回 null。
"""
            if grouping_mode == "external":
                grouping_instruction = """
   - 【当前表格为表格外部分区模式】当前表格前置文本已经确定外层分区。所有项目的 `section_name` 统一归属该外层分区；`part_name` 和 `group_path` 必须保持为空，本次任务不处理表内 BOQ 分类。
   - 表格内部的编码、缩进、合并单元格和成套说明只用于识别原始清单行及真实 BOM 父子关系，不得转换成表内分组标签。必须按照表格原始顺序完整提取每一条独立设备、材料、施工/服务项目及有结构证据的 BOM 节点，不得因为缺少数量、单位或独立编码而漏掉有效行。
   - 表格中凡是存在独立编码且同行单位或数量至少有一项明确的行，都是有效清单行，必须保留；这类行即使名称表现为分类汇总，也不能按纯分组标题删除，也不需要额外出现成套关键词才能输出。后续子行是否挂接为 BOM 子项，单独依据原文结构证据判断。
   - 没有单位和数量、但带有独立分组编码且后面确实存在该分组下的连续明细时，应保留为无计量结构节点，数量和单位填 null；它只用于还原原文层级，不参与价格库匹配，不得因为名称像分类而删除。没有后续明细、仅是说明性标题的行才可以省略。
   - 对真实 BOM，继续使用 `parent_item`、`root_item`、`tree_level` 和 `per_set_quantity` 表达直接父子关系；外层 `section_name` 不是 BOM 父项。只有原文存在成套组成、视觉层级、合并单元格或明确结构证据时才建立父子关系，普通并列清单行保持平级。
   - 如果设备名称单元格本身包含“每套包含/每套含有/每套包括/配置”等提示，且该单元格通过 `rowspan` 覆盖后续规格行，则这些后续非空规格行属于该设备的组成子项；不得因为子行没有重复填写序号、设备名称、单位或数量而按平级处理。
   - 对同一组成项连续出现的型号、尺寸、电气参数和性能指标续行，应合并到该组成项的 `specifications`；只有原文明确出现独立部件名称或独立计量依据时，才新建子节点。
"""
            elif grouping_mode == "internal":
                grouping_instruction = """
   - 【当前表格为表格内分组模式】当前表格没有可确认的表格外部分区。表内 BOQ 分组只填写 `part_name` 和 `group_path`，不得写入 `section_name`，也不得自动生成 `parent_item`；只有原文明确存在成套组成证据时，才建立真实 BOM 父子关系。
   - 若上下文标注了“表内分区状态”，仅将其作为当前表格前序行继承的分类记忆；遇到新的同级分组后立即切换。该状态不是新增清单行，也不是 BOM 父项。
"""
            else:
                grouping_instruction = """
   - 【当前表格未确认主分组模式】不要根据表格外文字或表内编号臆造分区；只保留原文有证据的字段。表内分组仅在结构明确时填写分类字段，真实 BOM 父子关系仍需单独依据成套或视觉结构证据判断。
"""
            prompt = f"""
{system_prompt}

【任务约束】
1. 你的任务是根据下面提供的【当前工程清单上下文与技术要求】进行信息抽取。当前分块只包含一张原文清单表及其前置标题，后端没有依据固定项目名称、章节名称或表头关键词预先筛掉表格；请你先判断表格是否属于 BOM/BOQ，再完整逐行提取其中所有可识别的清单项目。{section_hint}
   - 必须同时阅读表格的所有列及跨行、跨列单元格。遇到跨行结构时，只把重复出现的父项单元格视为同一个父项，把后续独立的组成内容逐项识别为子项或该父项的连续规格说明；不能因父项名称被 HTML `rowspan` 重复展示而生成重复父项，也不能因子项缺少独立编码而遗漏。
   - 对于序号和名称通过 `rowspan` 跨多行、规格列逐行列出型号/截面/组成的结构，必须保留序号-名称这一父项本身；将连续规格作为该父项的子项或规格明细处理，不能只把规格字符串当作独立项目，也不能因父项数量为空而丢弃父项。
   - 当表格出现“每套包含/每套含有/每套包括”等组成提示时，提示后的每一条有编码、名称、单位、数量或规格的组成行都必须逐项输出；不能只保留成套设备根项，也不能把组成行压缩进根项 `specifications`。
   - 对 `rowspan` 父项下由分号、冒号或“名称+参数”形式连续列出的组成描述，必须按原文逐段拆分；父项名称只保留设备本体，不能把“每套包含”等提示语并入名称。组成项识别不得依赖预设设备名称词表，无法确认的数量或单位分别填 `null`。
{grouping_instruction}
   - 后端不会根据原始表格另行补造清单项；模型返回的 `main_equipment_list` 必须是当前表格完整提取结果。父子关系、根项、层级和单套定额必须依据当前表格原文证据直接填写，无法确认时填 null 或保持默认平级值。
2. 宁缺毋滥原则：如果当前分块中完全没有提及某个字段的相关信息（找不到），请将该字段值置为 null。绝不允许编造任何信息。
3. **所属分项由模型筛选并提供证据**：`section_name` 只记录当前清单表的外层区域、标段、部分或分项名称。同一张表内的所有清单行原则上使用同一个外层 `section_name`；表内的设备分类、材料分类和专业目录必须通过 `part_name`、`group_path` 表达，不得写入 `section_name`，也不得自动建立 `parent_item`、`root_item`、`tree_level` 父子关系。只有当前清单表没有外层标题、且原文存在明确独立分区时，才允许使用该分区。填写时必须同时返回逐字摘录的 `section_evidence`，证据必须来自当前上下文且包含 `section_name`；不得把合同章节、整句说明、表头包装文字、设备名称、编码或模型自拟名称写入该字段；无法确认时 `section_name` 与 `section_evidence` 都必须为 null。
4. 明确豁免原则：如果上下文中明确写明“无需提供”、“不作要求”，请针对该字符串字段返回 "明确无要求"；如果写明“待定”、“另行通知”，请返回 "待定"。千万不要返回 null。

<当前工程清单上下文与技术要求 (第 {idx + 1}/{len(chunks)} 上下文分块)>
{chunk_text}
</当前工程清单上下文与技术要求>
"""
            # 打印本次请求实际携带的文档上下文，便于核对表格边界和分区提示是否正确。
            logger.info(
                "[EngineeringService] 大模型输入文档上下文（分块 %d/%d）：\n%s%s",
                idx + 1,
                len(chunks),
                section_hint,
                chunk_text,
            )
            try:
                sub_res = llm_service.generate_structured_output(
                    prompt=prompt,
                    schema_cls=EngineeringSchema,
                    temperature=0.1,
                    tenant_id=effective_tenant_id,
                )
            except Exception as e:
                # 长度超限只拆分当前失败分块，保留表格前置标题、原始表头和分组模式。
                if (
                    _is_engineering_length_limit_error(e)
                    and retry_depth < _get_engineering_chunk_retry_depth()
                ):
                    retry_chunks = _split_engineering_chunk_for_retry(
                        chunk_text,
                        grouping_mode,
                    )
                    if retry_chunks:
                        logger.warning(
                            "[EngineeringService] 分块 %d/%d 输出达到长度限制，"
                            "按完整表格行拆分为 %d 个子块后重试（第 %d 层）。",
                            idx + 1,
                            len(chunks),
                            len(retry_chunks),
                            retry_depth + 1,
                        )
                        retry_results: list[EngineeringSchema] = []
                        for retry_chunk in retry_chunks:
                            _, retry_schemas = process_chunk(
                                idx,
                                retry_chunk,
                                section_title,
                                table_index,
                                retry_depth + 1,
                            )
                            retry_results.extend(retry_schemas)
                        if retry_results:
                            return idx, retry_results

                # 保留完整堆栈，避免并发分块失败后只剩下一个无法定位的空结果。
                logger.exception(f"分块 {idx + 1} 提取失败: {e}")
                return idx, []

            item_count = len(sub_res.main_equipment_list or [])
            item_names = [item.item_name for item in sub_res.main_equipment_list[:5]]
            logger.info(
                f"[EngineeringService] 分块 {idx + 1} 结构化结果: "
                f"设备明细={item_count}，所属分项={section_title or '未识别'}，"
                f"示例={item_names}，输入字符数={len(chunk_text)}"
            )
            # # 记录模型未经过后端层级修复前的完整返回，便于确认遗漏发生在模型还是后处理阶段。
            # logger.info(
            #     "[EngineeringService] 大模型返回完整结构化结果（分块 %d/%d）：\n%s",
            #     idx + 1,
            #     len(chunks),
            #     _schema_to_log_json(sub_res),
            # )
            if not item_count:
                # 空结果仍允许参与其它字段汇总，但最终会在落库前统一拦截。
                logger.warning(
                    f"[EngineeringService] 分块 {idx + 1} 未提取到设备明细，"
                    "请检查该分块是否只包含表头、表格行是否被 RAG 截断或模型字段是否错配。"
                )
            return idx, [sub_res]

        # 每个原始分块对应一个结果列表，长度超限重试产生的子块在此保留原顺序。
        chunk_results: list[list[EngineeringSchema]] = [
            [] for _ in chunks
        ]
        with ThreadPoolExecutor(max_workers=min(5, len(chunks))) as executor:
            futures = [
                executor.submit(
                    process_chunk,
                    i,
                    chunk,
                    chunk_sections[i],
                    chunk_table_indexes[i],
                )
                for i, chunk in enumerate(chunks)
            ]
            for future in as_completed(futures):
                c_idx, c_schemas = future.result()
                chunk_results[c_idx] = c_schemas

        # 汇总合并各分块提取的设备清单与各项要求
        merged_equipment_list = []
        special_conditions = []
        mandatory_standards = []
        tech_validation = None
        safety_requirements = []
        reasoning_list = []

        for c_idx, schema_items in enumerate(chunk_results):
            if not schema_items:
                continue
            c_section = chunk_sections[c_idx]
            c_table_index = chunk_table_indexes[c_idx]
            c_section_evidence = (
                table_section_evidences[c_table_index]
                if c_table_index is not None
                and c_table_index < len(table_section_evidences)
                else None
            )
            for schema_item in schema_items:
                chunk_item_names = {
                    item.item_name
                    for item in schema_item.main_equipment_list
                    if item.item_name
                }
                if schema_item.main_equipment_list:
                    for eq in schema_item.main_equipment_list:
                        # 表格边界与主分组模式由后端依据原文写入，避免模型跨表串联或同时生成两套分类。
                        eq.source_table_index = c_table_index
                        eq.grouping_mode = (
                            table_grouping_modes.get(c_table_index, "none")
                            if c_table_index is not None
                            else "none"
                        )
                        # 模型先筛选清单行并返回候选分区；若当前表格已有明确外层标题，
                        # 最终字段统一归一到该外层标题，避免把表内分类误当 section_name。
                        model_section = normalize_engineering_section_name(eq.section_name)
                        if c_section and is_valid_engineering_section_name(c_section):
                            if model_section and model_section != c_section:
                                logger.info(
                                    "[EngineeringService] 模型返回表内分组，已归一为表格外层分区："
                                    f"分块={c_idx + 1}，模型值={model_section}，外层分区={c_section}"
                                )
                            eq.section_name = c_section
                            eq.section_evidence = c_section_evidence or c_section
                            if not c_section_evidence:
                                logger.warning(
                                    "[EngineeringService] 外部分区缺少可回溯的原文标题证据："
                                    "表格索引=%s，分区=%s",
                                    c_table_index,
                                    c_section,
                                )
                        elif model_section and (
                            is_valid_engineering_section_name(model_section)
                            and validate_engineering_section_evidence(
                                eq,
                                chunks[c_idx],
                                known_item_names=chunk_item_names,
                            )
                        ):
                            # 当前表格没有可确认的外层标题时，才保留模型自身核验通过的候选。
                            eq.section_name = model_section
                        else:
                            logger.warning(
                                "[EngineeringService] 当前表格无法确认有效外层分区，section_name 已置空："
                                f"分块={c_idx + 1}，模型值={model_section or '无'}，证据={eq.section_evidence or '无'}"
                            )
                            eq.section_name = None
                            eq.section_evidence = None

                        if eq.grouping_mode == "internal" and not c_section:
                            # 没有表格外置标题时，模型误写的内部分类不得落入 section_name。
                            eq.section_name = None
                            eq.section_evidence = None
                        elif eq.grouping_mode in {"external", "none"}:
                            # 原表没有内部目录时，清理模型可能误填的表内分类字段。
                            eq.part_name = None
                            eq.group_path = []
                            if eq.grouping_mode == "none":
                                # 没有任何可确认分组时，不保留模型自行推断的所属分区。
                                eq.section_name = None
                                eq.section_evidence = None
                    merged_equipment_list.extend(schema_item.main_equipment_list)
                if schema_item.special_working_conditions:
                    for c in schema_item.special_working_conditions:
                        if c not in special_conditions:
                            special_conditions.append(c)
                if schema_item.mandatory_standards:
                    for s in schema_item.mandatory_standards:
                        if s not in mandatory_standards:
                            mandatory_standards.append(s)
                if schema_item.tech_validation and not tech_validation:
                    tech_validation = schema_item.tech_validation
                if schema_item.safety_and_env_requirements:
                    for sf in schema_item.safety_and_env_requirements:
                        if sf not in safety_requirements:
                            safety_requirements.append(sf)
                if schema_item.reasoning:
                    reasoning_list.append(schema_item.reasoning)

        original_equipment_count = len(merged_equipment_list)
        merged_equipment_list = _deduplicate_equipment_items(merged_equipment_list)
        if len(merged_equipment_list) != original_equipment_count:
            logger.warning(
                "[EngineeringService] 已合并重试分块产生的重复清单项：原始结果=%d，去重后=%d，"
                "去重项=%d。",
                original_equipment_count,
                len(merged_equipment_list),
                original_equipment_count - len(merged_equipment_list),
            )

        source_bom_postprocessing_enabled = _is_source_bom_postprocessing_enabled()
        if source_bom_postprocessing_enabled:
            logger.info(
                "[EngineeringService] 已启用源表 BOM 校验与恢复，将对模型层级执行后处理。"
            )
            # 表内 BOQ 分类归一化只作用于 internal 模式，外部分区表保持原有 BOM 父子字段。
            internal_items = [
                item
                for item in merged_equipment_list
                if item.grouping_mode == "internal"
            ]
            if internal_items:
                internal_table_indexes = {
                    item.source_table_index
                    for item in internal_items
                    if item.source_table_index is not None
                }
                normalized_internal_items = self._normalize_model_boq_group_context(
                    internal_items,
                    clean_context,
                    allowed_table_indexes=internal_table_indexes,
                )
                normalized_by_identity = {
                    id(item): item for item in normalized_internal_items
                }
                merged_equipment_list = [
                    normalized_by_identity.get(id(item), item)
                    for item in merged_equipment_list
                ]
                logger.info(
                    "[EngineeringService] 仅对表内分组模式执行 BOQ 分类归一化：明细=%d，表格=%d",
                    len(internal_items),
                    len(internal_table_indexes),
                )
            else:
                logger.info(
                    "[EngineeringService] 当前结果无表内分组模式，保留表格外分区下的原始 BOM 层级。"
                )

            # 外部分区表中的带计量分组父行可能被模型误判为纯分类标题；
            # 依据原始表格边界和后续明细行进行通用恢复，不把这套规则用于表内分组表。
            external_table_indexes = {
                item.source_table_index
                for item in merged_equipment_list
                if item.grouping_mode == "external" and item.source_table_index is not None
            }
            if external_table_indexes:
                item_table_indexes = {
                    id(item): item.source_table_index
                    for item in merged_equipment_list
                    if item.source_table_index is not None
                }
                before_external_boq_category_ids = {
                    id(item) for item in merged_equipment_list
                }
                merged_equipment_list = self._remove_unpriced_external_boq_group_rows_from_source(
                    merged_equipment_list,
                    clean_context,
                    item_table_indexes=item_table_indexes,
                    allowed_table_indexes=external_table_indexes,
                )
                removed_external_boq_category_count = sum(
                    1
                    for item_id in before_external_boq_category_ids
                    if item_id not in {id(item) for item in merged_equipment_list}
                )
                logger.info(
                    "[EngineeringService] 外部分区 BOQ 分类清理完成：限定表格=%d，移除无计量中文分类=%d",
                    len(external_table_indexes),
                    removed_external_boq_category_count,
                )
                before_repair_ids = {id(item) for item in merged_equipment_list}
                merged_equipment_list = self._repair_boq_hierarchy_from_source(
                    merged_equipment_list,
                    clean_context,
                    item_table_indexes=item_table_indexes,
                    allowed_table_indexes=external_table_indexes,
                    table_grouping_modes=table_grouping_modes,
                    preserve_unpriced_structural_nodes=True,
                )
                repaired_count = sum(
                    1 for item in merged_equipment_list if id(item) not in before_repair_ids
                )
                logger.info(
                    "[EngineeringService] 外部分区源表结构校验完成：限定表格=%d，补回计价分组父行=%d",
                    len(external_table_indexes),
                    repaired_count,
                )
                before_structural_restore_ids = {id(item) for item in merged_equipment_list}
                merged_equipment_list = self._restore_missing_structural_nodes_from_source(
                    merged_equipment_list,
                    clean_context,
                    item_table_indexes=item_table_indexes,
                    allowed_table_indexes=external_table_indexes,
                    table_grouping_modes=table_grouping_modes,
                )
                restored_structural_count = sum(
                    1
                    for item in merged_equipment_list
                    if id(item) not in before_structural_restore_ids
                )
                logger.info(
                    "[EngineeringService] 外部分区遗漏结构父项恢复完成：限定表格=%d，补回结构父项=%d",
                    len(external_table_indexes),
                    restored_structural_count,
                )
                before_explicit_bom_restore_ids = {
                    id(item) for item in merged_equipment_list
                }
                merged_equipment_list = self._restore_missing_explicit_bom_rows_from_source(
                    merged_equipment_list,
                    clean_context,
                    item_table_indexes=item_table_indexes,
                    allowed_table_indexes=external_table_indexes,
                    table_grouping_modes=table_grouping_modes,
                )
                restored_explicit_bom_count = sum(
                    1
                    for item in merged_equipment_list
                    if id(item) not in before_explicit_bom_restore_ids
                )
                logger.info(
                    "[EngineeringService] 外部分区明确 BOM 组成恢复完成：限定表格=%d，补回组成行=%d",
                    len(external_table_indexes),
                    restored_explicit_bom_count,
                )

                # 源表恢复可能把模型已返回但尚未精确匹配的节点再次补入；
                # 恢复完成后必须重新按可靠源行键去重，避免同一组成项重复展示。
                before_post_restore_dedup_count = len(merged_equipment_list)
                merged_equipment_list = _deduplicate_equipment_items(
                    merged_equipment_list
                )
                post_restore_dedup_count = (
                    before_post_restore_dedup_count - len(merged_equipment_list)
                )
                if post_restore_dedup_count:
                    logger.warning(
                        "[EngineeringService] 源表 BOM 恢复后合并重复节点："
                        "恢复前=%d，合并后=%d，合并数量=%d",
                        before_post_restore_dedup_count,
                        len(merged_equipment_list),
                        post_restore_dedup_count,
                    )
        else:
            logger.info(
                "[EngineeringService] 已跳过源表 BOM 校验、层级归一化和遗漏恢复，保留模型原始层级。"
            )

        if source_bom_postprocessing_enabled:
            source_measurement_names = Counter(_collect_source_measurement_names(clean_context))
            model_measurement_names = Counter(
                _normalize_source_cell(item.item_name)
                for item in merged_equipment_list
                if item.item_name
                and (
                    item.quantity is not None
                    or bool(str(item.unit or "").strip())
                )
            )
            missing_measurement_names = list((source_measurement_names - model_measurement_names).elements())
            if missing_measurement_names:
                logger.warning(
                    "[EngineeringService] 原始计量行与模型结果存在差异：原文计量行=%d，"
                    "模型计量行=%d，疑似漏提=%d，示例=%s",
                    sum(source_measurement_names.values()),
                    sum(model_measurement_names.values()),
                    len(missing_measurement_names),
                    missing_measurement_names[:5],
                )
            else:
                logger.info(
                    "[EngineeringService] 原始计量行审计通过：原文计量行=%d，模型计量行=%d",
                    sum(source_measurement_names.values()),
                    sum(model_measurement_names.values()),
                )
        else:
            # 关闭源表后处理时不执行原文计量行审计，避免引入额外的结果校验。
            logger.info("[EngineeringService] 已跳过原文计量行与模型结果的差异审计。")
        # Pydantic 已完成类型、必填项和额外字段校验；分区字段继续在上方执行原文证据校验。
        logger.info(
            "[EngineeringService] 已完成模型清单汇总：设备明细=%d；仅按外部分区结构恢复可验证计价父行。",
            len(merged_equipment_list),
        )

        failed_chunk_numbers = [idx + 1 for idx, item in enumerate(chunk_results) if not item]
        empty_chunk_numbers = [
            idx + 1
            for idx, item in enumerate(chunk_results)
            if item and all(not schema.main_equipment_list for schema in item)
        ]
        if failed_chunk_numbers:
            logger.error(
                f"[EngineeringService] 分块提取失败清单: {failed_chunk_numbers}，"
                f"成功返回空设备清单的分块: {empty_chunk_numbers}"
            )

        # 所有分块均已完成后仍未得到设备项，按无可提取工程清单正常降级，不进行额外循环重试。
        if all_tables and not merged_equipment_list:
            diagnostic = (
                "检测到工程清单候选表格，但所有分块均未产生设备明细；"
                f"失败分块={failed_chunk_numbers or '无'}，空结果分块={empty_chunk_numbers or '无'}。"
            )
            logger.warning(
                f"[EngineeringService] {diagnostic} "
                "已完成全部分块处理，按无可提取工程清单继续保存其它工程元数据。"
            )

        final_schema = EngineeringSchema(
            main_equipment_list=merged_equipment_list,
            special_working_conditions=special_conditions,
            mandatory_standards=mandatory_standards,
            tech_validation=tech_validation,
            safety_and_env_requirements=safety_requirements,
            reasoning="; ".join(reasoning_list)
        )

        # 记录最终将要落库的完整结果，用于与模型原始返回和目标 BOM 树逐项对照。
        logger.info(
            "[EngineeringService] 工程清单最终归一化结果（文档ID=%s，设备明细=%d）：\n%s",
            document_id,
            len(merged_equipment_list),
            _schema_to_log_json(final_schema),
        )

        # 自动落盘数据库
        if self.db_model_cls and document_id:
            try:

                self._save_to_db(document_id, final_schema)
            except Exception as db_err:
                logger.warning(f"⚠️ 结构化数据提取成功，但落盘数据库失败 (文档ID: {document_id}): {db_err}")

        logger.info(f"✅ [EngineeringService] 语义上下文提取完成，成功汇总 {len(merged_equipment_list)} 项设备明细！")
        return final_schema

engineering_service = EngineeringService()
