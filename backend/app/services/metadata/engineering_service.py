import logging
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from .base import BaseMetadataService
from app.db.models.metadata import EngineeringMetadata
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)

class EquipmentItem(BaseModel):
    """设备/软件/材料清单明细（支持生成技术偏离表与多级精细化 BOM 成本核算）"""
    # 禁止模型返回未定义字段，避免字段名写错后被静默丢弃。
    model_config = ConfigDict(extra="forbid")

    item_code: Optional[str] = Field(None, description="招标文件工程量清单表格【第一列序号】中的原始编码（如'(一)'、'1'、'1.1'、'1.2'等，必须 100% 原样摘录；编码中的点号仅表示清单编号，不得单独据此推断 BOM 父子层级）")
    item_name: str = Field(..., description="设备/软件/材料/元器件名称")
    specifications: Optional[str] = Field(None, description="规格型号或详细技术参数要求")
    quantity: Optional[float] = Field(None, description="项目总采购数量或工程量，纯数字。对于设备/材料表示物理采购数量，对于施工/服务项目表示原文工程量或服务次数。若为多级嵌套子项，必须严格按照穿透连乘公式计算：顶层数量 * 各层级单套定额！若原文仅给出计价单位而未写明具体数量，必须输出 null！绝对禁止脑补填 1！")
    unit: Optional[str] = Field(None, description="物理/计价单位（如：平方米、块、台、套、面、组、只、人月）")
    brand_requirements: Optional[str] = Field(None, description="品牌或产地要求（如：'进口原装'、'指定某品牌/某品牌或同等及以上品牌'、'国产自主可控'）")
    key_parameters: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件明确要求的核心技术指标/关键星号(*)参数"
    )
    parent_item: Optional[str] = Field(None, description="直接父级设备/总成名称。只有原文明确存在真实的成套设备/总成父项，且当前行是该父项内部的组件时才填写；普通工程量清单中的分组标题、编号前缀和相邻行都不能作为父项，独立计价行填 null")
    root_item: Optional[str] = Field(None, description="真实 BOM 父子关系中的顶层主要标的物名称；普通扁平工程量清单行填 null")
    tree_level: Optional[int] = Field(1, description="真实 BOM 层级深度；普通扁平工程量清单（包括 2.6.1、2.6.2 这类同级编号行）统一为 1，不能按编号点号数量直接计算")
    per_set_quantity: Optional[float] = Field(None, description="真实成套父项内部的单套定额；普通工程量清单行或仅因编号产生的伪子项填 null")
    section_name: Optional[str] = Field(None, description="所属分标段/分区域/分项工程/子系统名称（如'标段一'、'一期工程'、'某厂区/某地块'，若全文未划分区域则为 null）")

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


class EngineeringService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EngineeringMetadata)

    @staticmethod
    def _normalize_boq_hierarchy(items: list[EquipmentItem]) -> list[EquipmentItem]:
        """清理工程量清单中由分组编号造成的伪 BOM 层级。"""
        if not items:
            return []

        import re

        # 先建立原始编号索引，后续以清单编号校验模型给出的父项，而不是相信相邻行推断。
        item_by_code = {
            str(item.item_code).strip(): item
            for item in items
            if item.item_code and str(item.item_code).strip()
        }
        normalized_items: list[EquipmentItem] = []
        dropped_group_count = 0
        repaired_hierarchy_count = 0

        for item in items:
            item_code = str(item.item_code or "").strip()

            # 没有数量和单位的行通常只是“接地”“预埋管”“乙供设备及材料”等分组标题，
            # 不应进入可计价设备清单，也不能成为其它行的 BOM 父项。
            if item.quantity is None and not item.unit:
                dropped_group_count += 1
                continue

            parent_item = str(item.parent_item or "").strip()
            if parent_item and re.fullmatch(r"\d+(?:\.\d+)+", item_code):
                expected_parent_code = item_code.rsplit(".", 1)[0]
                expected_parent = item_by_code.get(expected_parent_code)

                if expected_parent:
                    expected_parent_name = expected_parent.item_name.strip()
                    parent_is_non_priced_group = (
                        expected_parent.quantity is None and not expected_parent.unit
                    )

                    if parent_is_non_priced_group:
                        # 例如 2.6 是“接地”分组标题，2.6.1～2.6.6 是同级计价行。
                        item.parent_item = None
                        item.root_item = None
                        item.tree_level = 1
                        item.per_set_quantity = None
                        repaired_hierarchy_count += 1
                    elif parent_item != expected_parent_name:
                        # 编号明确给出直接父项时，以编号层级修复模型把兄弟行串成链的问题。
                        item.parent_item = expected_parent_name
                        item.root_item = expected_parent.root_item or expected_parent_name
                        item.tree_level = (expected_parent.tree_level or 1) + 1
                        repaired_hierarchy_count += 1

            normalized_items.append(item)

        if dropped_group_count or repaired_hierarchy_count:
            logger.info(
                "[EngineeringService] BOQ 层级归一化完成："
                f"移除非计价分组行={dropped_group_count}，修复伪父子关系={repaired_hierarchy_count}"
            )
        return normalized_items

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
你是资深的【项目总工与工程造价清单专家】。你的任务是从传入的技术图纸说明、工程量清单、《项目需求》、《技术规格书》和《货物需求一览表》中，提取出**设备、材料以及有明确计价依据的施工/服务 BOQ 行项目**。

【零容忍数字幻觉（最高指令）】
系统对参数极为严格，你提取的任何设备数量、技术指标必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。
- **关于数量 `quantity`**：若标书原文中仅给出了计价单位（如“平方米”、“米”），但未标注具体物理采购数量，`quantity` 必须输出为 null，绝对禁止脑补填 1！

【提取指南】
1. **完整工程量清单行项目提取（最高优先级）**：
   - 当前任务目标是提取完整但**可计价**的 BOM/BOQ 清单，不仅是核心设备和可采购材料。表格中代表设备、材料、安装、施工、运输、调试、检测或其他服务的有效计价行，必须逐行输出为一个 `EquipmentItem`。
   - **计价依据门槛（必须同时检查）**：除有明确子项的父级分部行外，只有当原文表格明确提供了数量/工程量，并且提供了单位、单价、合价、定额或其他计价字段之一时，才允许输出该行。若只有一段工作要求、制度说明或技术描述，没有数量/工程量和计价依据，必须排除，不能自行把 `quantity` 填成 1。
   - 对于满足计价依据门槛的施工/服务行，即使单位是“项”“批”“次”“日”“人月”，或名称看起来像施工工序，也必须保留。比如工程量表中的“电缆直埋”“电缆直埋（过河、沟）”“交通工程”“安装调试”“运输服务”等，均属于合法 BOQ 行项目。
   - 表格中的无数量、无单位、无单价的分组标题/分类行（如“接地”“预埋管”“乙供设备及材料”）不是可计价清单项，不得输出为 `EquipmentItem`，也不得作为 `parent_item`。只有父行自身也是明确的可计价成套设备/总成，且原文明确展示其内部组成关系时，才允许保留父子关系。
   - **明确排除非计价叙述**：安全生产制度、文明施工要求、岗位职责、人员分工、作业票要求、风险提示、违章分类、施工方法、管理流程、培训要求、验收说明、处罚条款、评标规则、合规承诺和一般技术规范，均不得作为 BOM/BOQ 项目；除非它们在工程量/报价表中拥有明确的数量、单位和计价依据。
   - 只有表头、空白行、纯注释、纯说明、合计/小计行（且不代表实际工作内容）可以不作为清单项输出。禁止把“在某区域内使用某种作业票”“工作负责人不在现场”“满足某安全要求”等句子提取为项目。
   - 设备、材料、施工和服务项目统一使用同一套 `EquipmentItem` 结构：项目名称或工作内容填入 `item_name`，原文技术要求/施工内容/服务范围填入 `specifications`，原文数量填入 `quantity`，原文单位填入 `unit`。数量必须是纯数字；原文没有数量时必须为 `null`。
   - **完整保留表格上下文**：必须结合当前表格的全部列、跨行表头、合并单元格内容、表格前后的章节标题和技术说明判断每一行含义；不得只依据“设备名称”列筛选，也不得因为某行名称与设备无关而跳过。
   - **【主要标的物聚焦与宏观大类归口原则（最高指令）】**：
     - 清单提取应紧紧围绕招标文件中的《货物需求一览表》、《工程量清单》、《采购清单》、《报价清单》和核心设备材料表；其他章节只作为技术上下文，不能仅凭其中的要求、制度或说明生成 BOM 项目。
     - **关于 `section_name`（所属主要部分/分标段名称）**：
       - `section_name` **必须且仅能填入项目最顶层的宏观分标段/主要大类部分名称**（即招标文件目录中划分的一级/二级大章节标题，通常全项目仅有 3~6 个顶层主要大类部分）。
       - **绝对严禁将表格上方的微观子系统小标题、装置功能小节名称或细分测试步骤当成 `section_name`**！若当前表格属于某顶层大类名下的细分子节，其 `section_name` **必须向上归口继承该顶层大类名称**。
       - 若整个招标文件仅有一张单体表格且全文未划分宏观大类/标段，则 `section_name` 统一填 null。
   - **【真实 BOM 层级与工程量清单编号严格区分（最高优先级）】**：
     - 工程量清单中的 `2.6`、`2.6.1`、`2.6.2`、`2.6.3` 等点号编号只是工作分解/清单行号，不代表 BOM 父子关系；同一分组下的 `2.6.1`～`2.6.6` 应视为平级计价行，统一输出 `parent_item=null`、`root_item=null`、`tree_level=1`、`per_set_quantity=null`。
     - 绝对禁止因为编号点号层数、行号连续、名称相似或前一行刚好出现，就把同级清单行串成父子链；例如 `2.6.2` 不能因为紧邻 `2.6.1` 就挂到 `2.6.1` 下。
     - 只有同时满足以下条件才建立 BOM 父子关系：父行自身有明确数量/单位或成套计价依据；原文存在“含有/配置/组成/配套”等明确组成语义，或存在可确认的视觉缩进、合并单元格、独立物料清单结构；且当前行确实是该父项内部组件。仅有编号层级时按扁平清单处理。
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
                # 单表路径先完成结果校验，避免空结果在基类中提前落库。
                persist=False,
            )
            if res:
                res.main_equipment_list = self._normalize_boq_hierarchy(res.main_equipment_list)
            if res and res.main_equipment_list and single_section:
                for eq in res.main_equipment_list:
                    if not eq.section_name:
                        eq.section_name = single_section

            if all_tables and (not res or not res.main_equipment_list):
                # 单表已完成本次结构化调用仍无有效清单时，按无可提取表格正常降级，避免无意义重试阻塞任务。
                logger.warning(
                    "[EngineeringService] 单表提取未产生设备明细，已完成本次提取；"
                    "按无可提取工程清单处理并继续保存其它工程元数据。"
                )

            if self.db_model_cls and document_id:
                self._save_to_db(document_id, res)
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
            except Exception as e:
                # 保留完整堆栈，避免并发分块失败后只剩下一个无法定位的空结果。
                logger.exception(f"分块 {idx + 1} 提取失败: {e}")
                return idx, None

            item_count = len(sub_res.main_equipment_list or [])
            item_names = [item.item_name for item in sub_res.main_equipment_list[:5]]
            logger.info(
                f"[EngineeringService] 分块 {idx + 1} 结构化结果: "
                f"设备明细={item_count}，示例={item_names}，输入字符数={len(chunk_text)}"
            )
            if not item_count:
                # 空结果仍允许参与其它字段汇总，但最终会在落库前统一拦截。
                logger.warning(
                    f"[EngineeringService] 分块 {idx + 1} 未提取到设备明细，"
                    "请检查该分块是否只包含表头、表格行是否被 RAG 截断或模型字段是否错配。"
                )
            return idx, sub_res

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

        merged_equipment_list = self._normalize_boq_hierarchy(merged_equipment_list)

        failed_chunk_numbers = [idx + 1 for idx, item in enumerate(chunk_results) if item is None]
        empty_chunk_numbers = [
            idx + 1
            for idx, item in enumerate(chunk_results)
            if item is not None and not item.main_equipment_list
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

        # 自动落盘数据库
        if self.db_model_cls and document_id:
            try:
                self._save_to_db(document_id, final_schema)
            except Exception as db_err:
                logger.warning(f"⚠️ 结构化数据提取成功，但落盘数据库失败 (文档ID: {document_id}): {db_err}")

        logger.info(f"✅ [EngineeringService] 分块并发提取完成，成功汇总 {len(merged_equipment_list)} 项设备明细！")
        return final_schema

engineering_service = EngineeringService()
