from typing import Optional
from pydantic import BaseModel, Field

from .base import BaseMetadataService
from app.db.models.metadata import TimelineMetadata

# --- 1. 渠道与通讯录结构 ---
class TenderAcquisitionInfo(BaseModel):
    """招标文件获取/领购信息"""
    acquisition_method: Optional[str] = Field(None, description="获取方式（如：线上平台下载、现场领购、邮件获取）")
    doc_fee: Optional[float] = Field(0.0, description="招标文件售价/标书费（单位：元，免费填 0.0）")
    download_url_or_address: Optional[str] = Field(None, description="标书下载网址平台或现场领购地址")
    acquisition_deadline: Optional[str] = Field(None, description="标书发售/获取截止时间（格式：YYYY-MM-DD HH:MM）")
    required_materials: Optional[str] = Field(None, description="领购所需材料（如：营业执照复印件、授权委托书、付款凭证）")

class ContactPerson(BaseModel):
    """招投标通讯录与联系人"""
    role_type: str = Field(..., description="角色类型（如：招标人/甲方、招标代理机构、技术答疑联系人、现场踏勘联系人、标书现场接收人）")
    unit_name: Optional[str] = Field(None, description="单位名称（如：XX市公安局 / XX招标代理有限公司）")
    contact_name: Optional[str] = Field(None, description="联系人姓名")
    phone: Optional[str] = Field(None, description="联系电话/手机号/座机")
    email: Optional[str] = Field(None, description="电子邮箱（用于提交澄清答疑函）")
    address: Optional[str] = Field(None, description="通讯地址/标书现场送达地址")

# --- 2. 筹备期与装订结构 ---
class TenderMilestone(BaseModel):
    """筹备期关键流程节点（红线控制）"""
    name: str = Field(..., description="节点名称（如：标书发售截止、现场踏勘、答疑提问截止、保证金到账截止）")
    deadline: str = Field(..., description="截止时间（标准格式：YYYY-MM-DD HH:MM）")
    is_mandatory: bool = Field(True, description="是否为硬性废标节点（如保证金未按时到账直接废标）")
    description: Optional[str] = Field(None, description="特殊说明（如：现场踏勘需带授权委托书及身份证原件）")

class DocumentRequirement(BaseModel):
    """标书制作与封装形式要求（交付调度）"""
    submission_type: str = Field("电子标+纸质标", description="递交形式（如：纯电子招投标、纯纸质递交、线上上传+线下纸质）")
    original_copies: int = Field(1, description="纸质正本份数")
    duplicate_copies: int = Field(0, description="纸质副本份数")
    electronic_copies: Optional[str] = Field(None, description="电子版载体要求（如：U盘1份，包含PDF与Word可编辑版）")
    seal_requirements: Optional[str] = Field(None, description="密封与包封要求（如：正副本统一密封，正套信封加盖骑缝章）")
    online_upload_platform: Optional[str] = Field(None, description="线上递交平台名称/网址（如果是电子标）")

# --- 3. TimelineSchema 主体 ---
class TimelineSchema(BaseModel):
    # --- A. 项目基础标识 ---
    project_id_code: Optional[str] = Field(None, description="项目编号/招标编号/标段编号")
    project_name: Optional[str] = Field(None, description="项目名称")
    tender_segment: Optional[str] = Field(None, description="标段/包件名称（如：标段一：系统开发）")

    # --- B. 领购渠道与通讯录 ---
    acquisition_info: Optional[TenderAcquisitionInfo] = Field(None, description="招标文件领购渠道与标书费说明")
    contacts: Optional[list[ContactPerson]] = Field(default_factory=list, description="招标人、代理机构及技术答疑联系人明细")

    # --- C. 投标倒排核心节点 (Supervisor 建立筹备看板重点) ---
    bid_deadline: Optional[str] = Field(None, description="开标/投标文件递交截止时间（格式：YYYY-MM-DD HH:MM）")
    bid_validity_days: Optional[int] = Field(None, description="投标有效期（纯天数，如 90）")
    tender_milestones: Optional[list[TenderMilestone]] = Field(default_factory=list, description="招投标全流程关键节点明细列表（发售、踏勘、提问、保证金等）")

    # --- D. 标书装订与制作要求 (交付调度) ---
    document_requirements: Optional[DocumentRequirement] = Field(None, description="标书份数、封装格式及电子标递交要求")

    # --- E. 交付/工期要求 (纯指标，无复杂里程碑) ---
    construction_period_days: Optional[int] = Field(None, description="要求总工期天数（纯整数，月份按30天换算，如 90）")
    construction_period_description: Optional[str] = Field(None, description="工期描述原文（如：'自合同签订之日起90个日历天内完成交付'）")

    # --- 推导过程 ---
    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")


class TimelineService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=TimelineMetadata)

    def extract_metadata(self, context: str, document_id: str) -> TimelineSchema:
        system_prompt = """
你是资深的【招投标项目经理与全局调度主管】。你的任务是从传入的《招标公告》和《投标人须知》中，提取出**招投标筹备期**的核心参数。
下游的总控 Agent 将会拿着这些时间节点去初始化系统全局的项目倒排看板，所以你的提取绝对不能有差错。

【零容忍数字幻觉（最高指令）】
系统对数字极其敏感，你提取的任何数字必须在原文中有明确出处，**绝对禁止**进行毫无根据的猜测或篡改。

【提取指南】
1. **渠道与通讯录**：寻找“获取招标文件”、“联系方式”。必须准确剥离甲方和代理机构的角色和电话。
2. **倒排里程碑**：除了开标时间（bid_deadline），其他诸如现场踏勘、答疑提问死线、保证金到账时间，统统写入 tender_milestones 数组中。所有时间强制转换为 `YYYY-MM-DD HH:MM` 格式。
3. **交付与封装**：寻找“投标文件的递交”、“密封要求”，提取正副本份数，以及是否需要 U盘 或线上递交。
4. **轻量化工期**：只提取总工期（construction_period_days），不用理会实施期间的各阶段里程碑。工期请转换成纯数字天数（如果是月，按30天换算）。

请在 `reasoning` 字段中写下你的提炼和确认过程。
如果上下文中没有任何关于某项的信息，请严格将该字段输出为 null。
"""
        return self.extract(context, TimelineSchema, system_prompt, document_id)

timeline_service = TimelineService()
