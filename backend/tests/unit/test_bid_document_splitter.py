"""
投标文件打分切分逻辑与层级 Path 继承单元测试 (test_bid_document_splitter.py)

测试重点：
1. 目录页 (TOC) 剥离与隔离测试：防止目录项误识别为正文大章碎块。
2. 动态层级 Path (L1 > L2 > L3) 状态机追踪与前缀注入测试。
3. 劣质/展平文本（缺少 # 标题样式）下的基于公文序号的规则层级恢复。
4. 正文描述性陈述（如“详见第八章”）防误判识别测试。
"""

import pytest
from app.services.extractor_service import ExtractorService


@pytest.fixture
def extractor():
    """初始化 ExtractorService 测试对象"""
    return ExtractorService()


def test_bid_document_toc_isolation_should_not_create_fragmented_chapters(extractor):
    """
    测试：投标文件开头的目录页 (TOC) 应当被识别并隔离，
    不应将目录页中的 "八、设计方案 ... 49" 误拆成碎片大章。
    """
    raw_md = (
        "# 目录\n"
        "一、投标函格式 .................................................... 1\n"
        "八、设计方案、施工方案 ............................................ 49\n"
        "  第一章 设计方案 ................................................ 49\n"
        "    第一节 项目可行性评估分析 .................................... 49\n\n"
        "一、投标函格式\n"
        "致采购单位：我方四川石楠建设工程有限公司决定参加本项目投标。\n\n"
        "八、设计方案、施工方案\n"
        "第一章 设计方案\n"
        "第一节 项目可行性评估分析\n"
        "本项目地处张家港市窑厂工业区，拟建设 840KW 分布式光伏发电站。\n"
    )

    chapters = extractor._group_markdown_text_by_chapter(raw_md, doc_type="bid")

    # 1. 第一个块应当是目录隔离块
    assert len(chapters) >= 2
    assert chapters[0]["title"] == "目录"
    assert chapters[0]["content_type"] == "toc_block"

    # 2. 正文大章应当顺序正确提取
    titles = [c["title"] for c in chapters]
    assert "一、投标函格式" in titles
    assert "第一节 项目可行性评估分析" in titles


def test_bid_document_hierarchy_path_tracking(extractor):
    """
    测试：深层正文段落应当继承多级 Path 堆栈 (L1 > L2 > L3)，
    切片 page_content 顶部应当自动注入 [所属章节: ...] 前缀说明。
    """
    raw_md = (
        "八、设计方案、施工方案\n"
        "第一章 设计方案\n"
        "第一节 项目可行性评估分析\n"
        "针对本工程项目特点，我方对光伏电池板防阴影遮挡进行精准测算。\n"
    )

    chapters = extractor._group_markdown_text_by_chapter(raw_md, doc_type="bid")
    assert len(chapters) == 3

    last_chapter = chapters[-1]
    expected_path = "八、设计方案、施工方案 > 第一章 设计方案 > 第一节 项目可行性评估分析"
    assert last_chapter["section_path"] == expected_path

    docs = extractor._adaptive_split_chapter(last_chapter, start_index=0, doc_type="bid")
    assert len(docs) == 1

    doc = docs[0]
    assert doc.metadata["section_path"] == expected_path
    assert f"[所属章节: {expected_path}]" in doc.page_content
    assert "防阴影遮挡进行精准测算" in doc.page_content


def test_bid_document_degraded_text_without_markdown_headers(extractor):
    """
    测试：在底层解析工具丢掉所有 Markdown '#' 样式时（劣质纯文本），
    依然能依靠中文序号探针成功恢复 L1 > L2 > L3 树状结构。
    """
    raw_md = (
        "十三、其他材料\n"
        "第一节 认证证书文件\n"
        "环境管理体系认证证书 ISO14001\n"
        "质量管理体系认证证书 ISO9001\n"
    )

    chapters = extractor._group_markdown_text_by_chapter(raw_md, doc_type="bid")
    assert len(chapters) == 2

    chap = chapters[-1]
    assert chap["section_path"] == "十三、其他材料 > 第一节 认证证书文件"

    docs = extractor._adaptive_split_chapter(chap, start_index=0, doc_type="bid")
    assert len(docs) == 1
    assert "十三、其他材料 > 第一节 认证证书文件" in docs[0].page_content


def test_bid_document_sentence_references_should_not_trigger_heading_state(extractor):
    """
    测试：正文描述中的句子（如“具体细节参见第八章的规定。”）
    不应当误触发章节切换。
    """
    raw_md = (
        "一、投标函格式\n"
        "我方承诺遵循相关条款，具体施工细节参见第八章的规定。\n"
        "相关项目质量要求遵循第一节的具体规定。\n"
    )

    chapters = extractor._group_markdown_text_by_chapter(raw_md, doc_type="bid")
    assert len(chapters) == 1

    chap = chapters[0]
    assert chap["title"] == "一、投标函格式"
    assert chap["section_path"] == "一、投标函格式"
    assert "具体施工细节参见第八章的规定" in chap["text"]


def test_non_toc_certificate_title_should_not_pollute_l1(extractor):
    """
    测试：不在目录白名单中的证书名（如“中国合格评定国家认可委员会实验室认可证书”）
    绝不应当升为 Level 1 霸占根节点，后续正文大章（如“七、售后服务方案”）必须清空并还原正确根节点。
    """
    raw_md = (
        "# 目录\n"
        "七、售后服务方案 ................................................. 103\n"
        "十三、其他材料 ................................................. 155\n\n"
        "十三、其他材料\n"
        "中国合格评定国家认可委员会实验室认可证书\n"
        "证书编号：CNAS L12345\n\n"
        "七、售后服务方案\n"
        "第一节 售后服务人员配置\n"
        "我方配置专职售后工程师 5 名。\n"
    )

    chapters = extractor._group_markdown_text_by_chapter(raw_md, doc_type="bid")

    # 查找“七、售后服务方案”块
    sh_chapters = [c for c in chapters if "售后服务" in c["section_path"]]
    assert len(sh_chapters) > 0
    for sc in sh_chapters:
        # 断言：售后服务方案节点绝对不能包含“中国合格评定...证书”前缀！
        assert "中国合格评定国家认可委员会实验室认可证书" not in sc["section_path"]
        assert sc["section_path"].startswith("七、售后服务方案")

