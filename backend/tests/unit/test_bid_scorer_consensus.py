"""
标书打分智能体 Supervisor + N 专项 Agent 核心与护栏逻辑单元测试

严格遵守测试与编码规范：
1. 采用 fixtures 动态加载测试预设数据
2. 测试命名规范：test_<功能>_<场景>_<期望结果>
3. 覆盖三种常见场景：正常场景（中位数贴合共识）、边界场景（分值截断与护栏）、异常场景（LLM格式解析失败安全兜底）
"""

import os
import json
import pytest
from unittest.mock import patch

from app.agents.tools.bid_scorer_tools import (
    compute_consensus,
    llm_score_batch,
    _extract_dynamic_keywords,
)
from app.agents.bid_scorer_agent import (
    supervisor_aggregate_node,
    _classify_specialist_agent_type,
)


@pytest.fixture
def mock_scorer_data():
    """
    从 fixtures 加载外部 JSON 数据源，避免在代码中硬编码字典或 JSON 数据
    """
    fixture_path = os.path.join(
        os.path.dirname(__file__), "..", "fixtures", "bid_scorer_mock_data.json"
    )
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_compute_consensus_normal_three_rounds_should_return_median(mock_scorer_data):
    """
    正常情况测试：针对相同评分项传入三轮结果，预期经过中位数贴合度选优共识后返回分数的中位数及最贴合的评语。
    """
    items = mock_scorer_data["sample_score_tree"]
    round1 = mock_scorer_data["llm_round1_response"]
    round2 = mock_scorer_data["llm_round2_response"]
    round3 = mock_scorer_data["llm_round3_response"]
    all_rounds = [round1, round2, round3]

    result = compute_consensus(items=items, all_rounds=all_rounds, category="技术分")

    # 验证返回值基础结构及项数一致性
    assert len(result) == 2
    
    # 第 1 项：三轮打分分别为 8.0, 9.0, 8.5，中位数为 8.5
    item1_res = next(i for i in result if i["item_code"] == "1.1")
    assert item1_res["ai_score"] == 8.5
    assert item1_res["max_score"] == 10.0
    assert item1_res["category"] == "技术分"
    assert len(item1_res["all_round_scores"]) == 3

    # 第 2 项：三轮打分皆为 5.0，中位数 5.0，标准差 0.0，置信度 1.0
    item2_res = next(i for i in result if i["item_code"] == "1.2")
    assert item2_res["ai_score"] == 5.0
    assert item2_res["score_variance"] == 0.0
    assert item2_res["confidence"] == 1.0


@patch("app.services.llm_service.llm_service.generate_text")
def test_llm_score_batch_exceed_max_score_should_truncate(mock_generate_text, mock_scorer_data):
    """
    边界情况测试（防幻觉 L3 护栏）：当 LLM 返回的分数超出满分或者小于0分时，
    预期系统强制在截断护栏作用下将分值限制在 0 至 max_score 区间内。
    """
    items = mock_scorer_data["sample_score_tree"]
    # 模拟 LLM 返回超出合理域界的分数（如 15 分和 -2 分）
    exceed_response_str = json.dumps(mock_scorer_data["llm_exceed_score_response"], ensure_ascii=False)
    mock_generate_text.return_value = f"```json\n{exceed_response_str}\n```"

    results = llm_score_batch(
        items=items,
        bid_content="测试的检索参考内容...",
        round_idx=0,
        category="技术分",
    )

    assert len(results) == 2
    # 15.0 分被截断致最大值 10.0
    item1 = next(i for i in results if i["item_code"] == "1.1")
    assert item1["ai_score"] == 10.0

    # -2.0 分被截断致最小边界 0.0
    item2 = next(i for i in results if i["item_code"] == "1.2")
    assert item2["ai_score"] == 0.0


@patch("app.services.llm_service.llm_service.generate_text")
def test_llm_score_batch_invalid_json_should_fallback_to_zero(mock_generate_text, mock_scorer_data):
    """
    异常情况测试：当 LLM 生成的数据完全不是标准 JSON（语法出错或崩溃信息），
    预期引擎不会抛出异常中断任务，而是触发异常防御回滚降级致全部项 0 分，标记错误与置信度 0。
    """
    items = mock_scorer_data["sample_score_tree"]
    # 模拟错误的非 JSON 输出
    mock_generate_text.return_value = "非常抱歉，本次生成遇到网络或排版错误无法给出完整结构。"

    results = llm_score_batch(
        items=items,
        bid_content="一些文档文本",
        round_idx=0,
        category="技术分",
    )

    assert len(results) == 2
    for item_res in results:
        assert item_res["ai_score"] == 0
        assert item_res["confidence"] == 0.0
        assert "LLM 返回格式异常" in item_res["scoring_basis"] or "解析失败" in (item_res["deduction_reason"] or "")


def test_supervisor_aggregate_node_abnormal_scores_should_generate_validation_warnings():
    """
    Supervisor 聚合节点数学校验（护栏 L5）与边界测试：
    针对某一类目全取 0 分或总加和超满分的边缘场景，预期系统能发现异常并生成校验警告提示。
    """
    state_mock = {
        "scored_items": [
            {
                "category": "技术分",
                "ai_score": 0.0,
                "max_score": 50.0
            },
            {
                "category": "商务分",
                "ai_score": 120.0,  # 单类累计异常超越
                "max_score": 50.0
            }
        ],
        "total_possible": 100.0
    }
    
    result = supervisor_aggregate_node(state_mock)  # type: ignore
    
    warnings = result["validation_warnings"]
    assert len(warnings) >= 2
    warning_texts = " ".join(warnings)
    assert "得 0 分" in warning_texts or "修饰截断" in warning_texts
    # 商务分应该被强制回调到最大极限
    assert result["category_scores"]["商务分"]["score"] == 50.0
    # 总分应当受限保护在 total_possible(100) 以内
    assert result["total_score"] == 50.0


def test_supervisor_specialist_agent_classification():
    """
    Supervisor 分类派发测试：根据分类名称分配致专项子 Agent
    """
    assert _classify_specialist_agent_type("技术参数及功能要求") == "tech_param_subagent"
    assert _classify_specialist_agent_type("施工方案与实施计划") == "plan_eval_subagent"
    assert _classify_specialist_agent_type("投标人资质与业绩") == "commercial_subagent"


def test_extract_dynamic_keywords():
    """
    模块 2 检索层测试：动态提取搜索词
    """
    items = [
        {"title": "设备平面布置图及施工方案", "sub_category": "技术要求", "scoring_criteria": "提供完整施工图纸与尺寸标注"}
    ]
    keywords = _extract_dynamic_keywords(items)
    assert isinstance(keywords, list)
    assert len(keywords) > 0
