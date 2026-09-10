"""
BidFormatExtractorService 单元测试

测试投标文件格式抽取服务的正向模式、回退托底结构构建与关键词正则切片。
"""

import io
import os
import re
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


def test_slice_text_by_keywords_should_prefer_real_yingda_format_chapter_over_toc():
    """测试目录与正文均出现标题时，只截取正文“第四章 应答文件格式”范围。"""
    sample_text = """
目 录
第一章 招标公告 ................................ 1
第四章 应答文件格式 ............................ 88
第五章 评审办法 ................................ 90

第一章 招标公告
公告正文
第四章 应答文件格式
第一册 技术标
有效认证证书
第二册 商务标
法定代表人身份证明
第五章 评审办法
评审正文
"""

    sliced_text = bid_format_extractor_service._slice_text_by_keywords(sample_text)

    assert "第一册 技术标" in sliced_text
    assert "第二册 商务标" in sliced_text
    assert "评审正文" not in sliced_text
    assert "第四章 应答文件格式 ............................ 88" not in sliced_text


def test_slice_text_by_keywords_should_follow_dynamic_toc_chapter_identity():
    """测试章节编号变化时，根据目录条目动态匹配正文而非依赖固定章号。"""
    sample_text = """
目 录
第九章 响应文件格式 ................................ 42
第十章 合同条款 .................................... 56

第一章 项目概况
项目正文
第九章 响应文件格式
响应函
报价明细表
第十章 合同条款
合同正文
"""

    sliced_text = bid_format_extractor_service._slice_text_by_keywords(sample_text)

    assert "第九章 响应文件格式" in sliced_text
    assert "响应函" in sliced_text
    assert "合同正文" not in sliced_text


def test_slice_text_by_keywords_should_return_empty_when_target_chapter_missing():
    """测试规则未定位到目标章节时返回空文本，由上层决定将全文交给大模型定位。"""
    sample_text = "第一章 招标公告\n附件一：专用资质业绩要求\n评审办法前附表"

    assert bid_format_extractor_service._slice_text_by_keywords(sample_text) == ""


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


def test_bid_format_structure_should_accept_table_template_and_synonyms():
    """测试 BidFormatStructure 能够兼容 'table_template' 等 LLM 返回的同义词枚举并正常解析"""
    from app.schemas.bid_generator import BidFormatStructure, BidFormatSection, ContentTypeEnum

    raw_data = {
        "document_title": "张家港市渔光互补项目 - 投标文件格式模板",
        "source_chapter_name": "投标文件格式",
        "sections": [
            {
                "section_title": "附件一 投标函",
                "content_type": "text_template",
                "body_markdown": "致：招标人\n我方...",
                "placeholders": ["招标人"]
            },
            {
                "section_title": "附件二 开标一览表",
                "content_type": "table_template",  # 此处测试之前报错的 input_value='table_template'
                "body_markdown": "| 项目 | 金额 |\n| --- | --- |\n| 总计 | ___ |",
                "placeholders": ["金额"]
            },
            {
                "section_title": "附件三 资格审查表",
                "content_type": "checklist",
                "body_markdown": "- [ ] 营业执照",
                "placeholders": None  # 测试 None 占位符容错
            },
            {
                "section_title": "附件四 其他材料",
                "content_type": "custom_unknown_type",  # 测试未知枚举类型回退容错
                "body_markdown": None,  # 测试 None Markdown 容错
                "placeholders": "单一字符串占位符"  # 测试字符串转列表容错
            }
        ]
    }

    structure = BidFormatStructure(**raw_data)
    assert len(structure.sections) == 4
    assert structure.sections[0].content_type == ContentTypeEnum.TEXT_TEMPLATE
    assert structure.sections[1].content_type == ContentTypeEnum.FORM_TABLE
    assert structure.sections[2].content_type == ContentTypeEnum.CHECKLIST
    assert structure.sections[2].placeholders == []
    assert structure.sections[3].content_type == ContentTypeEnum.OTHER
    assert structure.sections[3].body_markdown == ""
    assert structure.sections[3].placeholders == ["单一字符串占位符"]


def test_extract_with_llm_and_rebuild_with_mocked_llm_json(monkeypatch):
    """测试 _extract_with_llm_and_rebuild 在 LLM 返回 table_template 时能成功构建 Word 文档"""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.id = "test-doc-id"
    mock_doc.filename = "光伏电站项目.pdf"
    mock_doc.tenant_id = "tenant-bid-format"
    mock_doc.parsed_metadata = {"md_file_path": ""}
    
    mock_db = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.content = "第六章 投标文件格式\n附件一 投标函\n致招标人：我方愿投标..."
    monkeypatch.setattr("app.services.bid_format_extractor_service.document_crud.get_document_chunks", lambda db, doc_id: [mock_chunk])

    # 模拟 LLM 返回包含 table_template 的 JSON
    mock_llm_service = MagicMock()
    mock_llm_service.is_configured_for_tenant.return_value = True
    mock_llm_service.generate_structured_json.return_value = {
        "document_title": "光伏电站项目 - 投标文件格式模板",
        "source_chapter_name": "第六章 投标文件格式",
        "sections": [
            {
                "section_title": "附件一 投标函",
                "content_type": "text_template",
                "body_markdown": "致招标人：我方愿投标...",
                "placeholders": ["投标报价"]
            },
            {
                "section_title": "附件二 分项报价表",
                "content_type": "table_template",
                "body_markdown": "| 序号 | 名称 | 数量 |\n| :--- | :--- | :--- |\n| 1 | 逆变器 | 10 |",
                "placeholders": []
            }
        ]
    }

    service = bid_format_extractor_service
    monkeypatch.setattr(service, "llm_service", mock_llm_service)
    
    docx_bytes, mode = service._extract_with_llm_and_rebuild(mock_db, mock_doc)
    assert docx_bytes is not None
    assert len(docx_bytes) > 0
    assert mode == "llm_rebuilt"
    mock_llm_service.is_configured_for_tenant.assert_called_once_with("tenant-bid-format")
    assert mock_llm_service.generate_structured_json.call_args.kwargs["tenant_id"] == "tenant-bid-format"


def test_extract_with_llm_should_use_full_text_when_target_chapter_missing(monkeypatch):
    """测试规则未定位到章节时，将全文交给大模型自行定位而不是生成基础模板。"""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.id = "test-missing-format-doc-id"
    mock_doc.filename = "缺少格式章节项目.pdf"
    mock_doc.tenant_id = "tenant-bid-format"
    mock_doc.parsed_metadata = {"md_file_path": ""}

    mock_db = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.content = "项目文件正文中使用非标准标题描述格式附件\n附件一：投标函\n投标人名称：______"
    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_chunks",
        lambda db, doc_id: [mock_chunk],
    )

    mock_llm_service = MagicMock()
    mock_llm_service.is_configured_for_tenant.return_value = True
    mock_llm_service.generate_structured_json.return_value = {
        "document_title": "格式模板",
        "source_chapter_name": "格式附件",
        "sections": [
            {
                "section_title": "附件一：投标函",
                "content_type": "text_template",
                "body_markdown": "投标人名称：______",
                "placeholders": ["投标人名称"],
            }
        ],
    }
    monkeypatch.setattr(bid_format_extractor_service, "llm_service", mock_llm_service)

    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.docx_exporter_service.export_bid_format_to_docx_bytes",
        lambda structure: b"llm-template",
    )

    docx_bytes, mode = bid_format_extractor_service._extract_with_llm_and_rebuild(mock_db, mock_doc)

    assert docx_bytes == b"llm-template"
    assert mode == "llm_rebuilt"
    mock_llm_service.generate_structured_json.assert_called_once()
    prompt = mock_llm_service.generate_structured_json.call_args.args[0]
    assert mock_chunk.content in prompt
    assert "全文" in prompt


def test_extract_with_llm_should_not_use_fallback_when_sections_are_empty(monkeypatch):
    """测试大模型未提取到章节时返回错误，不生成基础模板。"""
    from unittest.mock import MagicMock

    mock_doc = MagicMock()
    mock_doc.id = "test-empty-sections-doc-id"
    mock_doc.filename = "空结果测试项目.pdf"
    mock_doc.tenant_id = "tenant-bid-format"
    mock_doc.parsed_metadata = {"md_file_path": ""}

    mock_db = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.content = "原文中没有格式附件内容"
    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_chunks",
        lambda db, doc_id: [mock_chunk],
    )

    mock_llm_service = MagicMock()
    mock_llm_service.is_configured_for_tenant.return_value = True
    mock_llm_service.generate_structured_json.return_value = {
        "document_title": "空结果",
        "source_chapter_name": "未找到",
        "sections": [],
    }
    monkeypatch.setattr(bid_format_extractor_service, "llm_service", mock_llm_service)

    with pytest.raises(ValueError, match="未在原文中定位到可用"):
        bid_format_extractor_service._extract_with_llm_and_rebuild(mock_db, mock_doc)


def test_extract_with_llm_exception_should_raise_model_unavailable(monkeypatch):
    """测试模型调用异常时抛出可识别的模型不可用异常，不生成基础模板。"""
    from unittest.mock import MagicMock
    from app.services.llm_service import ModelUnavailableError

    mock_doc = MagicMock()
    mock_doc.id = "test-error-doc-id"
    mock_doc.filename = "异常测试项目.pdf"
    mock_doc.tenant_id = "tenant-bid-format"
    mock_doc.parsed_metadata = {"md_file_path": ""}
    
    mock_db = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.content = "第六章 投标文件格式\n附件一 投标函\n致招标人..."
    monkeypatch.setattr("app.services.bid_format_extractor_service.document_crud.get_document_chunks", lambda db, doc_id: [mock_chunk])

    # 模拟 LLM 抛出异常
    mock_llm_service = MagicMock()
    mock_llm_service.is_configured_for_tenant.return_value = True
    mock_llm_service.generate_structured_json.side_effect = RuntimeError("网络超时或 API 连接异常")

    service = bid_format_extractor_service
    monkeypatch.setattr(service, "llm_service", mock_llm_service)
    
    with pytest.raises(ModelUnavailableError, match="模型不可用"):
        service._extract_with_llm_and_rebuild(mock_db, mock_doc)
    mock_llm_service.is_configured_for_tenant.assert_called_once_with("tenant-bid-format")


def test_extract_and_export_should_use_bound_external_template(monkeypatch):
    """存在文档绑定模板时，应直接返回用户提供的 DOCX，不再切片招标原文。"""
    fixture_path = os.path.abspath("backend/tests/fixtures/test_bidding.docx")
    mock_doc = type(
        "DocumentStub",
        (),
        {
            "file_path": fixture_path,
            "filename": "招标项目.pdf",
            "tenant_id": "tenant-bid-format",
        },
    )()
    bound_template = type(
        "TemplateStub",
        (),
        {"id": "template-1", "file_path": fixture_path},
    )()
    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_by_id_system",
        lambda db, doc_id: mock_doc,
    )
    monkeypatch.setattr(
        "app.services.bid_template_service.bid_template_service.get_bound_template",
        lambda db, doc_id, tenant_id: bound_template,
    )

    docx_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
        db=object(),
        doc_id="document-1",
    )

    with open(fixture_path, "rb") as fixture_file:
        assert docx_bytes == fixture_file.read()
    assert filename == "招标项目_投标文件格式模板.docx"
    assert mode == "bound_external_template"


def test_extract_and_export_should_reuse_cached_original_template_before_reextract(monkeypatch):
    """用户先下载原格式模板后，Agent 再取模板时应直接复用缓存。"""
    from unittest.mock import MagicMock

    fixture_path = os.path.abspath("backend/tests/fixtures/test_bidding.docx")
    mock_doc = type(
        "DocumentStub",
        (),
        {
            "file_path": fixture_path,
            "filename": "招标项目.docx",
            "tenant_id": "tenant-bid-format",
        },
    )()
    cached_bytes = b"cached-original-template"

    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_by_id_system",
        lambda db, doc_id: mock_doc,
    )
    monkeypatch.setattr(
        "app.services.bid_template_service.bid_template_service.get_bound_template",
        lambda db, doc_id, tenant_id: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_read_cached_bid_format_template",
        lambda doc_id, source_file_path: (cached_bytes, "cached_native_docx"),
    )
    native_slice = MagicMock(side_effect=AssertionError("命中缓存后不应再次执行 Word 切片"))
    monkeypatch.setattr(bid_format_extractor_service, "_slice_docx_natively", native_slice)

    docx_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
        db=object(),
        doc_id="document-cache-1",
    )

    assert docx_bytes == cached_bytes
    assert filename == "招标项目_投标文件格式模板.docx"
    assert mode == "cached_native_docx"
    native_slice.assert_not_called()


def test_extract_and_export_should_skip_cache_when_force_reextract_is_enabled(monkeypatch):
    """测试强制重新提取时跳过缓存并返回新的原格式模板。"""
    from unittest.mock import MagicMock

    fixture_path = os.path.abspath("backend/tests/fixtures/test_bidding.docx")
    mock_doc = type(
        "DocumentStub",
        (),
        {
            "file_path": fixture_path,
            "filename": "招标项目.docx",
            "tenant_id": "tenant-bid-format",
        },
    )()
    cache_reader = MagicMock(return_value=(b"old-template", "cached_native_docx"))
    native_slice = MagicMock(return_value=b"fresh-template")

    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_by_id_system",
        lambda db, doc_id: mock_doc,
    )
    monkeypatch.setattr(
        "app.services.bid_template_service.bid_template_service.get_bound_template",
        lambda db, doc_id, tenant_id: None,
    )
    monkeypatch.setattr(bid_format_extractor_service, "_read_cached_bid_format_template", cache_reader)
    monkeypatch.setattr(bid_format_extractor_service, "_slice_docx_natively", native_slice)
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_cache_extracted_template",
        lambda doc_id, source_file_path, docx_bytes, filename, mode: (docx_bytes, filename, mode),
    )

    docx_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
        db=object(),
        doc_id="document-force-reextract-1",
        force_reextract=True,
    )

    assert docx_bytes == b"fresh-template"
    assert filename == "招标项目_投标文件格式模板.docx"
    assert mode == "native_docx"
    cache_reader.assert_not_called()
    native_slice.assert_called_once_with(fixture_path)


def test_slice_docx_natively_should_preserve_exact_word_elements(tmp_path):
    """测试原生 Word 切片模式能够准确切取第六章正文并排除前置章节与目录"""
    import os
    from docx import Document

    test_docx_path = str(tmp_path / "测试招标文件.docx")
    doc = Document()
    
    # 1. 模拟目录
    doc.add_paragraph("目  录")
    doc.add_paragraph("第一章 招标公告 .................... 1")
    doc.add_paragraph("第六章 投标文件格式 ................ 30")
    
    # 2. 模拟第一章正文
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("某某项目进行公开招标...")
    
    # 3. 模拟第六章正文（目标切片范围）
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件一 投标函")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "品名"
    table.rows[0].cells[1].text = "单价"
    table.rows[1].cells[0].text = "光伏组件"
    table.rows[1].cells[1].text = "1000"
    doc.add_paragraph("附件二 授权书")
    
    # 4. 模拟第七章正文（终止大章）
    doc.add_paragraph("第七章 评标办法")
    doc.add_paragraph("综合评分法细则...")

    doc.save(test_docx_path)

    # 执行原生 Word 切片
    docx_bytes = bid_format_extractor_service._slice_docx_natively(test_docx_path)
    assert docx_bytes is not None
    assert len(docx_bytes) > 0

    # 重新加载切片后的 docx 验证内容
    sliced_doc = Document(io.BytesIO(docx_bytes))
    all_text = "\n".join([p.text for p in sliced_doc.paragraphs])
    
    assert "第六章 投标文件格式" in all_text
    assert "附件一 投标函" in all_text
    assert "附件二 授权书" in all_text
    assert "第一章 招标公告" not in all_text
    assert "第七章 评标办法" not in all_text
    assert len(sliced_doc.tables) == 1


def test_slice_docx_natively_should_delegate_ambiguous_duplicate_headings_to_llm(
    tmp_path, monkeypatch
):
    """测试同一章节标题出现多次时，原生切片不擅自选点而交给大模型定位。"""
    from docx import Document

    test_docx_path = str(tmp_path / "重复标题文档.docx")
    doc = Document()
    doc.add_paragraph("目标章节")
    doc.add_paragraph("前置说明")
    doc.add_paragraph("目标章节")
    doc.add_paragraph("模板正文")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "待填写"
    doc.save(test_docx_path)

    service = bid_format_extractor_service
    monkeypatch.setattr(service, "chapter_start_patterns", [re.compile(r"^目标章节$")])

    assert service._slice_docx_natively(test_docx_path) is None


def test_extract_and_export_should_use_llm_native_locator_after_native_ambiguity(monkeypatch):
    """测试原生定位不确定时继续使用大模型章节定位并保留原始 DOCX 切片结果。"""
    from unittest.mock import MagicMock

    fixture_path = os.path.abspath("backend/tests/fixtures/test_bidding.docx")
    mock_doc = type(
        "DocumentStub",
        (),
        {
            "file_path": fixture_path,
            "filename": "招标项目.docx",
            "tenant_id": "tenant-bid-format",
        },
    )()

    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_by_id_system",
        lambda db, doc_id: mock_doc,
    )
    monkeypatch.setattr(
        "app.services.bid_template_service.bid_template_service.get_bound_template",
        lambda db, doc_id, tenant_id: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_read_cached_bid_format_template",
        lambda doc_id, source_file_path: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_slice_docx_natively",
        MagicMock(return_value=None),
    )
    llm_locator = MagicMock(return_value=b"llm-native-docx")
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_slice_docx_with_llm_locator",
        llm_locator,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_cache_extracted_template",
        lambda doc_id, source_file_path, docx_bytes, filename, mode: (
            docx_bytes,
            filename,
            mode,
        ),
    )

    docx_bytes, filename, mode = bid_format_extractor_service.extract_and_export_bid_format(
        db=object(),
        doc_id="document-llm-locator-1",
    )

    assert docx_bytes == b"llm-native-docx"
    assert filename == "招标项目_投标文件格式模板.docx"
    assert mode == "llm_located_native_docx"
    llm_locator.assert_called_once_with(fixture_path, tenant_id="tenant-bid-format")


def test_extract_and_export_should_not_generate_basic_template_when_word_locating_fails(
    monkeypatch,
):
    """测试 Word 原生切片和大模型定位均失败时直接报错，不伪造基础模板。"""
    fixture_path = os.path.abspath("backend/tests/fixtures/test_bidding.docx")
    mock_doc = type(
        "DocumentStub",
        (),
        {
            "file_path": fixture_path,
            "filename": "招标项目.docx",
            "tenant_id": "tenant-bid-format",
        },
    )()

    monkeypatch.setattr(
        "app.services.bid_format_extractor_service.document_crud.get_document_by_id_system",
        lambda db, doc_id: mock_doc,
    )
    monkeypatch.setattr(
        "app.services.bid_template_service.bid_template_service.get_bound_template",
        lambda db, doc_id, tenant_id: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_read_cached_bid_format_template",
        lambda doc_id, source_file_path: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_slice_docx_natively",
        lambda docx_path: None,
    )
    monkeypatch.setattr(
        bid_format_extractor_service,
        "_slice_docx_with_llm_locator",
        lambda docx_path, tenant_id=None: None,
    )

    with pytest.raises(RuntimeError, match="未生成基础模板"):
        bid_format_extractor_service.extract_and_export_bid_format(
            db=object(),
            doc_id="document-locating-failed-1",
        )


def test_llm_locator_should_slice_nonstandard_word_heading_by_existing_candidates(tmp_path, monkeypatch):
    """测试正则未识别书名号标题时，大模型只选标题候选并由原始 DOM 完成切片。"""
    from unittest.mock import MagicMock
    from docx import Document

    test_docx_path = str(tmp_path / "非标准标题招标文件.docx")
    doc = Document()
    doc.add_paragraph("目 录")
    doc.add_paragraph("第六章《投标文件编制格式》 ................ 30")
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("公告正文")

    format_heading = doc.add_paragraph("第六章《投标文件编制格式》")
    format_heading.style = "Heading 1"
    doc.add_paragraph("附件一 投标函")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "项目"
    table.rows[0].cells[1].text = "报价"
    table.rows[1].cells[0].text = "设备"
    table.rows[1].cells[1].text = "待填写"

    next_heading = doc.add_paragraph("第七章 评标办法")
    next_heading.style = "Heading 1"
    doc.add_paragraph("评审正文")
    doc.save(test_docx_path)

    service = bid_format_extractor_service
    assert service._slice_docx_natively(test_docx_path) is None

    candidates = service._extract_docx_heading_candidates(test_docx_path)
    start_candidate = next(
        candidate for candidate in candidates if candidate["title"] == "第六章《投标文件编制格式》"
    )
    end_candidate = next(
        candidate for candidate in candidates if candidate["title"] == "第七章 评标办法"
    )

    mock_llm_service = MagicMock()
    mock_llm_service.generate_structured_json.return_value = {
        "matched": True,
        "start_candidate_id": start_candidate["candidate_id"],
        "end_candidate_id": end_candidate["candidate_id"],
        "confidence": 0.96,
        "reason": "标题含格式语义，后续包含投标函和报价表",
    }
    monkeypatch.setattr(service, "llm_service", mock_llm_service)

    docx_bytes = service._slice_docx_with_llm_locator(test_docx_path, tenant_id="tenant-test")
    assert docx_bytes
    mock_llm_service.generate_structured_json.assert_called_once()
    assert mock_llm_service.generate_structured_json.call_args.kwargs["tenant_id"] == "tenant-test"

    sliced_doc = Document(io.BytesIO(docx_bytes))
    all_text = "\n".join(paragraph.text for paragraph in sliced_doc.paragraphs)
    assert "第六章《投标文件编制格式》" in all_text
    assert "附件一 投标函" in all_text
    assert "第七章 评标办法" not in all_text
    assert len(sliced_doc.tables) == 1


def test_llm_locator_should_reject_untrusted_candidate_id(tmp_path, monkeypatch):
    """测试大模型返回不在候选列表中的标题 ID 时，不执行任意 Word 切片。"""
    from unittest.mock import MagicMock
    from docx import Document

    test_docx_path = str(tmp_path / "无效定位结果.docx")
    doc = Document()
    heading = doc.add_paragraph("投标文件编制格式")
    heading.style = "Heading 1"
    doc.add_paragraph("附件一 投标函")
    doc.save(test_docx_path)

    mock_llm_service = MagicMock()
    mock_llm_service.generate_structured_json.return_value = {
        "matched": True,
        "start_candidate_id": "body_p_99999",
        "end_candidate_id": None,
        "confidence": 0.99,
        "reason": "模型自行生成的标题",
    }
    monkeypatch.setattr(bid_format_extractor_service, "llm_service", mock_llm_service)

    assert bid_format_extractor_service._slice_docx_with_llm_locator(test_docx_path) is None
