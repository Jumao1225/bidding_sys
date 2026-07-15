from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .base import BaseMetadataService
from app.db.models.metadata import EngineeringMetadata

class EngineeringSchema(BaseModel):
    main_equipment_quantities: Optional[Dict[str, str]] = Field(
        None, description="主要标的物的定量配置。严格采用 {'设备名称': '规格及数量'} 的字典结构，如 {'光伏组件': '545Wp，1000块'}。若无则置null"
    )
    special_working_conditions: Optional[list[str]] = Field(
        None, description="特殊或高难度的施工工况说明。输出简短精炼的短语数组，如 ['生锈换瓦', '大跨度跨河布线', '夜间施工']。若无则置null"
    )
    reasoning: Optional[str] = Field(
        None, description="你的推导与思考过程（CoT），说明如何从庞杂的清单或技术规范中锁定这些核心工况与数量。"
    )

class EngineeringService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EngineeringMetadata)

    def extract_metadata(self, context: str, document_id: str) -> EngineeringSchema:
        system_prompt = """
你是资深的【项目总工与现场施工技术专家】。你的任务是从传入的技术图纸说明、工程量清单或招标技术规范上下文中，提取出**核心设备指标与非标施工难点**。
下游的技术方案专家 (Tech Worker) 将依赖你提取的痛点词（如“换瓦”、“跨河敷设”）去向量知识库检索专项施工工艺，自动为你撰写针对性的专项施工文案。

【提取指南】
1. 主材配置：不需要罗列每一个螺丝钉。你需要提取最核心的大宗物资及其数量（例如：“光伏组件”、“逆变器”、“箱变”）。必须以严格的键值对形式返回。
2. 特殊工况：重点排查文件中的“现场踏勘”、“注意事项”、“施工环境说明”。提取特殊的高成本/高风险工况，必须是纯字符串组成的数组 (List[str])。

请在 `reasoning` 字段中简要说明你是如何找出这些痛点和核心物资的。
如果上下文中没有任何相关的工程配置或特殊工况信息，请将其输出为 null。绝对不可根据常识盲目瞎编。
"""
        return self.extract(context, EngineeringSchema, system_prompt, document_id)

engineering_service = EngineeringService()
