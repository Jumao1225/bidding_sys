from pydantic import BaseModel, Field
from typing import Optional

from .base import BaseMetadataService
from app.db.models.metadata import TimelineMetadata

class TimelineSchema(BaseModel):
    project_id_code: Optional[str] = Field(
        None, description="项目唯一标识，如项目编号、招标编号、标段编号等。若无则置null"
    )
    project_name: Optional[str] = Field(
        None, description="项目名称。若无则置null"
    )
    bid_deadline: Optional[str] = Field(
        None, description="开标截止时间或投标文件递交截止时间，强制格式为 YYYY-MM-DD HH:MM (例如 2026-08-01 14:00)。若无则置null"
    )
    qa_deadline: Optional[str] = Field(
        None, description="提问截止时间、澄清答疑死线，强制格式为 YYYY-MM-DD HH:MM。若无则置null"
    )
    construction_period_days: Optional[int] = Field(
        None, description="项目工期要求，统一提取为纯数字天数（如 '60'）。如果是月则转换成天数，如果是节点则置null。"
    )
    document_copies: Optional[str] = Field(
        None, description="标书制作份数要求，如“正本1份，副本4份”。若无则置null"
    )
    reasoning: Optional[str] = Field(
        None, description="你的推导与思考过程（CoT），说明你是如何识别这些时间节点和业务参数的。"
    )

class TimelineService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=TimelineMetadata)

    def extract_metadata(self, context: str, document_id: str) -> TimelineSchema:
        system_prompt = """
你是资深的【招投标项目经理与全局调度主管】。你的任务是从传入的招标文件上下文中，提取出**核心的身份标识与时间轴约束**。
下游的总控 Agent (Supervisor) 将会拿着这些时间节点去初始化系统全局的项目倒排看板，并安排异步任务的时间轴，所以每一个时间节点的提取绝对不能有差错。

【提取指南】
1. 标识：寻找“项目编号”、“招标编号”、“项目名称”。
2. 开标死线：寻找“投标截止时间”、“开标时间”。必须提取并转换为标准格式 `YYYY-MM-DD HH:MM`。
3. 答疑死线：寻找“澄清招标文件截止时间”。转换为 `YYYY-MM-DD HH:MM`。
4. 工期：寻找“交货期”、“工期”等。只能提取数字天数（如 120），如果是“1年”填365。不能包含任何文字。
5. 装订份数：寻找“投标文件份数”等物料要求。

请在 `reasoning` 字段中写下你的提炼和确认过程。
如果上下文中没有任何关于某项的时限或编号信息，请严格将其输出为 null。
"""
        return self.extract(context, TimelineSchema, system_prompt, document_id)

timeline_service = TimelineService()
