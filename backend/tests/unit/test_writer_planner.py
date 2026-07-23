import pytest
from unittest.mock import patch, MagicMock
from app.agents.nodes.writer_planner_node import (
    plan_chapter_tasks_from_markdown,
    get_default_chapter_tasks,
    ChapterTask,
    ChapterPlan
)
from app.agents.nodes.writer_executor_node import execute_single_chapter_task


def test_get_default_chapter_tasks():
    """测试降级兜底的默认章节任务结构"""
    tasks = get_default_chapter_tasks()
    assert len(tasks) >= 8
    task_hints = [t.mapping_hint for t in tasks]
    assert "bid_letter" in task_hints
    assert "pricing" in task_hints
    assert "technical" in task_hints


@patch("app.agents.nodes.writer_planner_node.llm_service")
def test_plan_chapter_tasks_from_markdown(mock_llm):
    """测试从 Markdown 原文地毯式拆解章节任务列表"""
    mock_plan = ChapterPlan(
        source_chapter="第七章 投标文件格式",
        tasks=[
            ChapterTask(
                task_id="task_01",
                chapter_number="一",
                chapter_title="一、投标函",
                mapping_hint="bid_letter",
                task_type="template_fill",
                content_hint="致：某某单位"
            ),
            ChapterTask(
                task_id="task_02",
                chapter_number="二",
                chapter_title="二、防爆工况技术方案",
                mapping_hint="technical",
                task_type="generative_essay",
                content_hint="请阐述防爆措施"
            )
        ]
    )
    mock_llm.generate_structured_output.return_value = mock_plan

    text = "第七章 投标文件格式 一、投标函 二、防爆工况技术方案"
    tasks = plan_chapter_tasks_from_markdown(text)

    assert len(tasks) == 2
    assert tasks[0].task_id == "task_01"
    assert tasks[0].task_type == "template_fill"
    assert tasks[1].task_type == "generative_essay"


@pytest.mark.asyncio
@patch("app.agents.nodes.writer_executor_node.llm_service")
async def test_execute_single_chapter_task_generative(mock_llm):
    """测试单个生成类章节任务的执行"""
    mock_llm.generate_text.return_value = "## 防爆工况技术方案正文\n我方完全满足防爆要求。"
    
    task = ChapterTask(
        task_id="task_tech",
        chapter_number="五",
        chapter_title="五、技术方案",
        mapping_hint="technical",
        task_type="generative_essay"
    )

    metadata = {
        "engineering": {
            "main_equipment_list": [{"name": "防爆电机"}],
            "special_working_conditions": ["防爆ExdIIBT4"]
        }
    }
    analysis = {}

    res = await execute_single_chapter_task(task, metadata, analysis)
    assert res["task_id"] == "task_tech"
    assert "防爆" in res["filled_content"]
