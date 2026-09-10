import json
from pathlib import Path

from app.services.cost_service import (
    merge_cost_analysis_with_manual_structure,
    resolve_cost_total,
    sum_root_cost_items,
)


def load_manual_cost_merge_fixture() -> dict:
    """加载重新匹配保留人工结构的测试数据。"""
    fixture_path = Path(__file__).parents[1] / "fixtures" / "manual_cost_merge.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_sum_root_cost_items_should_not_double_count_parent_and_children():
    """父节点已包含子节点金额时，总价只能统计父节点。"""
    rows = [
        {"parent_item": None, "tree_level": 1, "calculated_total": 10000.0},
        {"parent_item": "成套设备", "tree_level": 2, "calculated_total": 5000.0},
        {"parent_item": "成套设备", "tree_level": 2, "calculated_total": 5000.0},
    ]

    assert sum_root_cost_items(rows) == 10000.0


def test_resolve_cost_total_should_prefer_saved_standard_total():
    """存在标准成本总额时，不应重新累加父子明细。"""
    rows = [
        {"parent_item": None, "tree_level": 1, "calculated_total": 10000.0},
        {"parent_item": "成套设备", "tree_level": 2, "calculated_total": 10000.0},
    ]

    assert resolve_cost_total({"total_cost": 10000.0}, rows) == 10000.0


def test_resolve_cost_total_should_fallback_to_root_items_for_invalid_total():
    """标准总额无效时，应兼容历史 ORM 明细并只汇总顶层节点。"""
    rows = [
        type("CostRow", (), {"parent_item": None, "tree_level": 1, "calculated_total": 321.456})(),
        type("CostRow", (), {"parent_item": "成套设备", "tree_level": 2, "calculated_total": 321.456})(),
    ]

    assert resolve_cost_total({"total_cost": "不是金额"}, rows) == 321.46


def test_merge_cost_analysis_should_preserve_manual_order_deletion_and_custom_item():
    """重新匹配后应保留人工排序、删除结果和新增节点。"""
    fixture = load_manual_cost_merge_fixture()

    merged = merge_cost_analysis_with_manual_structure(
        fixture["fresh_cost_analysis"],
        fixture["saved_cost_analysis"],
    )

    assert [item["node_id"] for item in merged["items"]] == [
        "root-photovoltaic",
        "cabinet-b",
        "custom-item",
    ]
    assert merged["items"][1]["ref_price"] == 200
    assert merged["items"][1]["parent_node_id"] == "root-photovoltaic"
    assert merged["items"][2]["is_custom_added"] is True
    assert merged["total_cost"] == 230


def test_merge_cost_analysis_should_preserve_manual_price_override():
    """重新匹配后不应覆盖用户手动修改过的价格。"""
    fixture = load_manual_cost_merge_fixture()
    saved_analysis = {
        "items": [fixture["manual_price_item"]],
    }

    merged = merge_cost_analysis_with_manual_structure(
        fixture["fresh_cost_analysis"],
        saved_analysis,
    )

    assert merged["items"][0]["ref_price"] == 999
    assert merged["items"][0]["match_quality"] == "手动修改"


def test_merge_cost_analysis_should_return_fresh_result_when_no_saved_items():
    """没有已保存人工清单时应直接使用本次重新匹配结果。"""
    fixture = load_manual_cost_merge_fixture()
    fresh_analysis = fixture["fresh_cost_analysis"]

    assert merge_cost_analysis_with_manual_structure(fresh_analysis, {}) is fresh_analysis


def test_merge_cost_analysis_should_refresh_unpriced_custom_item_from_fresh_match():
    """手动新增项未填写价格时，重新匹配应回填价格库结果并保留节点结构。"""
    fixture = load_manual_cost_merge_fixture()
    fresh_item = next(
        item for item in fixture["fresh_cost_analysis"]["items"]
        if item["node_id"] == "custom-pending"
    )
    fresh_analysis = {
        **fixture["fresh_cost_analysis"],
        "items": [fresh_item],
    }
    saved_analysis = {
        "items": [fixture["pending_custom_saved_item"]],
    }

    merged = merge_cost_analysis_with_manual_structure(fresh_analysis, saved_analysis)

    assert merged["items"][0]["node_id"] == "custom-pending"
    assert merged["items"][0]["parent_node_id"] is None
    assert merged["items"][0]["ref_price"] == 880
    assert merged["items"][0]["matched_name"] == "价格库新增项"
    assert merged["items"][0]["match_quality"] == "精准匹配"
    assert merged["total_cost"] == 1760


def test_merge_cost_analysis_should_preserve_priced_custom_item():
    """手动新增项已有价格时，重新匹配不应覆盖人工价格。"""
    fixture = load_manual_cost_merge_fixture()
    fresh_item = next(
        item for item in fixture["fresh_cost_analysis"]["items"]
        if item["node_id"] == "custom-pending"
    )
    saved_item = {
        **fixture["pending_custom_saved_item"],
        "ref_price": 320,
        "match_quality": "手动添加",
    }
    fresh_analysis = {
        "items": [fresh_item],
    }

    merged = merge_cost_analysis_with_manual_structure(
        fresh_analysis,
        {"items": [saved_item]},
    )

    assert merged["items"][0]["ref_price"] == 320
    assert merged["items"][0]["match_quality"] == "手动添加"
