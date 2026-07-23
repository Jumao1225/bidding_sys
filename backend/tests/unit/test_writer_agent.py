import pytest
from unittest.mock import patch, MagicMock
from app.agents.nodes.writer_agent import (
    parse_font_size,
    FormattingSpec,
    BidDocOutline,
    OutlineItem,
    MergedStyles,
    WordGenerator,
)
from app.agents.nodes.writer_agent_node import writer_agent_node


def test_parse_font_size_chinese_and_numeric():
    """测试中文字号与数字磅值的解析转换"""
    assert parse_font_size("小四") == 12.0
    assert parse_font_size("三号") == 16.0
    assert parse_font_size("初号") == 42.0
    assert parse_font_size("14pt") == 14.0
    assert parse_font_size("28磅") == 28.0
    assert parse_font_size(None) is None


def test_merged_styles_three_tier_priority():
    """测试三层样式合并的优先级策略 (LLM 提取 > docx 读取 > 通用默认)"""
    # 场景 1: 完全使用通用默认值
    s1 = MergedStyles()
    assert s1.body_font == "宋体"
    assert s1.body_size_pt == 12.0
    assert s1.heading_font == "黑体"

    # 场景 2: 注入 docx 原文件样式
    docx_styles = {
        "default_font": "Times New Roman",
        "default_font_size_pt": 11.0
    }
    s2 = MergedStyles(docx_styles=docx_styles)
    assert s2.body_font == "Times New Roman"
    assert s2.body_size_pt == 11.0

    # 场景 3: 格式章节 LLM 提取的排版规范优先级最高
    spec = FormattingSpec(
        body_font="仿宋_GB2312",
        body_font_size="小三",
        heading_font="楷体",
        heading_font_size="二号",
        line_spacing="28磅"
    )
    s3 = MergedStyles(formatting_spec=spec, docx_styles=docx_styles)
    assert s3.body_font == "仿宋_GB2312"
    assert s3.body_size_pt == 15.0  # 小三
    assert s3.heading_font == "楷体"
    assert s3.h1_size_pt == 22.0     # 二号
    assert s3.line_spacing_pt == 28.0


def test_word_generator_draft_generation():
    """测试 WordGenerator 根据目录树生成完整的 docx 字节流"""
    styles = MergedStyles()
    generator = WordGenerator(styles=styles)

    outline = BidDocOutline(
        source_chapter="第七章 投标文件格式",
        outline=[
            OutlineItem(number="一", title="投标函", mapping_hint="bid_letter"),
            OutlineItem(number="二", title="法定代表人授权书", mapping_hint="authorization"),
            OutlineItem(number="三", title="商务报价清单", mapping_hint="cost"),
            OutlineItem(number="四", title="技术方案", mapping_hint="technical"),
            OutlineItem(number="五", title="自定义特别声明", mapping_hint="_unknown", content_hint="此项为测试说明"),
        ]
    )

    metadata = {
        "timeline": {"project_name": "某信息系统采购项目", "project_id_code": "PROJ-2026-001"},
        "engineering": {"main_equipment_list": [{"item_name": "核心服务器", "quantity": 2, "unit": "台"}]},
    }

    analysis = {
        "cost_analysis": {
            "total_cost": 150000.0,
            "budget_status": "预算可控",
            "items": [
                {
                    "name": "核心服务器",
                    "spec_requirement": "64核 256G内存",
                    "qty": 2.0,
                    "unit": "台",
                    "ref_price": 75000.0,
                    "subtotal": 150000.0,
                }
            ]
        }
    }

    docx_bytes = generator.generate_bidding_draft(outline=outline, metadata=metadata, analysis=analysis)
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 0


def test_word_generator_fallback_structure():
    """测试未识别到目录时自动回退为默认模版结构"""
    styles = MergedStyles()
    generator = WordGenerator(styles=styles)

    outline = BidDocOutline(source_chapter="未检测到", outline=[])
    docx_bytes = generator.generate_bidding_draft(outline=outline, metadata={}, analysis={})

    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 0


@patch("app.agents.nodes.writer_agent_node.SessionLocal")
@patch("app.agents.nodes.writer_agent_node.rag_service")
@patch("app.agents.nodes.writer_agent_node.llm_service")
@patch("app.worker.tasks.emit_agent_log")
def test_writer_agent_node_execution(mock_emit_log, mock_llm, mock_rag, mock_session):
    """测试 writer_agent_node 的全流程 Mock 执行"""
    mock_db = MagicMock()
    mock_session.return_value = mock_db

    mock_doc = MagicMock()
    mock_doc.file_path = "/tmp/test_doc.docx"
    mock_doc.parsed_metadata = {}
    mock_db.query.return_value.filter.return_value.first.return_value = mock_doc

    mock_rag.search_bidding_document.return_value = "第七章 投标文件格式：一、投标函 二、报价"

    mock_outline = BidDocOutline(
        source_chapter="第七章",
        outline=[
            OutlineItem(number="一", title="投标函", mapping_hint="bid_letter"),
            OutlineItem(number="二", title="报价清单", mapping_hint="cost")
        ]
    )
    mock_llm.generate_structured_output.return_value = mock_outline

    state = {
        "document_id": "test-doc-001",
        "user_id": "user-001",
        "tenant_id": "tenant-001",
        "company_quals": "测试公司能力说明"
    }

    result = writer_agent_node(state)

    assert result["completed_steps"] == ["writer_agent"]
    assert "draft_path" in result
    assert result["worker_summaries"][0]["status"] == "success"
