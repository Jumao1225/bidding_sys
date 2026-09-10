"""路由服务的目录树原文映射单元测试。"""

from app.services.routing_service import (
    RoutingDecision,
    _canonicalize_target_chapters,
    _extract_toc_candidates,
)


def test_extract_toc_candidates_should_remove_structure_markers_only():
    """目录节点提取只清理列表标记，不改写节点正文。"""
    toc = "- 第一章 节点甲\n  - 第二章 节点乙"

    assert _extract_toc_candidates(toc) == ["第一章 节点甲", "第二章 节点乙"]


def test_canonicalize_target_chapters_should_return_exact_toc_node():
    """模型返回序号变体时，路由应映射回目录树中的原文节点。"""
    decision = RoutingDecision(
        is_global_search=False,
        target_chapters=["（一）节点甲"],
    )

    result = _canonicalize_target_chapters(
        decision,
        "- 第一章 节点甲\n- 第二章 节点乙",
    )

    assert result.is_global_search is False
    assert result.target_chapters == ["第一章 节点甲"]


def test_canonicalize_target_chapters_should_fallback_when_node_is_unknown():
    """模型返回目录外标题时，应避免把未知标题继续传入局部检索。"""
    decision = RoutingDecision(
        is_global_search=False,
        target_chapters=["目录外节点"],
    )

    result = _canonicalize_target_chapters(decision, "- 第一章 节点甲")

    assert result.is_global_search is True
    assert result.target_chapters == []
