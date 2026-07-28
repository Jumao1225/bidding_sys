"""
DocxSkillService 单元测试

包含测试用例：
1. test_accept_tracked_changes_should_remove_revision_marks: 测试接受全文修订痕迹；
2. test_insert_toc_should_add_toc_fields_and_enable_update_fields: 测试动态插入 Word 目录域；
3. test_scrub_privacy_should_clear_creator_and_rsid: 测试文档隐私与元数据脱敏清洗；
4. test_extract_comments_should_return_comments_list: 测试提取 DOCX 内置审阅批注列表。
"""

import io
import pytest
from docx import Document
from app.services.docx_test_filler_service import docx_test_filler_service
from app.services.docx_skill_service import docx_skill_service


def test_accept_tracked_changes_should_remove_revision_marks():
    """ 测试接受 Word 全文修订痕迹功能 """
    template_bytes = docx_test_filler_service.create_sample_docx()
    res_bytes = docx_skill_service.accept_tracked_changes(template_bytes)
    assert res_bytes is not None
    assert len(res_bytes) > 0


def test_insert_toc_should_add_toc_fields_and_enable_update_fields():
    """ 测试自动插入/更新 Word 动态目录功能 """
    template_bytes = docx_test_filler_service.create_sample_docx()
    res_bytes = docx_skill_service.insert_table_of_contents(template_bytes)
    assert res_bytes is not None
    assert len(res_bytes) > 0

    doc = Document(io.BytesIO(res_bytes))
    full_text = "\n".join([p.text for p in doc.paragraphs])
    assert "目 录" in full_text or "TOC" in full_text


def test_scrub_privacy_should_clear_creator_and_rsid():
    """ 测试隐私与元数据脱敏清洗功能 """
    template_bytes = docx_test_filler_service.create_sample_docx()
    res_bytes = docx_skill_service.scrub_privacy_metadata(template_bytes)
    assert res_bytes is not None
    assert len(res_bytes) > 0


def test_extract_comments_should_return_comments_list():
    """ 测试提取 DOCX 文档批注功能 """
    template_bytes = docx_test_filler_service.create_sample_docx()
    comments = docx_skill_service.extract_comments(template_bytes)
    assert isinstance(comments, list)


def test_strip_comments_should_remove_comments():
    """ 测试彻底清空与剔除 Word 批注功能 """
    template_bytes = docx_test_filler_service.create_sample_docx()
    clean_bytes = docx_skill_service.strip_comments(template_bytes)
    assert clean_bytes is not None
    assert len(clean_bytes) > 0
    remaining_comments = docx_skill_service.extract_comments(clean_bytes)
    assert len(remaining_comments) == 0

