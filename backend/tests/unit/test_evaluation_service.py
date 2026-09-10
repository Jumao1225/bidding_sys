from unittest.mock import patch

from app.services.metadata.evaluation_service import (
    EvaluationSchema,
    _normalize_evaluation_method,
    evaluation_service,
)


def test_normalize_evaluation_method_should_keep_short_name():
    """短评标方法名称应保持原样。"""
    assert _normalize_evaluation_method("综合评分法") == "综合评分法"


def test_normalize_evaluation_method_should_remove_explanation_after_separator():
    """评标方法后带说明时，应只保留方法名称。"""
    value = "综合评分法：在符合招标文件要求的前提下，总得分为各项评分之和"

    assert _normalize_evaluation_method(value) == "综合评分法"


def test_normalize_evaluation_method_should_cap_unseparated_boundary_text():
    """没有分隔符的异常长字段也必须受展示长度上限约束。"""
    value = "异常方法" + "描述" * 30

    normalized = _normalize_evaluation_method(value)

    assert len(normalized) == 32
    assert normalized.startswith("异常方法")


def test_evaluation_schema_should_not_expose_reasoning_field():
    """评标 Schema 不应再要求模型生成高成本的可见推理字段。"""
    assert "reasoning" not in EvaluationSchema.model_fields


def test_extract_metadata_should_normalize_method_before_persisting():
    """评标提取结果应在落库前完成短字段规范化。"""
    extracted = EvaluationSchema(
        evaluation_method="综合评分法：这是不应进入标题徽章的详细评分说明"
    )

    with patch.object(evaluation_service, "extract", return_value=extracted), \
         patch.object(evaluation_service, "_save_to_db") as save_mock:
        result = evaluation_service.extract_metadata("测试上下文", "document-a")

    assert result.evaluation_method == "综合评分法"
    save_mock.assert_called_once_with("document-a", result)
