import os
import pytest
from pathlib import Path
from app.services.mineru_service import MinerUService


def test_mineru_check_availability():
    """
    测试环境探测功能，能够返回正确的诊断字典格式
    """
    service = MinerUService()
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

    service = MinerUService()
    result = service.parse_file(file_path=str(word_fixture_path), task_id="test_unit_task_001")

    # 1. 验证结果结构完整
    assert result["task_id"] == "test_unit_task_001"
    assert result["file_name"] == "test_bidding.docx"
    assert os.path.exists(result["md_file_path"])

    # 2. 验证 Markdown 内容非空
    assert len(result["markdown_content"]) > 0
    assert "#" in result["markdown_content"]

    # 3. 验证结构化章节解析
    sections = result["sections"]
    assert len(sections) > 0
    assert any("title" in sec for sec in sections)

    # 4. 读取物理落盘的 md 文件，确认文件内容一致
    with open(result["md_file_path"], "r", encoding="utf-8") as f:
        saved_md = f.read()
    assert saved_md == result["markdown_content"]
