import pytest
from unittest.mock import patch, MagicMock
from app.agents.nodes.writer_planner_node import ChapterTask
from app.agents.tools.writer_tools import (
    get_company_qualifications_tool,
    get_cost_estimation_data_tool,
    retrieve_chapter_clause_requirements
)
from app.agents.nodes.writer_executor_node import execute_single_chapter_task, execute_all_chapter_tasks


def test_get_cost_estimation_data_tool():
    """测试成本测算底价提取工具的数据解析与大写金额转换"""
    analysis_data = {
        "cost_analysis": {
            "total_cost": 120000.0,
            "budget_status": "预算符合要求",
            "items": [
                {"name": "高性能服务器", "qty": 2, "unit": "台", "ref_price": 60000.0, "subtotal": 120000.0}
            ]
        }
    }
    cost_data = get_cost_estimation_data_tool(analysis_data)

    assert cost_data["total_cost"] == 120000.0
    assert "拾" in cost_data["total_cost_rmb"] or "万" in cost_data["total_cost_rmb"]
    assert len(cost_data["cost_items"]) == 1
    assert cost_data["budget_status"] == "预算符合要求"


@patch("app.agents.tools.writer_tools.SessionLocal")
def test_get_company_qualifications_tool(mock_session):
    """测试资质中心 DB 查询工具的数据读取"""
    mock_db = MagicMock()
    mock_session.return_value = mock_db

    mock_qual = MagicMock()
    mock_qual.id = "qual_001"
    mock_qual.name = "建筑工程施工总承包"
    mock_qual.level = "二级"
    mock_qual.company_name = "测试建筑工程有限公司"
    mock_qual.expiry_date = None
    mock_qual.file_url = "/uploads/qualifications/qual_001.pdf"

    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_qual]

    quals = get_company_qualifications_tool("tenant_001")
    assert len(quals) == 1
    assert quals[0]["name"] == "建筑工程施工总承包"
    assert quals[0]["level"] == "二级"
    assert quals[0]["expiry_date"] == "长期有效"


@pytest.mark.asyncio
@patch("app.agents.nodes.writer_executor_node.llm_service")
@patch("app.agents.nodes.writer_executor_node.get_company_qualifications_tool")
async def test_execute_single_chapter_task_template_fill(mock_get_quals, mock_llm):
    """测试 template_fill 类型的章节任务执行逻辑"""
    mock_llm.generate_text.return_value = "项目名称：测试项目\n招标编号：PROJ-001\n致：某某招标公司\n投标总价：人民币 拾贰万元整 (¥120,000.00)"

    task = ChapterTask(
        task_id="task_01_bid_letter",
        chapter_number="一",
        chapter_title="一、投标函",
        mapping_hint="bid_letter",
        task_type="template_fill",
        template_markdown="致：____\n项目名称：____\n招标编号：____"
    )

    metadata = {
        "timeline": {"project_name": "测试项目", "project_id_code": "PROJ-001"}
    }
    analysis = {
        "cost_analysis": {"total_cost": 120000.0, "items": []}
    }

    res = await execute_single_chapter_task(task, metadata, analysis, document_id="doc_123")

    assert res["task_id"] == "task_01_bid_letter"
    assert "PROJ-001" in res["filled_content"] or "测试项目" in res["filled_content"]


@pytest.mark.asyncio
@patch("app.agents.nodes.writer_executor_node.get_company_qualifications_tool")
async def test_execute_single_chapter_task_qualification_table(mock_get_quals):
    """测试 qualification 类型的资质表格数据读取与装配"""
    mock_get_quals.return_value = [
        {"name": "电子与智能化工程", "level": "一级", "expiry_date": "2028-12-31", "company_name": "某科技公司", "file_url": "/url1"}
    ]

    task = ChapterTask(
        task_id="task_03_qual",
        chapter_number="三",
        chapter_title="三、资格审查资料",
        mapping_hint="qualification",
        task_type="schema_table"
    )

    res = await execute_single_chapter_task(task, {}, {}, tenant_id="tenant_001")

    assert len(res["table_rows"]) == 1
    assert res["table_rows"][0]["name"] == "电子与智能化工程"
    assert res["table_rows"][0]["level"] == "一级"
