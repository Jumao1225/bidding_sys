import os
import pytest
from pathlib import Path
from app.services.parsers.mineru_parser import MinerUParser


def test_mineru_check_availability():
    """
    测试环境探测功能，能够返回正确的诊断字典格式
    """
    service = MinerUParser()
    avail = service.check_availability()
    
    assert isinstance(avail, dict)
    assert "is_installed" in avail
    assert "message" in avail


def test_parse_file_with_docx_fixture():
    """
    测试解析测试集的真实 Word 标书文件 (test_bidding.docx)，校验 .md 生成与大章结构提取
    """
    base_dir = Path(__file__).resolve().parent.parent
    word_fixture_path = base_dir / "fixtures" / "test_bidding.docx"
    
    assert os.path.exists(word_fixture_path), f"测试用例需要的 Word Fixture 不存在: {word_fixture_path}"

    service = MinerUParser()
    result = service.parse(file_path=str(word_fixture_path), task_id="test_unit_task_001")

    # 1. 验证结果结构完整
    assert result["task_id"] == "test_unit_task_001"
    assert result["file_name"] == "test_bidding.docx"
    assert os.path.exists(result["md_file_path"])

    # 2. 验证 Markdown 内容非空
    assert len(result["markdown_content"]) > 0
    assert "#" in result["markdown_content"]

    # 3. 验证结构化章节解析
    sections = result.get("sections", [])
    if sections:
        assert any("title" in sec for sec in sections)

    # 4. 读取物理落盘的 md 文件，确认文件内容一致
    with open(result["md_file_path"], "r", encoding="utf-8") as f:
        saved_md = f.read()
    assert saved_md == result["markdown_content"]


def test_mineru_parse_retry_success():
    """
    测试 MinerU 前两次解析失败、第 3 次重试成功的情况
    """
    from unittest.mock import patch
    base_dir = Path(__file__).resolve().parent.parent
    word_fixture_path = base_dir / "fixtures" / "test_bidding.docx"
    service = MinerUParser()

    call_count = 0

    def mock_cloud_api(file_path, task_id, model_version="vlm", max_poll_seconds=600):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return None
        return "# 重试解析成功标题\n这是第 3 次尝试成功解析的内容。"

    with patch.object(service, "_parse_via_cloud_api", side_effect=mock_cloud_api), \
         patch("time.sleep", return_value=None):
        result = service.parse(file_path=str(word_fixture_path), task_id="test_retry_task", max_retries=2)

    assert call_count == 3
    assert result["markdown_content"] == "# 重试解析成功标题\n这是第 3 次尝试成功解析的内容。"
    assert "test_retry_task_retry_2" in result["task_id"]


def test_mineru_parse_retry_exhausted_raises():
    """
    测试 MinerU 解析连续失败超过 max_retries (2次) 后抛出 RuntimeError 异常
    """
    from unittest.mock import patch
    base_dir = Path(__file__).resolve().parent.parent
    word_fixture_path = base_dir / "fixtures" / "test_bidding.docx"
    service = MinerUParser()

    with patch.object(service, "_parse_via_cloud_api", return_value=None), \
         patch("time.sleep", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            service.parse(file_path=str(word_fixture_path), task_id="test_fail_task", max_retries=2)

    assert "MinerU 解析失败" in str(exc_info.value)
    assert "重试 2 次" in str(exc_info.value)

