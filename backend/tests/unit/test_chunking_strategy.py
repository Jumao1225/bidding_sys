"""
文档切分策略单元测试

测试 ExtractorService 的核心方法：
- _detect_chapter_title: 章节标题正则检测
- _group_chunks_by_chapter: 按章节归组
- _adaptive_split_chapter: 超长章节自适应再分块
"""
import pytest
import json
import os
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.extractor_service import (
    ExtractorService,
    MAX_CHUNK_SIZE,
    CHUNK_OVERLAP,
)


# ========== Mock 对象：模拟 Docling HierarchicalChunker 的输出结构 ==========

@dataclass
class MockProv:
    """模拟 Docling 的 Provenance 对象"""
    page_no: int = 1


@dataclass
class MockDocItem:
    """模拟 Docling 的 DocItem 对象"""
    label: str = "text"
    prov: List[MockProv] = field(default_factory=lambda: [MockProv()])


@dataclass
class MockChunkMeta:
    """模拟 Docling 的 ChunkMeta 对象"""
    headings: List[str] = field(default_factory=list)
    doc_items: List[MockDocItem] = field(default_factory=lambda: [MockDocItem()])


@dataclass
class MockChunk:
    """模拟 Docling HierarchicalChunker 输出的单个 Chunk"""
    text: str = ""
    meta: MockChunkMeta = field(default_factory=MockChunkMeta)


def _build_mock_chunk(text: str, headings: list, page_no: int = 1, label: str = "text") -> MockChunk:
    """辅助函数：快速构建一个 MockChunk 对象"""
    return MockChunk(
        text=text,
        meta=MockChunkMeta(
            headings=headings,
            doc_items=[MockDocItem(label=label, prov=[MockProv(page_no=page_no)])]
        )
    )


@pytest.fixture
def extractor():
    """创建一个 ExtractorService 实例（不初始化 Docling Converter）"""
    return ExtractorService()


@pytest.fixture
def fixture_data():
    """加载测试 fixture 数据"""
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mock_chunker_data.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ========== 测试 _detect_chapter_title ==========

class TestDetectChapterTitle:
    """章节标题正则检测测试"""

    def test_detect_standard_chapter_should_return_title(self, extractor):
        """正常情况：标准「第X章」格式应被正确识别"""
        result = extractor._detect_chapter_title("第一章 招标公告\n详细内容...")
        assert result is not None
        assert "第一章" in result

    def test_detect_section_format_should_return_title(self, extractor):
        """正常情况：「第X节」格式应被正确识别"""
        result = extractor._detect_chapter_title("第二节 评标办法")
        assert result is not None
        assert "第二节" in result

    def test_detect_chinese_number_format_should_not_be_major_chapter(self, extractor):
        """规则说明：「一、标题」属于 2 级小节，不应触发独立大章分割 (返回 None)"""
        result = extractor._detect_chapter_title("一、投标须知")
        assert result is None

    def test_detect_attachment_format_should_return_title(self, extractor):
        """正常情况：「附件X」格式应被识别为独立大章"""
        result = extractor._detect_chapter_title("附件一 投标文件格式")
        assert result is not None
        assert "附件" in result

    def test_detect_parenthesis_format_should_not_be_major_chapter(self, extractor):
        """规则说明：「（一）」属于 3 级小节，不应触发独立大章分割 (返回 None)"""
        result = extractor._detect_chapter_title("（一）投标报价要求")
        assert result is None

    def test_detect_toc_entry_should_return_none(self, extractor):
        """异常情况：目录项（以页码数字结尾）应被排除"""
        result = extractor._detect_chapter_title("第一章 招标公告 .................. 3")
        assert result is None

    def test_detect_plain_text_should_return_none(self, extractor):
        """边界情况：普通正文不应被识别为标题"""
        result = extractor._detect_chapter_title("本项目采用公开招标方式。")
        assert result is None

    def test_detect_long_text_should_return_none(self, extractor):
        """边界情况：超长文本（>100字）不应被识别为标题"""
        long_title = "第一章 " + "详" * 200
        result = extractor._detect_chapter_title(long_title)
        assert result is None

    def test_detect_markdown_formatted_should_return_clean_title(self, extractor):
        """正常情况：带 Markdown 格式符号的标题应返回清理后的纯文本"""
        result = extractor._detect_chapter_title("**第四章 项目需求**")
        assert result is not None
        assert "*" not in result
        assert "第四章" in result


# ========== 测试 _group_chunks_by_chapter ==========

class TestGroupChunksByChapter:
    """按章节归组测试"""

    def test_group_multi_chapter_doc_should_separate_chapters(self, extractor, fixture_data):
        """正常情况：多章节文档应精确按独立大章 (第一章、第二章、附件一等) 进行聚合归组"""
        raw_data = fixture_data["multi_chapter_doc"]["chunks"]
        mock_chunks = [
            _build_mock_chunk(c["text"], c["headings"], c["page_no"], c["label"])
            for c in raw_data
        ]

        chapters = extractor._group_chunks_by_chapter(mock_chunks)

        # 应至少识别出 3 个独立大章 (第一章、第二章、附件一)
        assert len(chapters) >= 3

        # 验证大章标题
        titles = [ch["title"] for ch in chapters]
        assert any("第一章" in t for t in titles), f"应识别到第一章大章，实际标题: {titles}"
        assert any("第二章" in t for t in titles), f"应识别到第二章大章，实际标题: {titles}"
        assert any("附件" in t for t in titles), f"应识别到附件大章，实际标题: {titles}"

        # 验证 trace_info 中的结构元数据
        sample_trace = chapters[0]["trace_info"]
        assert "chapter" in sample_trace
        assert "headings" in sample_trace

    def test_group_hierarchical_sections_should_keep_in_same_major_chapter(self, extractor):
        """正常情况：同属第一章内部的小节 (一、/二、) 应完整归属于第一章大章，不被切碎"""
        mock_chunks = [
            _build_mock_chunk("第一章 投标邀请\n招标项目名称：光伏项目。", ["第一章 投标邀请", "一、招标项目名称及编号"], 1),
            _build_mock_chunk("二、供应商资格要求\n必须具备独立法人资格。", ["第一章 投标邀请", "二、供应商资格要求"], 1),
        ]

        chapters = extractor._group_chunks_by_chapter(mock_chunks)

        # 两个小节均属于第一章，应聚合为 1 个完整的大章 Block
        assert len(chapters) == 1
        assert chapters[0]["title"] == "第一章 投标邀请"
        assert "光伏项目" in chapters[0]["text"]
        assert "独立法人资格" in chapters[0]["text"]

    def test_group_same_chapter_chunks_should_merge_text(self, extractor):
        """正常情况：属于同一章节路径的碎片应合并到一起"""
        mock_chunks = [
            _build_mock_chunk("第一章 概述\n项目背景。", ["第一章 概述"], 1),
            _build_mock_chunk("项目目标是建设智慧城市。", ["第一章 概述"], 1),
            _build_mock_chunk("项目预算为5000万元。", ["第一章 概述"], 2),
        ]

        chapters = extractor._group_chunks_by_chapter(mock_chunks)

        assert len(chapters) == 1
        assert "项目背景" in chapters[0]["text"]
        assert "项目目标" in chapters[0]["text"]
        assert "项目预算" in chapters[0]["text"]

    def test_group_inner_line_chapter_header_should_split_correctly(self, extractor):
        """核心修复测试：当 Raw Chunk 内部中间行 (如第3行) 出现新大章标题时，应自动将其精准切分为两个不同的大章"""
        embedded_chunk = _build_mock_chunk(
            "法定代表人（或负责人）或授权代表：\n"
            "签署日期： 年 月 日\n"
            "**第四章 项目需求**\n"
            "**一、项目说明**\n"
            "1.1 项目简介：分布式光伏项目。",
            headings=["第三章 合同条款及格式"],
            page_no=1
        )

        chapters = extractor._group_chunks_by_chapter([embedded_chunk])

        # 应识别出第三章落款与第四章开头的两个独立大章
        assert len(chapters) == 2
        titles = [ch["title"] for ch in chapters]
        assert "第三章 合同条款及格式" in titles[0]
        assert "第四章 项目需求" in titles[1]
        assert "法定代表人" in chapters[0]["text"]
        assert "分布式光伏项目" in chapters[1]["text"]

    def test_group_no_title_chunks_should_use_default(self, extractor, fixture_data):
        """边界情况：无标题文档应全部归入默认章节"""
        raw_data = fixture_data["no_title_doc"]["chunks"]
        mock_chunks = [
            _build_mock_chunk(c["text"], c["headings"], c["page_no"], c["label"])
            for c in raw_data
        ]

        chapters = extractor._group_chunks_by_chapter(mock_chunks)

        assert len(chapters) == 1
        assert chapters[0]["title"] == "无章节/正文"


# ========== 测试 _adaptive_split_chapter ==========

class TestAdaptiveSplitChapter:
    """超长章节自适应再分块测试"""

    def test_split_short_chapter_should_produce_single_chunk(self, extractor):
        """正常情况：短章节（<= MAX_CHUNK_SIZE）应产出单个 Chunk"""
        chapter = {
            "title": "第一章 概述",
            "text": "这是一个短章节。" * 10,
            "page_start": 1,
            "content_type": "chapter_block",
            "trace_info": {"headings": ["第一章 概述"], "element_label": "text"},
        }

        docs = extractor._adaptive_split_chapter(chapter, start_index=0)

        assert len(docs) == 1
        assert docs[0].metadata["section_title"] == "第一章 概述"
        assert docs[0].metadata["chunk_index"] == 0

    def test_split_long_chapter_should_produce_multiple_chunks(self, extractor):
        """正常情况：长章节（> MAX_CHUNK_SIZE）应产出多个子块"""
        # 构造一段超过 MAX_CHUNK_SIZE 的文本
        long_text = "本项目需要建设智慧城市综合管理平台。" * 200  # 约 3600 字
        chapter = {
            "title": "第三章 技术要求",
            "text": long_text,
            "page_start": 6,
            "content_type": "chapter_block",
            "trace_info": {"headings": ["第三章 技术要求"], "element_label": "text"},
        }

        docs = extractor._adaptive_split_chapter(chapter, start_index=5)

        # 应产出多个子块
        assert len(docs) > 1

        # 验证所有子块都继承了父章节的 section_title
        for doc in docs:
            assert doc.metadata["section_title"] == "第三章 技术要求"

        # 验证 chunk_index 连续递增
        for i, doc in enumerate(docs):
            assert doc.metadata["chunk_index"] == 5 + i

        # 验证每个子块长度不超过 MAX_CHUNK_SIZE + 合理容差
        for doc in docs:
            assert len(doc.page_content) <= MAX_CHUNK_SIZE + 100, \
                f"子块长度 {len(doc.page_content)} 超过阈值 {MAX_CHUNK_SIZE}"

    def test_split_empty_chapter_should_produce_no_chunks(self, extractor):
        """边界情况：空章节应产出 0 个 Chunk"""
        chapter = {
            "title": "空章节",
            "text": "   ",
            "page_start": 1,
            "content_type": "chapter_block",
            "trace_info": {"headings": [], "element_label": "text"},
        }

        docs = extractor._adaptive_split_chapter(chapter, start_index=0)

        assert len(docs) == 0

    def test_split_preserves_page_info(self, extractor):
        """正常情况：分块后应保留页码信息"""
        chapter = {
            "title": "第五章 评标",
            "text": "评标采用综合评分法。" * 10,
            "page_start": 15,
            "content_type": "chapter_block",
            "trace_info": {"headings": ["第五章 评标"], "element_label": "text"},
        }

        docs = extractor._adaptive_split_chapter(chapter, start_index=0)

        for doc in docs:
            assert doc.metadata["page_num"] == 15

    def test_split_table_block_should_not_be_split(self, extractor):
        """核心规则：Markdown 表格块在切分时必须保持整块完整，禁止跨行跨表切断"""
        table_markdown = (
            "| 序号 | 货物名称 | 规格型号 | 数量 | 单价 |\n"
            "|---|---|---|---|---|\n"
            "| 1 | 光伏逆变器 | 400kW 组串式 | 2 | 50000 |\n"
            "| 2 | 光伏组件 | 550W 单晶 | 720 | 800 |\n"
            "| 3 | 交流配电柜 | 400V 柜体 | 1 | 12000 |\n"
        )
        long_prefix = "这里是表格前的描述文本。" * 80
        long_suffix = "这里是表格后的说明文本。" * 80
        chapter_text = f"{long_prefix}\n\n{table_markdown}\n\n{long_suffix}"

        chapter = {
            "title": "第三章 规格参数",
            "text": chapter_text,
            "page_start": 5,
            "content_type": "chapter_block",
            "trace_info": {"headings": ["第三章 规格参数"], "element_label": "text"},
        }

        docs = extractor._adaptive_split_chapter(chapter, start_index=0)

        # 找到包含表格的 Chunk
        table_docs = [doc for doc in docs if "| 序号 | 货物名称 |" in doc.page_content]
        assert len(table_docs) == 1, "包含表格的 Chunk 应当且仅有 1 个（表格保持完整）"
        
        # 验证该 Chunk 包含了完整的表格行
        table_content = table_docs[0].page_content
        assert "| 1 | 光伏逆变器 |" in table_content
        assert "| 2 | 光伏组件 |" in table_content
        assert "| 3 | 交流配电柜 |" in table_content
