"""标书填报修复轮章节范围筛选测试。"""

from app.agents.bid_filler_agent import _select_repair_chapter_tasks


def test_select_repair_chapter_tasks_should_keep_only_failed_chapters():
    """正常场景：修复轮只保留终审指出的问题章节。"""
    chapter_tasks = [
        {"chapter_number": "一", "chapter_title": "投标函", "category": "needs_fill"},
        {"chapter_number": "二", "chapter_title": "项目人员表", "category": "needs_data"},
    ]

    result = _select_repair_chapter_tasks(
        chapter_tasks,
        {"项目人员表": "存在人员字段未落位"},
    )

    assert result == [chapter_tasks[1]]


def test_select_repair_chapter_tasks_should_match_numbered_title():
    """边界场景：终审标题包含章节编号时仍能匹配缓存任务。"""
    chapter_tasks = [
        {"chapter_number": "五", "chapter_title": "项目负责人及其他人员介绍", "category": "needs_data"},
    ]

    result = _select_repair_chapter_tasks(
        chapter_tasks,
        {"五、项目负责人及其他人员介绍": "人员表存在回读问题"},
    )

    assert result == chapter_tasks


def test_select_repair_chapter_tasks_should_return_empty_for_invalid_input():
    """异常/空输入场景：没有缓存或没有修复指令时不误派发章节。"""
    assert _select_repair_chapter_tasks(None, {"项目人员表": "需要修复"}) == []
    assert _select_repair_chapter_tasks([], {"项目人员表": "需要修复"}) == []
    assert _select_repair_chapter_tasks(
        [{"chapter_title": "项目人员表"}],
        None,
    ) == []
    assert _select_repair_chapter_tasks(
        [{"chapter_title": "项目人员表"}, "非法任务"],
        {"": "无效指令"},
    ) == []
