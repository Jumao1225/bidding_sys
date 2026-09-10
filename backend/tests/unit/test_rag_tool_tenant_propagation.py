"""测试 Worker 的 RAG 工具能够显式传递租户模型配置。"""

from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.agents.bid_filler_workers import _build_worker_tools, run_chapter_worker
from app.core.context import current_tenant_id


def _get_worker_search_tool(tenant_id: str | None):
    """构造偏离表 Worker 工具并返回固定租户的通用检索工具。"""
    tools = _build_worker_tools(
        docx_temp_path="",
        chapter_title="商务偏离表",
        mapping_hint="deviation",
        category="needs_data",
        tenant_id=tenant_id,
    )
    return next(tool for tool in tools if tool.name == "search_bidding_document")


def test_worker_rag_tool_explicit_tenant_should_reach_routing():
    """正常场景：即使工具线程没有租户上下文，也必须使用 Worker 显式绑定的租户。"""
    search_tool = _get_worker_search_tool("tenant-deepseek")

    with patch("app.agents.tools.security.validate_document_access", return_value=True), patch(
        "app.agents.tools.rag_tools.routing_service.analyze_intent_and_route",
        return_value=None,
    ) as route_mock, patch(
        "app.agents.tools.rag_tools.rag_service.search_bidding_document",
        return_value="原文证据",
    ):
        result = search_tool.invoke({"document_id": "doc-1", "query": "合同付款方式"})

    assert "原文证据" in result
    route_mock.assert_called_once_with("doc-1", "合同付款方式", tenant_id="tenant-deepseek")


def test_worker_rag_tool_empty_tenant_should_use_context_tenant():
    """边界场景：未显式绑定租户时，仍兼容已有 ContextVar 调用方式。"""
    token = current_tenant_id.set("tenant-from-context")
    try:
        search_tool = _get_worker_search_tool("")
        with patch("app.agents.tools.security.validate_document_access", return_value=True), patch(
            "app.agents.tools.rag_tools.routing_service.analyze_intent_and_route",
            return_value=None,
        ) as route_mock, patch(
            "app.agents.tools.rag_tools.rag_service.search_bidding_document",
            return_value="原文证据",
        ):
            search_tool.invoke({"document_id": "doc-2", "query": "投标截止时间"})
    finally:
        current_tenant_id.reset(token)

    route_mock.assert_called_once_with("doc-2", "投标截止时间", tenant_id="tenant-from-context")


def test_worker_rag_tool_routing_error_should_return_logged_failure():
    """异常场景：Routing 失败时返回可识别错误，并保留异常日志处理。"""
    search_tool = _get_worker_search_tool("tenant-error")

    with patch("app.agents.tools.security.validate_document_access", return_value=True), patch(
        "app.agents.tools.rag_tools.routing_service.analyze_intent_and_route",
        side_effect=RuntimeError("routing unavailable"),
    ):
        result = search_tool.invoke({"document_id": "doc-3", "query": "评标办法"})

    assert "RAG 检索过程中发生错误" in result
    assert "routing unavailable" in result


def test_worker_company_profile_tool_should_keep_explicit_profile_id():
    """跨线程场景：Worker 工具应固定使用显式企业档案 ID。"""
    from app.agents.tools.bid_db_tools import current_profile_id

    tools = _build_worker_tools(
        docx_temp_path="",
        chapter_title="投标函",
        mapping_hint="bid_letter",
        category="needs_fill",
        profile_id="selected-profile",
    )
    profile_tool = next(tool for tool in tools if tool.name == "query_company_profile_tool")
    db = MagicMock()
    selected_profile = SimpleNamespace(company_name="四川石楠建设工程有限公司")
    token = current_profile_id.set("wrong-default-profile")
    try:
        with patch("app.agents.tools.bid_db_tools.SessionLocal", return_value=db), patch(
            "app.agents.tools.bid_db_tools.resolve_company_profile",
            return_value=selected_profile,
        ) as resolve_mock:
            result = profile_tool.invoke({"field_key": "投标人名称"})
    finally:
        current_profile_id.reset(token)

    assert result == "四川石楠建设工程有限公司"
    resolve_mock.assert_called_once_with(db, "selected-profile")


def test_run_chapter_worker_should_forward_explicit_profile_id():
    """正常场景：章节 Worker 必须将档案 ID 传给工具装配层。"""
    fake_llm = MagicMock()
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="", tool_calls=[], response_metadata={})]
    }

    with patch("app.agents.bid_filler_workers.llm_service.get_llm", return_value=fake_llm), patch(
        "app.agents.bid_filler_workers._build_worker_tools", return_value=[]
    ) as build_tools_mock, patch(
        "app.agents.bid_filler_workers.build_worker_prompt",
        return_value=("系统提示", "用户提示"),
    ), patch(
        "app.agents.bid_filler_workers.create_react_agent", return_value=fake_agent
    ), patch("app.services.audit_service.audit_service.log_event"), patch(
        "app.agents.bid_filler_workers._record_worker_context"
    ):
        result = run_chapter_worker(
            chapter_title="投标函",
            chapter_number="一",
            mapping_hint="bid_letter",
            category="needs_fill",
            document_id="doc-1",
            docx_temp_path="",
            profile_id="selected-profile",
        )

    assert result["status"] == "success"
    assert build_tools_mock.call_args.kwargs["profile_id"] == "selected-profile"


def test_pricing_worker_should_use_bounded_rounds_and_deterministic_closure():
    """报价 Worker 必须使用 7 轮/5 万输出上限，并在模型不提交矩阵时走后端闭环。"""
    fake_llm = MagicMock()
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="", tool_calls=[], response_metadata={})]
    }
    deterministic_proposal = {
        "path": "/body/tbl[1]",
        "proposed_text": '[["1", "项目A"]]',
        "value": '[["1", "项目A"]]',
        "type": "table_rows",
        "status": "success",
    }

    with patch("app.agents.bid_filler_workers.llm_service.get_llm", return_value=fake_llm) as get_llm_mock, patch(
        "app.agents.bid_filler_workers._build_worker_tools", return_value=[]
    ), patch(
        "app.agents.bid_filler_workers.build_worker_prompt", return_value=("系统提示", "用户提示")
    ), patch(
        "app.agents.bid_filler_workers.create_react_agent", return_value=fake_agent
    ), patch(
        "app.agents.bid_filler_workers._build_deterministic_pricing_proposal",
        return_value=deterministic_proposal,
    ), patch("app.services.audit_service.audit_service.log_event"), patch(
        "app.agents.bid_filler_workers._record_worker_context"
    ):
        result = run_chapter_worker(
            chapter_title="投标配置及分项报价表",
            chapter_number="五",
            mapping_hint="pricing",
            category="needs_data",
            document_id="doc-pricing-1",
            docx_temp_path="",
        )

    assert result["status"] == "success"
    assert result["deterministic_closure_used"] is True
    assert fake_agent.invoke.call_args.kwargs["config"] == {"recursion_limit": 7}
    assert all(call.kwargs["max_output_tokens"] == 50000 for call in get_llm_mock.call_args_list)


def test_dynamic_pricing_worker_should_skip_free_text_model_and_close_deterministically():
    """动态扩写报价表有真实契约时，Worker 应直接闭环，不启动可能失控的自由文本模型。"""
    deterministic_proposal = {
        "path": "/body/tbl[1]",
        "proposed_text": '[["1", "项目A", "10.00"]]',
        "value": '[["1", "项目A", "10.00"]]',
        "type": "table_rows",
        "status": "success",
    }
    contract = {"mode": "dynamic_expand", "table_path": "/body/tbl[1]"}

    with patch(
        "app.agents.bid_filler_workers._resolve_pricing_table_contract",
        return_value=contract,
    ), patch(
        "app.agents.bid_filler_workers._build_deterministic_pricing_proposal",
        return_value=deterministic_proposal,
    ), patch("app.agents.bid_filler_workers.llm_service.get_llm") as get_llm_mock, patch(
        "app.services.audit_service.audit_service.log_event"
    ), patch("app.agents.bid_filler_workers._record_worker_context"):
        result = run_chapter_worker(
            chapter_title="投标配置及分项报价表",
            chapter_number="五",
            mapping_hint="pricing",
            category="needs_data",
            document_id="doc-pricing-direct",
            docx_temp_path="existing.docx",
        )

    assert result["status"] == "success"
    assert result["deterministic_closure_used"] is True
    get_llm_mock.assert_not_called()
