from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

from .base import BaseMetadataService
from app.db.models.metadata import EvaluationMetadata

class ScoreDetail(BaseModel):
    """动态评分项（递归或列表结构，适配任意评分表）"""
    item_code: Optional[str] = Field(None, description="评分项编号或序号，如 '1.1'、'技术三'")
    category: str = Field(..., description="一级评分分类，如：商务分/技术分/价格分/资信分/服务分")
    sub_category: Optional[str] = Field(None, description="二级子项，如：团队人员配置、项目实施方案、同类业绩")
    title: str = Field(..., description="评分项名称")
    max_score: float = Field(..., description="本项最高分值")
    
    scoring_criteria: str = Field(..., description="完整评分标准原文")
    scoring_type: Optional[str] = Field(None, description="评分类型：加分项(bonus) / 扣分项(deduction) / 阶梯打分(ladder) / 专家打分(subjective)")
    
    rules_summary: Optional[list[str]] = Field(
        default_factory=list, 
        description="拆解后的结构化得分要点（如：['具备CMMI3得1分','具备CMMI5得3分','上限3分']）"
    )

class EvaluationSchema(BaseModel):
    evaluation_method: str = Field("综合评分法", description="评标方法（如：综合评分法、最低投标价法、双信封法）")
    total_score: float = Field(100.0, description="总分，通常为 100")
    
    weight_distribution: dict[str, float] = Field(
        default_factory=dict, 
        description="各评分维度及其对应的权重分值"
    )

    score_tree: list[ScoreDetail] = Field(
        default_factory=list, 
        description="提取出的所有评分细则明细列表"
    )

    hard_service_requirements: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="提取到的售后服务及硬性约束条款（如：{'质保期': '3年', '维修响应': '4小时', '培训服务': '免费培训3人', '罚则': '每超时1天扣0.5%'}）。如果不涉及具体数值或要求，请强制丢弃或置为空字典 {}。"
    )

    reasoning: Optional[str] = Field(None, description="CoT 推导过程（不落库）")

class EvaluationService(BaseMetadataService):
    def __init__(self):
        super().__init__(db_model_cls=EvaluationMetadata)

    def extract_metadata(self, context: str, document_id: str) -> EvaluationSchema:
        system_prompt = """
你是【资深评标专家与售后运维总监】。你的任务是从传入的招标文件（可能是文字段落、列表或Markdown表格形式的“评标办法”和“合同商务条款”部分）中，以**全局视角**穷尽式地提取出**评分权重分布、完整的评分细则树，以及售后硬性约束**。
下游的 Service Worker（售后服务专家）和报价系统将完全依赖你的结构化解析，任何一项几分的遗漏都可能导致投标失利。

【全局视野与提取指南】
1. **穷尽式提取评分树 (`score_tree`)**：无论评分标准多么复杂，请进行自上而下的地毯式扫描，将每一项独立的评分点（包含极其细微的偏离扣分、证书加分）剥离为 `ScoreDetail`，确保绝无遗漏。利用 `category`（如技术分）和 `sub_category`（如施工方案）来构建准确的层级关系。
2. **逻辑校验机制**：请确保提取的 `evaluation_method`、`weight_distribution`（各大类权重汇总）与 `total_score`，以及所有叶子节点 `max_score` 的加和在数学逻辑上自洽。不要捏造，但必须纵览全局防止漏抓。
3. **深入解析计分规则 (`rules_summary`)**：不要仅仅摘抄原句，必须剥开复杂的嵌套文字，把诸如“每多一项业绩加1分，最高5分”等规则提炼为清晰的短句数组放入 `rules_summary`。
4. **无视排版，注重语义**：原文本可能极度碎片化或缺乏规整表格，请基于资深评标经验，跨越段落和格式障碍，精准还原评分全貌。
5. **售后服务及约束剥离 (`hard_service_requirements`)**：仔细寻找任何涉及“售后服务”、“维护保养”、“培训服务”、“响应时间”、“质保期/缺陷责任期”、“罚款/违约金”的具体要求。无论这些要求是否在评分表里，都必须将它们强制抽离并以字典形式（如 `{"质保期": "3年", "维修响应": "4小时内到达现场"}`）独立写入。注意：严格防范“假大空”废话，提取的内容必须是具备具体数值边界或明确动作指向的硬性要求（如“必须提供原厂质保函”、“具备本地化团队”）。如果原文仅仅是“售后态度好”、“质量可靠”等无具体支撑的主观描述，请强制丢弃。严禁利用常识推断补充！

请务必先在 `reasoning` 字段中写下你通盘梳理整个评分体系的逻辑脉络，然后再输出结构化 JSON。
如果不包含某项内容，对应字段置空或返回空列表。绝不可主观推断或编造原文不存在的计分项。
"""
        return self.extract(context, EvaluationSchema, system_prompt, document_id)

evaluation_service = EvaluationService()
