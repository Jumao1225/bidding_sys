from typing import Optional
from pydantic import BaseModel, Field

from .base import BaseMetadataService
from app.db.models.metadata import EngineeringMetadata

class EquipmentItem(BaseModel):
    """设备/软件/材料清单明细（支持生成技术偏离表）"""
    item_name: str = Field(..., description="设备/软件/材料名称")
    specifications: Optional[str] = Field(None, description="规格型号或详细技术参数要求")
    quantity: Optional[float] = Field(None, description="数量（纯数字）。若原文仅给出计价单位（如'平方米'）而未写明具体物理采购数量，必须输出 null！绝对禁止脑补填 1！")
    unit: Optional[str] = Field(None, description="单位（如：平方米、块、台、套、人月）")
    brand_requirements: Optional[str] = Field(None, description="品牌或产地要求（如：'进口原装'、'指定某品牌/某品牌或同等及以上品牌'、'国产自主可控'）")
    key_parameters: Optional[list[str]] = Field(
        default_factory=list, 
        description="招标文件明确要求的核心技术指标/关键星号(*)参数"
    )

class TechValidationRequirement(BaseModel):
    """技术验证、样品与演示要求（一票否决/高分项）"""
    sample_required: bool = Field(False, description="开标现场是否需要提供物理样品/样机")
    sample_description: Optional[str] = Field(None, description="样品/样机送达与封样要求")
    poc_demo_required: bool = Field(False, description="是否需要现场 POC 演示或软件系统功能答辩")
    test_report_requirements: Optional[list[str]] = Field(
        default_factory=list, 
        description="要求的第三方检测/测试报告明细（如：['须具备某种第三方认证机构出具的检测报告']）"
    )

class EngineeringSchema(BaseModel):
    # --- 1. 主要标的物与设备清单 (生成《技术偏离表》) ---
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

    def extract_metadata(self, context: str, document_id: str) -> EngineeringSchema:
        system_prompt = """
你是资深的【项目总工与现场施工技术专家】。你的任务是从传入的技术图纸说明、工程量清单、《项目需求》、《技术规格书》及《评标办法》中，提取出**核心设备指标与非标施工/合规难点**。

【零容忍数字幻觉（最高指令）】
系统对参数极为严格，你提取的任何设备数量、技术指标必须在原文中有明确的出处。**绝对禁止**进行毫无根据的猜测、篡改或臆想。
- **关于数量 `quantity`**：若标书原文中仅给出了计价单位（如“平方米”、“米”），但未标注具体物理采购数量，`quantity` 必须输出为 null，绝对禁止脑补填 1！

【提取指南】
1. **主材配置与硬性技术指标（偏离表核心）**：核心设备的名称、规格、数量、品牌要求必须结构化提取。数量必须是纯数字。
   - **关于 `specifications`（规格参数要求）**：**必须 100% 原汁原味完整摘录标书原文中的详细技术参数描述**（包含所有型号参数、材质、尺寸、物理/电气指标等）。
   - **拒绝“详见XXX”废话（最高指令）**：若清单表格中写有“详见技术规格”、“详见项目需求”、“详见第五章”等引用说明，**绝不能直接把“详见XXX”当作规格参数！你必须从后文《技术规格书/项目需求》章节中找到该设备真实的详细规格与技术要求完整摘录填入！**
   - **关于 `key_parameters`**：请从原文中提炼具体的**技术参数指标**（如精确的厚度、材质要求、功率、吞吐量等具有明确物理/化学测量依据的约束），**绝对禁止**提取诸如“使用寿命长”、“防腐防水防火”、“风格协调”之类的假大空废话或主观描述！
   - **极度注意（防止断章取义）**：提取参数时，**必须将该指标生效的【前置条件/测试环境】一并提取**！例如，绝不能只提取“某指标≥某数值”，必须完整提取“在XXX温度、XXX压力、XXX测试条件约束下，该指标≥某数值”。必须将所有带 '*' 号的参数以及带有完整条件的明确技术门槛原汁原味地填入该数组。
2. **特殊工况**：排查“现场踏勘”、“注意事项”。提取特殊的高成本/高风险工况（如“不停机业务迁移”、“夜间施工”）。
3. **技术标准**：提取明确规定的“国家标准”、“行业标准”。这决定了我们的编制依据。
4. **技术验证与样品（死亡雷区）**：重点去《评标办法》或《投标人须知》中寻找“样品”、“检测报告”、“CMA”、“CNAS”、“现场演示(POC)”的字眼，这关乎是否废标。
5. **安全与环保**：提取现场必须遵守的安全红线。

请在 `reasoning` 字段中简要说明你是如何找出这些痛点和核心物资的。
如果上下文中没有任何相关的配置或要求信息，请严格将其输出为 null。绝对不可根据常识盲目瞎编。
"""
        return self.extract(context, EngineeringSchema, system_prompt, document_id)

engineering_service = EngineeringService()
