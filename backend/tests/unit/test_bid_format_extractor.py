"""
BidFormatExtractorService 单元测试

测试投标文件格式抽取服务的正向模式、回退托底结构构建与关键词正则切片。
"""

import pytest
from app.services.bid_format_extractor_service import bid_format_extractor_service


def test_build_fallback_structure_should_contain_essential_bid_sections():
    """测试托底架构构建，确保包含投标函、授权书与报价汇总表等核心格式"""
    structure = bid_format_extractor_service._build_fallback_structure("智慧园区建设工程招标文件.pdf")
    
    assert "智慧园区建设工程招标文件" in structure.document_title
    assert len(structure.sections) >= 3
    section_titles = [s.section_title for s in structure.sections]
    assert any("投标函" in t for t in section_titles)
    assert any("授权" in t for t in section_titles)
    assert any("开标一览表" in t for t in section_titles)


def test_slice_text_by_keywords_should_locate_bid_format_chapter():
    """测试在多章节大文本中，正则匹配定位'投标文件格式'章节起止范围"""
    sample_text = """
第一章 招标公告
本工程项目......

第二章 投标人须知
投标人必须具备......

第六章 投标文件格式
附件一：投标函
致：采购人......

附件二：法定代表人授权书
    """
    sliced_text = bid_format_extractor_service._slice_text_by_keywords(sample_text)
    assert "第六章 投标文件格式" in sliced_text
    assert "附件一：投标函" in sliced_text
    assert "第一章 招标公告" not in sliced_text


def test_is_toc_line_should_correctly_identify_table_of_contents_lines():
    """测试 _is_toc_line 能否精准判断带-3- / -55- 及第一卷等目录连点页码行，防止误杀切片"""
    toc_line_1 = "第六章 投标文件格式 .................... 40"
    toc_line_2 = "第七章 合同条款................................... 55"
    toc_line_3 = "第六章 投标文件格式\t40"
    toc_line_4 = "第一章 招标公告........................-3-"
    toc_line_5 = "第六章 投标文件格式....................-55-"
    toc_line_vol = "第一卷"

    body_line_1 = "第六章 投标文件格式"
    body_line_2 = "附件一 投标函"

    assert bid_format_extractor_service._is_toc_line(toc_line_1) is True
    assert bid_format_extractor_service._is_toc_line(toc_line_2) is True
    assert bid_format_extractor_service._is_toc_line(toc_line_3) is True
    assert bid_format_extractor_service._is_toc_line(toc_line_4) is True
    assert bid_format_extractor_service._is_toc_line(toc_line_5) is True
    assert bid_format_extractor_service._is_toc_line(toc_line_vol) is True

    assert bid_format_extractor_service._is_toc_line(body_line_1) is False
    assert bid_format_extractor_service._is_toc_line(body_line_2) is False


def test_is_real_next_main_chapter_should_distinguish_main_chapters_from_attachments():
    """测试 _is_real_next_main_chapter 能否区分真实独立大章与格式附件内部子标题"""
    real_chapter_1 = "第七章 评标办法"
    real_chapter_2 = "第七章 合同条款"
    
    internal_sub_1 = "附件七 承诺函"
    internal_sub_2 = "格式七 授权委托书"
    internal_sub_3 = "第七部分 商务响应表"

    assert bid_format_extractor_service._is_real_next_main_chapter(real_chapter_1) is True
    assert bid_format_extractor_service._is_real_next_main_chapter(real_chapter_2) is True

    assert bid_format_extractor_service._is_real_next_main_chapter(internal_sub_1) is False
    assert bid_format_extractor_service._is_real_next_main_chapter(internal_sub_2) is False
    assert bid_format_extractor_service._is_real_next_main_chapter(internal_sub_3) is False


