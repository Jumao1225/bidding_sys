from unittest.mock import MagicMock, patch

from app.services.analysis_result_service import persist_worker_analysis_result


def test_persist_worker_analysis_result_should_merge_result_and_status():
    """专项结果落库时应保留既有字段，并记录本次 Worker 状态。"""
    document = MagicMock()
    document.parsed_metadata = {"cost_analysis": {"total_cost": 100}}

    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = document

    session = MagicMock()
    session.query.return_value = query

    with patch("app.db.session.SessionLocal", return_value=session), patch(
        "app.services.analysis_result_service.flag_modified"
    ):
        persisted = persist_worker_analysis_result(
            document_id="doc-1",
            tenant_id="tenant-1",
            user_id="user-1",
            worker_name="strategy_risk",
            result_updates={"risks_analysis": [{"severity": "高"}]},
        )

    assert persisted is True
    assert document.parsed_metadata["cost_analysis"] == {"total_cost": 100}
    assert document.parsed_metadata["risks_analysis"] == [{"severity": "高"}]
    assert document.parsed_metadata["analysis_status"]["strategy_risk"]["status"] == "completed"
    query.with_for_update.assert_called_once()
    session.commit.assert_called_once()


def test_persist_worker_analysis_result_without_document_id_should_skip():
    """缺少文档 ID 时不能创建无归属的分析记录。"""
    with patch("app.db.session.SessionLocal") as session_local:
        persisted = persist_worker_analysis_result(
            document_id=None,
            tenant_id="tenant-1",
            user_id="user-1",
            worker_name="strategy_risk",
        )

    assert persisted is False
    session_local.assert_not_called()
