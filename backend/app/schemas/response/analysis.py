from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class AnalysisResultData(BaseModel):
    """
    AI 解析结果的返回数据结构
    """
    qualifications_analysis: Dict[str, Any] = Field(
        default_factory=dict, 
        description="资质分析比对结果 (包含 match_score, items 等)"
    )
    risks_analysis: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="风险项识别列表"
    )
    extracted_text: Optional[str] = Field(
        default=None,
        description="完整的招标文件提取文本，用于前端高亮展示"
    )
