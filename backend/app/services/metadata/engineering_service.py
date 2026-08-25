import logging
from typing import Optional
from pydantic import BaseModel, Field

from .base import BaseMetadataService
from app.db.models.metadata import EngineeringMetadata
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

class EquipmentItem(BaseModel):
    """设备/软件/材料清单明细（支持生成技术偏离表与多级精细化 BOM 成本核算）"""
    item_code: Optional[str] = Field(None, description="招标文件工程量清单表格【第一列序号】中的原始层级编码（如'(一)'、'1'、'1.1'、'1.2'等，必须 100% 原样摘录，严禁私自篡改）")
    item_name: str = Field(..., description="设备/软件/材料/元器件名称")
    specifications: Optional[str] = Field(None, description="规格型号或详细技术参数要求")
    quantity: Optional[float] = Field(None, description="项目物理总采购需求量，纯数字。若为多级嵌套子项，必须严格按照穿透连乘公式计算：顶层采购套数 * 各层级单套定额！若原文仅给出计价单位而未写明具体采购数量，必须输出 null！绝对禁止脑补填 1！")
    unit: Optional[str] = Field(None, description="物理/计价单位（如：平方米、块、台、套、面、组、只、人月）")
    brand_requirements: Optional[str] = Field(None, description="品牌或产地要求（如：'进口原装'、'指定某品牌/某品牌或同等及以上品牌'、'国产自主可控'）")
    key_parameters: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件明确要求的核心技术指标/关键星号(*)参数"
    )
    parent_item: Optional[str] = Field(None, description="直接父级设备/总成名称（若本条目为某组件内部的分项/元器件，填入直接上一级父设备名称；独立顶层设备填 null）")
    root_item: Optional[str] = Field(None, description="所属顶层主要标的物名称（若本条目为某复合标的物名下的多级子项，填入最顶层标的物名称；自身即为顶层主标的填 null 或自身名称）")
    tree_level: Optional[int] = Field(1, description="层级深度：1=顶层主要标的物, 2=二级成套子系统/总成, 3=三级核心元器件/配件, 4+=更细分末级项")
    per_set_quantity: Optional[float] = Field(None, description="上一级组件内部单套定额/每套包含数量（若为成套内部子项，记录每套包含的数量；独立顶层设备填 null）")
    section_name: Optional[str] = Field(None, description="所属分标段/分区域/分项工程/子系统名称（如'标段一'、'一期工程'、'某厂区/某地块'，若全文未划分区域则为 null）")

class TechValidationRequirement(BaseModel):
    """技术验证、样品与演示要求（一票否决/高分项）"""
    sample_required: Optional[bool] = Field(False, description="开标现场是否需要提供物理样品/样机")
    sample_description: Optional[str] = Field(None, description="样品/样机送达与封样要求")
    poc_demo_required: Optional[bool] = Field(False, description="是否需要现场 POC 演示或软件系统功能答辩")
    test_report_requirements: Optional[list[str]] = Field(
        default_factory=list, 
        description="要求的第三方检测/测试报告明细（如：['须具备某种第三方认证机构出具的检测报告']）"
    )

class EngineeringSchema(BaseModel):
    # --- 1. 主要标的物与设备清单 (生成《技术偏离表》与精细化 BOM) ---
    main_equipment_list: Optional[list[EquipmentItem]] = Field(
        default_factory=list, 
        description="主要设备、材料或软件标的物配置清单明细"
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


class EngineeringService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EngineeringMetadata)

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

        # 智能表格靶向预过滤：从传入的大段混合文本中精准提取出所有的【标的物/设备材料清单表格】与关联标题，自动剔除纯文字噪音
        clean_context = extract_equipment_tables_and_context(context)

        system_prompt = r"""
你是资深的【项目总工与现场施工技术专家】。你的任务是从传入的技术图纸说明、工程量清单、《项目需求》、《技术规格书》、《货物需求一览表》及《评标办法》中，提取出**核心设备指标与非标施工/合规难点**。

【零容忍数字幻觉（最高指令）】
系统对参数极为严格，你提取的任何设备数量、技术指标必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。
- **关于数量 `quantity`**：若标书原文中仅给出了计价单位（如“平方米”、“米”），但未标注具体物理采购数量，`quantity` 必须输出为 null，绝对禁止脑补填 1！

【提取指南】
1. **主材配置与硬性技术指标（偏离表与 BOM 核心）**：核心设备的名称、规格、数量、品牌要求必须结构化提取。数量必须是纯数字。
   - **【主要标的物聚焦与宏观大类归口原则（最高指令）】**：
     - 清单提取应紧紧围绕招标文件中的《货物需求一览表》、《工程量清单》与核心设备材料表，聚焦于具有明确供货实体的**核心设备、材料、元器件与成套总成**，过滤掉纯现场操作工序或行政告知文字。
     - **关于 `section_name`（所属主要部分/分标段名称）**：
       - `section_name` **必须且仅能填入项目最顶层的宏观分标段/主要大类部分名称**（即招标文件目录中划分的一级/二级大章节标题，通常全项目仅有 3~6 个顶层主要大类部分）。
       - **绝对严禁将表格上方的微观子系统小标题、装置功能小节名称或细分测试步骤当成 `section_name`**！若当前表格属于某顶层大类名下的细分子节，其 `section_name` **必须向上归口继承该顶层大类名称**。
       - 若整个招标文件仅有一张单体表格且全文未划分宏观大类/标段，则 `section_name` 统一填 null。
   - **【任意深度多级嵌套 BOM 设备树（Multi-Level BOM 任意 N 级递归穿透提取，最高指令）】**：
     - 当工程量清单表格中出现包含任意多层嵌套缩进、层级递进编号（如顶层复合系统 $\\rightarrow$ 二级总成 $\\rightarrow$ 三级组件 $\\rightarrow$ 四级模块 $\\rightarrow$ 五级元器件等任意 $N$ 级树状结构）时，必须严格按以下【通用递归归纳法则】逐级完整拆解：
     
     - **【零文本合并红线（通用递归约束）】**：
       - **凡是在表格中带有独立层级编码（如点号递进序号、缩进编号）、独立计量单位或独立单台定额的任何部件/元器件，无论嵌套层级有多深（Level 1 至 Level N），必须 100% 逐行拆解输出为独立的 `EquipmentItem` 记录！**
       - **绝对禁止将第 $L+1$ 级或更深层的子部件合并压缩成一段概括性文字塞进第 $L$ 级父节点的 `specifications` 描述中！**

     - **【通用 N 级递归字段赋值与连乘规则（数学归纳法）】**：
       1. **层级深度判定 (`tree_level`)**：
          - 设最顶层主要标的物为 Level 1（`tree_level = 1`）；
          - 依据序号编码层级（如序号点号数量加 1，或视觉缩进关系）自动确定当前节点所处的层级深度 $L$（`tree_level = L`，其中 $L \\ge 1$）。
       2. **直接父级绑定 (`parent_item`)**：
          - 若 $L = 1$（顶层根节点），`parent_item` 必须为 null；
          - 若 $L \\ge 2$（任意子项/孙项节点），`parent_item` **必须且仅能严格指向其直接所属的上一级（Level $L-1$）父节点的完整名称**。
       3. **顶层根设备绑定 (`root_item`)**：
          - 整个分支树下的所有层级节点（Level 1 至 Level $N$），其 `root_item` **必须全部统一填入该分支最顶层 Level 1 根标的物的名称**。
       4. **单台配置定额 (`per_set_quantity`)**：
          - 若 $L = 1$，`per_set_quantity` 填 null；
          - 若 $L \\ge 2$，`per_set_quantity` **必须准确填入在单台直接父级（Level $L-1$ 设备）中的物理配置数量**（纯数字 $q_L$）。
       5. **项目物理总需求量递归穿透连乘换算 (`quantity`)**：
          - 若 $L = 1$，`quantity` 填该顶层标的物在整个项目中的总采购套数（纯数字 $Q_1$）；
          - 若 $L \ge 2$，当前物料在整个项目中的物理总需求量 **必须通过从顶层至当前层级的全链路单套定额递归连乘公式准确换算**：
            $$\text{quantity} = Q_1 \times q_2 \times q_3 \times \dots \times q_L$$
            （即：顶层总套数 $Q_1$ 乘以该分支路径上各级单套定额的乘积）。
       6. **规格与技术参数 (`specifications`)**：
          - 每一个节点（无论处于哪一层级）的 `specifications` **仅摘录其自身的物理型号、尺寸、电气指标与材质参数**，严禁掺杂下级子部件清单文字。
     - 若清单为普通扁平表格（无嵌套层级关系），则所有条目的 `parent_item`、`root_item` 和 `per_set_quantity` 统一输出为 null，`tree_level` 统一填 1，`quantity` 为原文物理采购数量。
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

        # 当只有一个表格且文本长度适中时，直接单次提取
        def extract_section_title_from_heading(heading_text: str) -> Optional[str]:
            """从表格前方的文本中自动提取所属的顶级/次级章节标题作为分部/分标段名称（通用算法，零硬编码）"""
            if not heading_text:
                return None
            lines = [l.strip() for l in heading_text.split('\n') if l.strip()]
            
            # 第一轮：优先查找明确具备【一级/二级大编号或Markdown标题】特征的顶层章节行
            for line in reversed(lines):
                clean_line = re.sub(r'^[#\s*]+', '', line).strip()
                # 排除纯注释或说明行
                if re.match(r'^(?:注|说明|备注|提示|注意)[:：]', clean_line):
                    continue
                # 匹配大编号（如 1、 2. 一、 二、 第X标段 第X部分 ### 标题等）
                if re.match(r'^(?:[0-9]+[、.．]|[一二三四五六七八九十]+[、.．]|第[0-9一二三四五六七八九十]+[标标段章节部分区])', clean_line) or line.startswith('#'):
                    # 截断破折号、中划线及后续说明文字（如 "—以下清单..."、"-说明..."、"（以下清单..."）
                    m = re.split(r'[-—–]{1,}|——|—以下|：以下|:以下|；以下|;\s*以下|注[:：]|说明[:：]|（以下', clean_line)
                    title = m[0].strip()
                    title_clean = re.sub(r'^[0-9]+[、.．]\s*', '', title).strip()
                    if len(title_clean) >= 2:
                        return title_clean
                    return title

            # 第二轮：查找包含清单/需求/标段/工程等核心分部关键词的行
            for line in reversed(lines):
                clean_line = re.sub(r'^[#\s*]+', '', line).strip()
                if re.match(r'^(?:注|说明|备注|提示|注意)[:：]', clean_line):
                    continue
                if any(kw in clean_line for kw in ['清单', '需求', '标段', '工程', '部分', '系统', '一览表']) and len(clean_line) <= 60:
                    m = re.split(r'[-—–]{1,}|——|—以下|：以下|:以下|；以下|;\s*以下|注[:：]|说明[:：]|（以下', clean_line)
                    return m[0].strip()
            return None

        if len(all_tables) <= 1 and len(clean_context) <= 6000:
            single_section = extract_section_title_from_heading(clean_context[:all_tables[0].start()]) if all_tables else None
            res = self.extract(
                clean_context,
                EngineeringSchema,
                system_prompt,
                document_id,
                tenant_id=effective_tenant_id,
            )
            if res and res.main_equipment_list and single_section:
                for eq in res.main_equipment_list:
                    if not eq.section_name:
                        eq.section_name = single_section
            return res

        chunks = []
        chunk_sections = []
        last_end = 0
        current_active_section: Optional[str] = None

        for tbl in all_tables:
            start, end = tbl.start(), tbl.end()
            heading = clean_context[last_end:start].strip()
            
            # 状态机机制：若当前表格前置文本识别出新的章节大类，更新当前活跃区域；否则自动沿用/继承上一个有效区域
            parsed_title = extract_section_title_from_heading(heading)
            if parsed_title:
                current_active_section = parsed_title
            
            sec_title = current_active_section
            tbl_text = tbl.group(0)
            chunk = f"{heading}\n\n{tbl_text}".strip()
            chunks.append(chunk)
            chunk_sections.append(sec_title)
            last_end = end

        tail = clean_context[last_end:].strip()
        if tail and chunks:
            chunks[-1] = f"{chunks[-1]}\n\n{tail}"
        elif tail:
            chunks.append(tail)
            chunk_sections.append(current_active_section)

        logger.info(f"🚀 [EngineeringService] 识别到 {len(chunks)} 个清单表格分块，启动 5 路并发结构化提取...")

        def process_chunk(idx: int, chunk_text: str, section_title: Optional[str]) -> tuple[int, Optional[EngineeringSchema]]:
            section_hint = f"\n【重要指令】：本分块表格所属的顶层分标段/主要部分为【{section_title}】。本表格中提取出的所有设备物料，其 `section_name` 字段必须统一填入：“{section_title}”。严禁将表格内部各行的局部小标题随意当作 section_name！\n" if section_title else ""
            prompt = f"""
{system_prompt}

【任务约束】
1. 你的任务是根据下面提供的【当前分项工程量清单与技术要求】进行信息抽取。{section_hint}
2. 宁缺毋滥原则：如果上下文中完全没有提及某个字段的相关信息（找不到），请将该字段值置为 null。绝不允许编造任何信息。
3. 明确豁免原则：如果上下文中明确写明“无需提供”、“不作要求”，请针对该字符串字段返回 "明确无要求"；如果写明“待定”、“另行通知”，请返回 "待定"。千万不要返回 null。

<当前分项工程量清单与技术要求 (第 {idx + 1}/{len(chunks)} 分项)>
{chunk_text}
</当前分项工程量清单与技术要求>
"""
            try:
                sub_res = llm_service.generate_structured_output(
                    prompt=prompt,
                    schema_cls=EngineeringSchema,
                    temperature=0.1,
                    tenant_id=effective_tenant_id,
                )
                return idx, sub_res
            except Exception as e:
                logger.error(f"分块 {idx + 1} 提取失败: {e}")
                return idx, None

        chunk_results = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(5, len(chunks))) as executor:
            futures = [executor.submit(process_chunk, i, c, chunk_sections[i]) for i, c in enumerate(chunks)]
            for future in as_completed(futures):
                c_idx, c_schema = future.result()
                chunk_results[c_idx] = c_schema

        # 汇总合并各分块提取的设备清单与各项要求
        merged_equipment_list = []
        special_conditions = []
        mandatory_standards = []
        tech_validation = None
        safety_requirements = []
        reasoning_list = []

        for c_idx, schema_item in enumerate(chunk_results):
            if not schema_item:
                continue
            c_section = chunk_sections[c_idx]
            if schema_item.main_equipment_list:
                for eq in schema_item.main_equipment_list:
                    # 确定性章节大类纠偏：若该表格明确识别到了顶层章节标题，统一纠偏保持全表一致
                    if c_section:
                        if not eq.section_name or eq.section_name != c_section:
                            eq.section_name = c_section
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

        final_schema = EngineeringSchema(
            main_equipment_list=merged_equipment_list,
            special_working_conditions=special_conditions,
            mandatory_standards=mandatory_standards,
            tech_validation=tech_validation,
            safety_and_env_requirements=safety_requirements,
            reasoning="; ".join(reasoning_list)
        )

        # 自动落盘数据库
        if self.db_model_cls and document_id:
            try:
                self._save_to_db(document_id, final_schema)
            except Exception as db_err:
                logger.warning(f"⚠️ 结构化数据提取成功，但落盘数据库失败 (文档ID: {document_id}): {db_err}")

        logger.info(f"✅ [EngineeringService] 分块并发提取完成，成功汇总 {len(merged_equipment_list)} 项设备明细！")
        return final_schema

engineering_service = EngineeringService()
