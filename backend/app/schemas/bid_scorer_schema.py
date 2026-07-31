"""
标书打分 Schema 定义 (bid_scorer_schema.py)

定义 BidScorerAgent 相关的请求参数和响应数据模型，
配合 FastAPI 自动生成 OpenAPI 文档。
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============================================================
# 请求模型 (Request)
# ============================================================

class ScoreBidRequest(BaseModel):
    """触发打分的请求参数"""
    document_id: str = Field(..., description="被评分的投标文件 Document ID")
    source_doc_id: str = Field(..., description="评分维度来源的招标文件 Document ID")
    scoring_rounds: int = Field(default=3, ge=1, le=5, description="共识轮数（1~5，默认 3）")


class RescoreCategoryRequest(BaseModel):
    """针对特定分类/维度或单一评分项进行人工微调重算请求"""
    result_id: str = Field(..., description="打分记录 ID (UUID)")
    category: str = Field(..., description="目标评估维度分类名称，例如 '价格分'")
    item_code: Optional[str] = Field(None, description="可选的目标评分项编号或标题，若指定则仅精细重算该单一项")
    user_instruction: str = Field(..., description="用户自定义微调指令/调优提示词")
    scoring_rounds: int = Field(default=1, ge=1, le=5, description="重算轮数（默认 1 轮）")


# ============================================================
# 响应模型 (Response)
# ============================================================

class ScoreItemResponse(BaseModel):
    """单项打分结果"""
    id: Optional[str] = Field(None, description="记录 ID")
    item_code: Optional[str] = Field(None, description="评分项编号")
    category: str = Field(..., description="一级分类")
    sub_category: Optional[str] = Field(None, description="二级分类")
    title: str = Field(..., description="评分项名称")
    max_score: float = Field(..., description="该项满分")
    ai_score: float = Field(..., description="AI 打分（中位数）")
    confidence: float = Field(..., description="置信度（0.0~1.0）")
    score_variance: float = Field(0.0, description="三轮分数标准差")
    all_round_scores: Optional[List[float]] = Field(None, description="三轮原始分数")
    scoring_basis: Optional[str] = Field(None, description="评分依据（引用原文）")
    deduction_reason: Optional[str] = Field(None, description="扣分原因")
    suggestion: Optional[str] = Field(None, description="改进建议")

    class Config:
        from_attributes = True


class CategoryScoreResponse(BaseModel):
    """大类得分汇总"""
    category: str = Field(..., description="分类名称")
    score: float = Field(..., description="该类得分")
    max_total: float = Field(..., description="该类满分")
    count: int = Field(..., description="评分项数量")


class ImprovementSuggestion(BaseModel):
    """改进建议"""
    priority: int = Field(..., description="优先级（1~5，越高越紧急）")
    category: str = Field(..., description="所属分类")
    title: str = Field(..., description="评分项名称")
    current_score: float = Field(..., description="当前得分")
    potential_gain: float = Field(..., description="改进后可提升的分数")
    action: str = Field(..., description="具体改进行动")


class ScoreResultSummary(BaseModel):
    """打分结果摘要（用于列表展示）"""
    id: str = Field(..., description="打分记录 ID")
    document_id: str = Field(..., description="投标文件 ID")
    source_doc_id: str = Field(..., description="招标文件 ID")
    evaluation_method: Optional[str] = Field(None, description="评标方法")
    total_score: float = Field(..., description="总分")
    max_possible: float = Field(..., description="满分")
    score_rate: float = Field(..., description="得分率")
    scoring_rounds: int = Field(3, description="共识轮数")
    model_name: Optional[str] = Field(None, description="LLM 模型名称")
    created_at: Optional[datetime] = Field(None, description="创建时间")

    class Config:
        from_attributes = True


class ScoreResultDetail(BaseModel):
    """打分结果完整详情（含逐项明细）"""
    id: str = Field(..., description="打分记录 ID")
    document_id: str = Field(..., description="投标文件 ID")
    source_doc_id: str = Field(..., description="招标文件 ID")
    evaluation_method: Optional[str] = Field(None, description="评标方法")
    total_score: float = Field(..., description="总分")
    max_possible: float = Field(..., description="满分")
    score_rate: float = Field(..., description="得分率")
    category_scores: Optional[Dict[str, Any]] = Field(None, description="按大类聚合的分数")
    summary: Optional[str] = Field(None, description="总体评价摘要")
    top_improvements: Optional[List[ImprovementSuggestion]] = Field(None, description="改进建议")
    validation_warnings: Optional[List[str]] = Field(None, description="校验告警")
    scoring_rounds: int = Field(3, description="共识轮数")
    model_name: Optional[str] = Field(None, description="LLM 模型名称")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    items: List[ScoreItemResponse] = Field(default_factory=list, description="逐项打分明细")

    class Config:
        from_attributes = True


class UploadBidResponse(BaseModel):
    """投标文件上传响应"""
    document_id: str = Field(..., description="投标文件的唯一 ID")
    chunk_count: int = Field(..., description="切片数量")
    parse_status: str = Field(..., description="解析状态")
    source_doc_id: str = Field(..., description="关联的招标文件 ID")


# ============================================================
# 切片与人工标注 Schema (Manual Chunking Annotation)
# ============================================================

class DocChunkDetailResponse(BaseModel):
    """文档切片明细（用于前端标注与全文档展现）"""
    id: str = Field(..., description="切片唯一 ID")
    document_id: str = Field(..., description="所属文档 ID")
    chunk_index: int = Field(..., description="切片序号")
    section_title: Optional[str] = Field(None, description="章节名称（自动预测或人工标注）")
    parent_chapter: Optional[str] = Field(None, description="父级章节")
    content: str = Field(..., description="切片文本或表格内容")
    page_num: Optional[int] = Field(None, description="物理页码")
    has_table: Optional[bool] = Field(False, description="是否为表格切片")

    class Config:
        from_attributes = True


class ChunkUpdateItem(BaseModel):
    """单切片更新项"""
    id: Optional[str] = Field(None, description="切片记录 ID（新建切片时可为 null）")
    chunk_index: int = Field(..., description="切片序号")
    section_title: Optional[str] = Field(None, description="人工指定的章节名称")
    parent_chapter: Optional[str] = Field(None, description="父级章节名称")
    content: str = Field(..., description="切片文本内容")
    page_num: Optional[int] = Field(None, description="物理页码")


class ChunkBatchUpdateRequest(BaseModel):
    """批量提交人工标注切片的请求体"""
    chunks: List[ChunkUpdateItem] = Field(..., description="人工标注修改后的全量切片列表")

