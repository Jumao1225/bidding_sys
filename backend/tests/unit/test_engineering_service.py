from html.parser import HTMLParser
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest

from app.services.metadata.engineering_service import (
    EquipmentItem,
    EngineeringSchema,
    EngineeringService,
    build_engineering_table_section_hints,
    extract_engineering_section_name_from_heading,
    normalize_engineering_section_name,
    _source_rows_from_context,
)


class _MineruTableParser(HTMLParser):
    """解析 MinerU 输出中的 HTML 表格行，保留单元格顺序。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录表格行和单元格的开始。"""
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        """收集单元格文本并折叠 OCR 产生的多余空白。"""
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """结束单元格或表格行并写入解析结果。"""
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            cell_text = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(cell_text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None


def _load_mineru_table_rows(marker: str) -> list[list[str]]:
    """从当前项目的 MinerU 输出中定位并解析包含指定标记的真实表格。"""
    output_root = Path(__file__).resolve().parents[2] / "uploads" / "mineru_output"
    matched_tables: list[str] = []
    for output_path in sorted(output_root.glob("*/output.md")):
        content = output_path.read_text(encoding="utf-8")
        if "张家港市凤凰镇杨家桥村10.88MW渔光互补项目" not in content:
            continue
        matched_tables.extend(
            table
            for table in re.findall(r"<table[\s\S]*?</table>", content)
            if marker in table
        )
    assert matched_tables, f"未在 MinerU 输出中找到包含 {marker!r} 的表格"

    parser = _MineruTableParser()
    parser.feed(matched_tables[0])
    return parser.rows


def _mineru_row_to_item(row: list[str], quantity_index: int = 4) -> EquipmentItem | None:
    """将 MinerU 表格中的有效编码行转换为清单模型。"""
    if len(row) <= quantity_index or not row[0] or not row[1]:
        return None
    # 排除表头和纯文字分组行，只把 PDF 中的章节号、整数序号和点号序号作为清单行。
    if not re.fullmatch(r"[（(][一二三四五六七八九十百千万]+[）)]|\d+(?:\.\d+)*", row[0]):
        return None
    quantity_text = row[quantity_index].strip()
    quantity = float(quantity_text) if re.fullmatch(r"\d+(?:\.\d+)?", quantity_text) else None
    return EquipmentItem(
        item_code=row[0],
        item_name=row[1],
        specifications=row[2] or None,
        unit=row[3] or None,
        quantity=quantity,
    )


def test_engineering_extraction_should_pass_tenant_to_table_scoped_llm_calls():
    """多张清单表应按表格边界调用模型，并为每次调用传递租户配置。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="测试设备", quantity=1, unit="项")]
    )

    # 使用两个最小表格验证默认聚合路径。
    source_context = "<table><tr><td>设备</td></tr></table>\n<table><tr><td>材料</td></tr></table>"

    with patch(
        "app.utils.table_utils.extract_equipment_tables_and_context",
        return_value=source_context,
    ), patch.object(service, "_save_to_db"), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ) as generate_mock, patch(
        "app.services.metadata.engineering_service.logger.info"
    ) as logger_info:
        service.extract_metadata(source_context, "document-a", tenant_id="tenant-a")

    assert generate_mock.call_count == 2
    assert all(call.kwargs["tenant_id"] == "tenant-a" for call in generate_mock.call_args_list)
    log_text = "\n".join(
        " ".join(str(arg) for arg in call.args)
        for call in logger_info.call_args_list
    )
    assert "大模型返回完整结构化结果" in log_text
    assert "测试设备" in log_text
    assert "工程清单最终归一化结果" in log_text


def test_engineering_extraction_with_empty_single_table_results_should_keep_model_empty():
    """模型单表返回为空时，后端不应从原始表格补造清单。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(main_equipment_list=[])
    source_context = (
        "<table><tr><th>序号</th><th>设备名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>台</td><td>1</td></tr></table>"
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db") as save_mock:
        result = service.extract_metadata(source_context, "document-a")

    assert result.main_equipment_list == []
    save_mock.assert_called_once_with("document-a", result)


def test_engineering_extraction_with_empty_table_scoped_results_should_degrade_to_no_table():
    """按表格隔离调用均为空时，应按无可提取清单正常落库。"""
    service = EngineeringService()
    mock_result = EngineeringSchema(main_equipment_list=[])
    source_context = (
        "<table><tr><th>设备名称</th><th>数量</th></tr><tr><td>设备A</td><td>1</td></tr></table>"
        "<table><tr><th>设备名称</th><th>数量</th></tr><tr><td>设备B</td><td>2</td></tr></table>"
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ) as generate_mock, patch.object(service, "_save_to_db") as save_mock:
        result = service.extract_metadata(source_context, "document-a")

    assert generate_mock.call_count == 2
    assert result.main_equipment_list == []
    save_mock.assert_called_once_with("document-a", result)


def test_engineering_schema_with_unknown_field_should_raise_validation_error():
    """顶层字段名错误时，应显式报错而不是降级为空清单。"""
    with pytest.raises(ValueError):
        EngineeringSchema.model_validate({"equipment_list": []})


def test_normalize_engineering_section_name_should_keep_semantic_name_only():
    """包装性清单标题只做结构归一化，不维护具体项目分区映射。"""
    assert normalize_engineering_section_name("项目需求清单（某分项）") == "某分项"
    assert normalize_engineering_section_name("自定义分区") == "自定义分区"
    assert normalize_engineering_section_name(None) is None


def test_normalize_engineering_section_name_should_remove_style_markers_only():
    """所属分项名称应移除字体样式标记，但保留单个技术星号。"""
    assert normalize_engineering_section_name("斜桥****工业二区****") == "斜桥工业二区"
    assert normalize_engineering_section_name("<span style='font-weight:bold'>某工业四区</span>") == "某工业四区"
    assert normalize_engineering_section_name("某分区 *1") == "某分区 *1"


def test_extract_engineering_section_name_should_prefer_local_area_over_table_wrapper():
    """最近的局部分区标题应优先于合同章节和清单包装标题。"""
    heading = (
        "## 二、项目主要标的物技术要求\n"
        "1、某区域\n"
        "1、项目需求清单（某部分）—以下清单为参考要求"
    )

    assert extract_engineering_section_name_from_heading(heading) == "某区域"


def test_extract_engineering_section_name_should_accept_unnumbered_area_heading():
    """不带序号的局部区域标题也应被识别为当前表格分区。"""
    heading = "## 二、项目主要标的物技术要求\n某工业四区"

    assert extract_engineering_section_name_from_heading(heading) == "某工业四区"


def test_extract_engineering_section_name_should_filter_font_markers_from_heading():
    """从表格前标题提取所属分项时，应过滤字体样式标记。"""
    heading = "## 二、项目主要标的物技术要求\n斜桥****工业二区****"

    assert extract_engineering_section_name_from_heading(heading) == "斜桥工业二区"


def test_extract_engineering_section_name_should_fallback_to_semantic_table_title():
    """没有局部分区标题时，应使用清单标题括号内的语义名称。"""
    heading = "## 二、项目主要标的物技术要求\n1、项目需求清单（某部分）"

    assert extract_engineering_section_name_from_heading(heading) == "某部分"


def test_build_engineering_table_section_hints_should_keep_numbered_requirement_titles():
    """多张清单表的编号标题应分别生成分区索引，保留括号内的语义分区。"""
    context = (
        "1、项目需求清单（一次侧部分）—以下清单设备参数为参考技术要求，数量为初步估算。\n"
        "<table><tr><th>序号</th><th>名称</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>1</td></tr></table>\n"
        "2、项目需求清单（二次侧部分）—以下清单设备参数为参考技术要求；数量为初步估算。\n"
        "<table><tr><th>序号</th><th>名称</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备B</td><td>1</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    hints = build_engineering_table_section_hints(context, table_matches)

    assert len(hints) == 2
    assert "表格 1" in hints[0]
    assert "候选分区=一次侧部分" in hints[0]
    assert "项目需求清单（一次侧部分）" in hints[0]
    assert "表格 2" in hints[1]
    assert "候选分区=二次侧部分" in hints[1]
    assert "项目需求清单（二次侧部分）" in hints[1]


def test_build_engineering_table_section_hints_should_include_inner_group_priority():
    """表内存在递进编码分组时，分区索引应同时提示更具体的内部分组。"""
    context = (
        "1、项目需求清单（某外层部分）—以下为参考技术要求。\n"
        "<table><tr><th>序号</th><th>名称</th><th>数量</th><th>单位</th></tr>"
        "<tr><td>(一)</td><td>某功能系统</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>某设备组</td><td></td><td></td></tr>"
        "<tr><td>1.1</td><td>某设备</td><td>1</td><td>台</td></tr>"
        "<tr><td>9</td><td>其它</td><td></td><td></td></tr>"
        "<tr><td>9.1</td><td>某预制舱</td><td>1</td><td>座</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    hints = build_engineering_table_section_hints(context, table_matches)

    assert len(hints) == 1
    assert "外层候选分区=某外层部分" in hints[0]
    assert "编码 (一) / 名称 某功能系统" in hints[0]
    assert "编码 9 / 名称 其它" in hints[0]


def test_engineering_extraction_should_fallback_invalid_section_to_source_heading():
    """模型返回非法分区时，应回退到当前表格的原文分区标题。"""
    service = EngineeringService()
    source_context = (
        "## 二、项目主要标的物技术要求\n"
        "1、某区域\n"
        "1、项目需求清单（某部分）\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>1</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_name="设备A",
                quantity=1,
                unit="台",
                section_name="一、合同标的",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-section")

    assert result.main_equipment_list[0].section_name == "某区域"


def test_engineering_extraction_should_keep_section_with_exact_source_evidence():
    """模型返回分区及其原文证据一致时，应保留分区字段。"""
    service = EngineeringService()
    source_context = (
        "## 二次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>1</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_name="设备A",
                quantity=1,
                unit="台",
                section_name="二次侧部分",
                section_evidence="二次侧部分",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-section-evidence")

    item = result.main_equipment_list[0]
    assert item.section_name == "二次侧部分"
    assert item.section_evidence == "二次侧部分"


def test_engineering_extraction_should_fallback_equipment_name_section_to_source_heading():
    """模型把设备名称当分区或证据来自设备行时，应回退到原文分区标题。"""
    service = EngineeringService()
    source_context = (
        "## 二次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>"
        "<tr><td>1</td><td>设备A</td><td>1</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_name="设备A",
                quantity=1,
                unit="台",
                section_name="设备A",
                section_evidence="设备A",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-invalid-section-evidence")

    item = result.main_equipment_list[0]
    assert item.section_name == "二次侧部分"
    assert item.section_evidence == "二次侧部分"


def test_engineering_extraction_should_fallback_parent_item_section_to_source_heading():
    """模型把表内计价父级名称当所属分区时，应回退到原文分区标题。"""
    service = EngineeringService()
    source_context = (
        "## 一次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>设备A</td><td>1</td><td>套</td></tr>"
        "<tr><td>1</td><td>子设备B</td><td>2</td><td>台</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="设备A", quantity=1, unit="套"),
            EquipmentItem(
                item_name="子设备B",
                quantity=2,
                unit="台",
                parent_item="设备A",
                section_name="设备A",
                section_evidence="设备A",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-parent-as-section")

    assert result.main_equipment_list[1].section_name == "一次侧部分"
    assert result.main_equipment_list[1].section_evidence == "一次侧部分"


def test_engineering_extraction_should_keep_outer_section_over_inner_group():
    """表内明确分组应通过 BOM 层级表达，section_name 仍保持外层分区。"""
    service = EngineeringService()
    source_context = (
        "1、项目需求清单（一次侧部分）—以下为参考技术要求。\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>数量</th><th>单位</th></tr>"
        "<tr><td>9</td><td>其它</td><td></td><td></td></tr>"
        "<tr><td>9.1</td><td>一次预制舱</td><td>1</td><td>座</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="其它"),
            EquipmentItem(
                item_name="一次预制舱",
                quantity=1,
                unit="座",
                section_name="其它",
                section_evidence="其它",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-inner-section")

    assert result.main_equipment_list[1].section_name == "一次侧部分"
    assert result.main_equipment_list[1].section_evidence == "一次侧部分"


def test_equipment_item_section_name_should_clear_non_string_or_sentence():
    """所属分项字段不是标题型字符串时，应统一置空。"""
    non_string_item = EquipmentItem(item_name="设备A", section_name=["二次侧部分"])
    sentence_item = EquipmentItem(item_name="设备B", section_name="该设备应满足现场安装及调试要求。")

    assert non_string_item.section_name is None
    assert sentence_item.section_name is None


def test_engineering_empty_extraction_should_not_overwrite_existing_items():
    """空提取结果不能覆盖数据库中已有的工程清单。"""
    service = EngineeringService()
    existing_record = MagicMock(main_equipment_list=[{"item_name": "已有设备"}])
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing_record

    with patch("app.db.session.SessionLocal", return_value=db):
        service._save_to_db(
            "document-existing",
            EngineeringSchema(main_equipment_list=[]),
        )

    db.commit.assert_not_called()


def test_engineering_prompt_should_keep_construction_and_service_boq_rows():
    """工程量清单提取 Prompt 必须覆盖施工、安装和服务类有效行项目。"""
    service = EngineeringService()
    source_context = (
        "<table><tr><th>序号</th><th>项目名称</th><th>单位</th><th>工程量</th></tr>"
        "<tr><td>3.1.6.1</td><td>电缆直埋</td><td>项</td><td>1.00</td></tr>"
        "<tr><td>3.1.7</td><td>交通工程</td><td>项</td><td>1.00</td></tr></table>"
        "在一级动火区域内使用二级动火工作票。工作负责人不在现场时不得作业。"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[EquipmentItem(item_name="电缆直埋", quantity=1, unit="项")]
    )

    with patch.object(
        service, "_save_to_db"
    ), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ) as generate_mock:
        service.extract_metadata(source_context, "document-boq")

    prompt = generate_mock.call_args.kwargs["prompt"]
    assert "BOM/BOQ 表格" in prompt
    assert "施工/服务行" in prompt
    assert "电缆直埋" in prompt
    assert "交通工程" in prompt
    assert "逐行核对要求（必须执行）" in prompt
    assert "缺少数量或单位不等于该行无效" in prompt
    assert "后端不会根据原始表格另行补造清单项" in prompt
    assert "安全生产制度、文明施工要求、岗位职责、人员分工" in prompt
    assert "在一级动火区域内使用二级动火工作票" not in prompt
    assert "原文没有数量时必须为 `null`" in prompt


def test_engineering_hierarchy_should_flatten_numbered_boq_siblings():
    """工程量清单分组标题下的连续编号行不应被误判为多级 BOM 子项。"""
    service = EngineeringService()
    items = [
        EquipmentItem(
            item_code="2.6",
            item_name="接地",
            parent_item="乙供设备及材料",
            root_item="乙供设备及材料",
            tree_level=2,
        ),
        EquipmentItem(
            item_code="2.6.1",
            item_name="接地绝缘铜绞线",
            quantity=22850,
            unit="m",
            parent_item="接地",
            root_item="乙供设备及材料",
            tree_level=3,
        ),
        EquipmentItem(
            item_code="2.6.2",
            item_name="接地绝缘铜绞线",
            quantity=3850,
            unit="m",
            parent_item="接地绝缘铜绞线",
            root_item="乙供设备及材料",
            tree_level=4,
        ),
        EquipmentItem(
            item_code="2.6.3",
            item_name="接地干线",
            quantity=25700,
            unit="m",
            parent_item="接地绝缘铜绞线",
            root_item="乙供设备及材料",
            tree_level=5,
        ),
    ]

    normalized = service._normalize_boq_hierarchy(items)

    assert [item.item_code for item in normalized] == ["2.6.1", "2.6.2", "2.6.3"]
    assert all(item.parent_item is None for item in normalized)
    assert all(item.root_item is None for item in normalized)
    assert all(item.tree_level == 1 for item in normalized)
    assert all(item.per_set_quantity is None for item in normalized)


def test_engineering_hierarchy_should_preserve_pdf_style_nested_bom():
    """PDF 明确存在“根项-总成-元件”结构时，应保留结构父级并修复直接父级。"""
    service = EngineeringService()
    items = [
        EquipmentItem(
            item_code="(二)",
            item_name="成套系统",
            quantity=4,
            unit="套",
        ),
        EquipmentItem(
            item_code="1",
            item_name="环网柜",
            quantity=4,
            unit="套",
            specifications="每套包含：柜内元件",
        ),
        EquipmentItem(
            item_code="1.1",
            item_name="断路器",
            quantity=4,
            unit="组",
            parent_item="错误的相邻项",
            per_set_quantity=1,
        ),
        EquipmentItem(
            item_code="2",
            item_name="变压器单元",
        ),
        EquipmentItem(
            item_code="2.1",
            item_name="升压变压器",
            quantity=4,
            unit="台",
            parent_item="成套系统",
            per_set_quantity=1,
        ),
    ]

    normalized = service._normalize_boq_hierarchy(items)
    normalized_by_code = {item.item_code: item for item in normalized}

    assert list(normalized_by_code) == ["(二)", "1", "1.1", "2", "2.1"]
    assert normalized_by_code["(二)"].parent_item is None
    assert normalized_by_code["1"].parent_item == "成套系统"
    assert normalized_by_code["1"].tree_level == 2
    assert normalized_by_code["1.1"].parent_item == "环网柜"
    assert normalized_by_code["1.1"].tree_level == 3
    assert normalized_by_code["2"].parent_item == "成套系统"
    assert normalized_by_code["2"].tree_level == 2
    assert normalized_by_code["2.1"].parent_item == "变压器单元"
    assert normalized_by_code["2.1"].tree_level == 3


def test_engineering_hierarchy_should_not_infer_parent_from_numbering_only():
    """只有递进编号而没有成套证据时，必须保持普通 BOQ 平级结构。"""
    service = EngineeringService()
    items = [
        EquipmentItem(item_code="(二)", item_name="项目清单", quantity=1, unit="项"),
        EquipmentItem(item_code="1", item_name="工程项目", quantity=1, unit="项"),
        EquipmentItem(item_code="1.1", item_name="施工子项", quantity=2, unit="项"),
    ]

    normalized = service._normalize_boq_hierarchy(items)

    assert [item.item_code for item in normalized] == ["(二)", "1", "1.1"]
    assert normalized[1].parent_item is None
    assert normalized[2].parent_item is None
    assert normalized[2].tree_level == 1


def test_engineering_hierarchy_should_stop_at_next_section_boundary():
    """新章节重新从 1 编号时，不应继承上一成套设备的父级。"""
    service = EngineeringService()
    items = [
        EquipmentItem(
            item_code="(九)",
            item_name="铁附件、电缆防火封堵",
            quantity=1,
            unit="项",
        ),
        EquipmentItem(
            item_code="1",
            item_name="铁附件",
            quantity=1,
            unit="吨",
            specifications="每套包含：附件",
        ),
        EquipmentItem(
            item_code="1.1",
            item_name="防火材料",
            quantity=1,
            unit="项",
            per_set_quantity=1,
        ),
        EquipmentItem(item_code="(十)", item_name="其它"),
        EquipmentItem(
            item_code="1",
            item_name="边锚桩",
            quantity=1,
            unit="根",
            parent_item="铁附件、电缆防火封堵",
            root_item="铁附件、电缆防火封堵",
            tree_level=2,
        ),
        EquipmentItem(
            item_code="2",
            item_name="边桩",
            quantity=1,
            unit="根",
            parent_item="铁附件、电缆防火封堵",
            root_item="铁附件、电缆防火封堵",
            tree_level=2,
        ),
    ]

    normalized = service._normalize_boq_hierarchy(items)
    edge_items = [item for item in normalized if item.item_name in {"边锚桩", "边桩"}]

    assert [item.item_name for item in normalized] == [
        "铁附件、电缆防火封堵",
        "铁附件",
        "防火材料",
        "边锚桩",
        "边桩",
    ]
    assert all(item.parent_item is None for item in edge_items)
    assert all(item.root_item is None for item in edge_items)
    assert all(item.tree_level == 1 for item in edge_items)


def test_engineering_hierarchy_should_match_pdf_bom_and_tujian_rows():
    """按用户 PDF 第 29、39 页条目验证成套 BOM 与土建清单的边界。"""
    service = EngineeringService()
    items = [
        EquipmentItem(
            item_code="(二)",
            item_name="2000kVA光伏升压箱变",
            quantity=4,
            unit="套",
        ),
        EquipmentItem(
            item_code="1",
            item_name="环网柜",
            quantity=1,
            unit="套",
            specifications="每套包含：",
        ),
        EquipmentItem(
            item_code="1.1",
            item_name="高压真空断路器",
            quantity=1,
            unit="组",
            per_set_quantity=1,
        ),
        EquipmentItem(
            item_code="1.2",
            item_name="隔离开关",
            quantity=1,
            unit="组",
            parent_item="高压真空断路器",
            per_set_quantity=1,
        ),
        EquipmentItem(
            item_code="1.3",
            item_name="氧化锌避雷器",
            quantity=3,
            unit="只",
            parent_item="隔离开关",
            per_set_quantity=3,
        ),
        EquipmentItem(item_code="2", item_name="10kV变压器"),
        EquipmentItem(
            item_code="2.1",
            item_name="10kV 升压变压器",
            quantity=1,
            unit="台",
            parent_item="2000kVA光伏升压箱变",
            per_set_quantity=1,
        ),
        EquipmentItem(item_code="(十)", item_name="其它"),
        EquipmentItem(
            item_code="1",
            item_name="边锚桩",
            unit="根",
            parent_item="2000kVA光伏升压箱变",
            root_item="2000kVA光伏升压箱变",
            tree_level=2,
        ),
        EquipmentItem(
            item_code="2",
            item_name="边桩",
            unit="根",
            parent_item="2000kVA光伏升压箱变",
            root_item="2000kVA光伏升压箱变",
            tree_level=2,
        ),
        EquipmentItem(
            item_code="3",
            item_name="中桩",
            unit="根",
            parent_item="2000kVA光伏升压箱变",
            root_item="2000kVA光伏升压箱变",
            tree_level=2,
        ),
    ]

    normalized = service._normalize_boq_hierarchy(items)
    normalized_by_name = {item.item_name: item for item in normalized}

    assert normalized_by_name["环网柜"].parent_item == "2000kVA光伏升压箱变"
    assert normalized_by_name["高压真空断路器"].parent_item == "环网柜"
    assert normalized_by_name["隔离开关"].parent_item == "环网柜"
    assert normalized_by_name["氧化锌避雷器"].parent_item == "环网柜"
    assert normalized_by_name["10kV 升压变压器"].parent_item == "10kV变压器"
    assert all(normalized_by_name[name].parent_item is None for name in ["边锚桩", "边桩", "中桩"])
    assert all(normalized_by_name[name].tree_level == 1 for name in ["边锚桩", "边桩", "中桩"])


def test_engineering_hierarchy_should_use_actual_mineru_tables_for_bom_boundary():
    """直接使用对应 MinerU 表格，验证箱变 BOM 与土建表之间不会串父级。"""
    primary_rows = _load_mineru_table_rows("2000kVA光伏升压箱变")
    civil_rows = _load_mineru_table_rows("边锚桩")

    bom_start = next(
        index
        for index, row in enumerate(primary_rows)
        if row and row[0] == "(二)" and "2000kVA光伏升压箱变" in row[1]
    )
    next_primary_section = next(
        index
        for index, row in enumerate(primary_rows[bom_start + 1 :], bom_start + 1)
        if row and row[0] == "(三)"
    )
    boundary_start = next(
        index
        for index, row in enumerate(primary_rows)
        if row and row[0] == "(九)"
    )

    bom_items = [
        item
        for item in (
            _mineru_row_to_item(row)
            for row in primary_rows[bom_start:next_primary_section]
        )
        if item is not None
    ]
    # MinerU 将“每套包含:”识别成了空编码行；按其实际表格位置归并到箱变根项。
    bom_items[0].specifications = "每套包含:"
    boundary_items = [
        item
        for item in (
            _mineru_row_to_item(row)
            for row in primary_rows[boundary_start:]
        )
        if item is not None
    ]
    civil_items = [
        item
        for item in (_mineru_row_to_item(row, quantity_index=5) for row in civil_rows)
        if item is not None
    ]

    assert len(civil_items) == 19
    assert [item.item_name for item in civil_items[:6]] == [
        "边锚桩",
        "边桩",
        "中桩",
        "稳定桩",
        "桥架桩",
        "固定支架桩",
    ]
    assert civil_items[7].quantity == 8.33904

    normalized = EngineeringService._normalize_boq_hierarchy(
        bom_items + boundary_items + civil_items
    )
    normalized_by_name = {item.item_name: item for item in normalized}

    assert normalized_by_name["环网柜"].parent_item == "2000kVA光伏升压箱变"
    assert normalized_by_name["高压真空断路器"].parent_item == "环网柜"
    assert normalized_by_name["10kV升压变压器"].parent_item == "10kV变压器"
    for civil_name in ["边锚桩", "边桩", "中桩", "固定支架桩"]:
        assert normalized_by_name[civil_name].parent_item is None
        assert normalized_by_name[civil_name].root_item is None
        assert normalized_by_name[civil_name].tree_level == 1


def test_engineering_hierarchy_should_preserve_actual_pdf_priced_section_children():
    """按 PDF 一次侧表的“导体和导线”分组验证无数量明细的父子级。"""
    rows = _load_mineru_table_rows("2000kVA光伏升压箱变")
    section_start = next(
        index for index, row in enumerate(rows) if row and row[0] == "(五)"
    )
    next_section = next(
        index
        for index, row in enumerate(rows[section_start + 1 :], section_start + 1)
        if row and row[0] == "(七)"
    )
    items = [
        item
        for item in (
            _mineru_row_to_item(row)
            for row in rows[section_start:next_section]
        )
        if item is not None
    ]

    normalized = EngineeringService._normalize_boq_hierarchy(items)
    normalized_by_code = {item.item_code: item for item in normalized}

    assert len(normalized) == 7
    assert normalized_by_code["(五)"].item_name == "导体和导线"
    assert normalized_by_code["(五)"].tree_level == 1
    for item_code in ["1", "2", "3", "4", "5", "6"]:
        assert normalized_by_code[item_code].parent_item == "导体和导线"
        assert normalized_by_code[item_code].root_item == "导体和导线"
        assert normalized_by_code[item_code].tree_level == 2


def test_engineering_hierarchy_should_restore_missing_section_parents_from_source_context():
    """模型漏返回括号分组行时，应依据原始表格恢复父项并阻断后续分组串挂。"""
    rows = _load_mineru_table_rows("导体和导线")
    source_path = next(
        path
        for path in (Path(__file__).resolve().parents[2] / "uploads" / "mineru_output").glob("*/output.md")
        if "导体和导线" in path.read_text(encoding="utf-8")
    )
    source_context = source_path.read_text(encoding="utf-8")

    start = next(index for index, row in enumerate(rows) if row and row[0] == "(五)")
    source_items = [
        item
        for item in (_mineru_row_to_item(row) for row in rows[start:])
        if item is not None
    ]
    # 模拟模型遗漏计价分组父行，并把所有明细错误继承到前一个分组。
    model_items = [
        item
        for item in source_items
        if item.item_code not in {"(五)", "(七)", "(九)"}
    ]
    for item in model_items:
        if re.fullmatch(r"\d+", item.item_code or ""):
            item.parent_item = "错误的前置分组"
            item.root_item = "错误的前置分组"
            item.tree_level = 2

    repaired = EngineeringService._repair_boq_hierarchy_from_source(model_items, source_context)
    normalized = EngineeringService._normalize_boq_hierarchy(repaired)
    normalized_by_name = {item.item_name: item for item in normalized}

    assert normalized_by_name["导体和导线"].quantity == 1
    assert normalized_by_name["接地部分"].quantity == 1
    assert normalized_by_name["铁附件、电缆防火封堵"].quantity == 1
    for item_name in ["10kV交流电缆", "10kV交流电缆终端", "0.4kV交流电缆", "0.4kV交流电缆终端"]:
        matching_items = [item for item in normalized if item.item_name == item_name]
        assert matching_items
        assert all(item.parent_item == "导体和导线" for item in matching_items)
    for item_name in ["铜覆扁钢", "铜覆钢垂直接地极", "绝缘铜绞线"]:
        assert normalized_by_name[item_name].parent_item == "接地部分"
    for item_name in ["铁附件", "电缆防火涂料", "有机堵料", "无机堵料", "防火隔板"]:
        assert normalized_by_name[item_name].parent_item == "铁附件、电缆防火封堵"
    for item_name in ["一次预制舱", "二次预制舱", "模拟图板", "安全生产准备"]:
        assert normalized_by_name[item_name].parent_item is None
        assert normalized_by_name[item_name].root_item is None
        assert normalized_by_name[item_name].tree_level == 1


@pytest.mark.parametrize(
    ("table_marker", "expected_row_count", "expected_names", "quantity_index"),
    [
        (
            "2000kVA光伏升压箱变",
            138,
            ["环网柜", "高压真空断路器", "10kV升压变压器"],
            4,
        ),
        (
            "电气二次部分",
            127,
            ["站控层设备", "就地监控系统", "远动通信柜"],
            4,
        ),
        (
            "通信部分(本体)",
            19,
            ["通信设备屏", "通信综合屏", "安装线缆"],
            4,
        ),
        (
            "光伏发电设备",
            30,
            ["太阳能光伏组件", "逆变器", "电缆连接器"],
            4,
        ),
        (
            "边锚桩",
            20,
            ["边锚桩", "固定支架桩", "主要标的物柔性支架", "临时设施费用"],
            5,
        ),
    ],
)
def test_engineering_all_pdf_bom_tables_should_match_mineru_source(
    table_marker: str,
    expected_row_count: int,
    expected_names: list[str],
    quantity_index: int,
):
    """五张 PDF BOM 表均应能从对应 MinerU 原始表格中完整定位关键行。"""
    rows = _load_mineru_table_rows(table_marker)

    assert len(rows) == expected_row_count
    table_text = "\n".join(" | ".join(row) for row in rows)
    assert all(expected_name in table_text for expected_name in expected_names)

    # 同时转换并归一化可计价编码行，确认每张真实表都能进入清单层级处理流程。
    items = [
        item
        for item in (_mineru_row_to_item(row, quantity_index=quantity_index) for row in rows)
        if item is not None
    ]
    assert items
    normalized = EngineeringService._normalize_boq_hierarchy(items)
    assert normalized


def test_engineering_extraction_should_keep_table_scoped_section_and_hierarchy():
    """多表同编码时，模型分区证据和父子关系都不能跨表串联。"""
    source_context = (
        "1、项目需求清单（区域A）\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>系统A</td><td></td><td>项</td><td>1</td></tr>"
        "<tr><td>1</td><td>设备A</td><td>规格A</td><td>台</td><td>2</td></tr></table>\n"
        "2、项目需求清单（区域B）\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>系统B</td><td></td><td>项</td><td>1</td></tr>"
        "<tr><td>1</td><td>设备B</td><td>规格B</td><td>台</td><td>3</td></tr></table>"
    )

    def generate_by_table(prompt: str, **_: object) -> EngineeringSchema:
        """模拟模型按当前表格返回内部分组及其原文证据。"""
        if "设备A" in prompt:
            return EngineeringSchema(
                main_equipment_list=[
                    EquipmentItem(
                        item_code="1",
                        item_name="设备A",
                        specifications="规格A",
                        quantity=2,
                        unit="台",
                        parent_item="系统A",
                        root_item="系统A",
                        tree_level=2,
                        section_name="系统A",
                        section_evidence="(一) 系统A",
                    )
                ]
            )
        return EngineeringSchema(
            main_equipment_list=[
                    EquipmentItem(
                        item_code="1",
                        item_name="设备B",
                        specifications="规格B",
                        quantity=3,
                        unit="台",
                        parent_item="系统B",
                        root_item="系统B",
                        tree_level=2,
                        section_name=None,
                    )
            ]
        )

    service = EngineeringService()
    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        side_effect=generate_by_table,
    ) as generate_mock, patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-table-scope")

    assert generate_mock.call_count == 2
    result_by_name = {item.item_name: item for item in result.main_equipment_list}
    assert result_by_name["设备A"].section_name == "区域A"
    assert result_by_name["设备B"].section_name == "区域B"
    assert result_by_name["设备A"].parent_item == "系统A"
    assert result_by_name["设备B"].parent_item == "系统B"
    assert result_by_name["设备A"].parent_item != result_by_name["设备B"].parent_item


def test_engineering_extraction_should_use_nearest_project_list_heading_for_whole_table():
    """表格上方的项目需求清单括号分区应覆盖整张表，不能被表内分类替换。"""
    service = EngineeringService()
    source_context = (
        "5、项目需求清单（土建配套部分）—以下清单材料规格为参考要求，"
        "支架工程量为初步估算，最终以深化设计方案及施工图纸工程量清单为准。\n"
        "<table><tr><th>序号</th><th>名称</th><th>描述</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>边锚桩</td><td>PHC600AB110-12</td><td>根</td><td>10</td></tr>"
        "<tr><td>2</td><td>固定支架</td><td>Q235B型钢</td><td>吨</td><td>2</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_name="边锚桩",
                quantity=10,
                unit="根",
                section_name="某内部分类",
                section_evidence="某内部分类",
            ),
            EquipmentItem(
                item_name="固定支架",
                quantity=2,
                unit="吨",
                section_name="支架材料",
                section_evidence="支架材料",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-civil-heading")

    assert {item.section_name for item in result.main_equipment_list} == {"土建配套部分"}
    assert {item.section_evidence for item in result.main_equipment_list} == {"土建配套部分"}


def test_engineering_extraction_should_not_restore_source_rows_when_model_omits_items():
    """模型漏返回部分清单行时，后端不应从原表补造缺失项目。"""
    service = EngineeringService()
    source_context = (
        "5、项目需求清单（土建配套部分）—以下清单材料规格为参考要求。\n"
        "<table><tr><th>序号</th><th>名称</th><th>描述</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>边锚桩</td><td>PHC600AB110-12</td><td>根</td><td></td></tr>"
        "<tr><td>2</td><td>边桩</td><td>PHC400AB95-18</td><td>根</td><td></td></tr>"
        "<tr><td>3</td><td>临时设施费用</td><td>综合考虑</td><td>项</td><td>1</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="1",
                item_name="边锚桩",
                specifications="PHC600AB110-12",
                unit="根",
                section_name="土建配套部分",
                section_evidence="土建配套部分",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-source-row-repair")

    result_by_name = {item.item_name: item for item in result.main_equipment_list}
    assert set(result_by_name) == {"边锚桩"}
    assert result_by_name["边锚桩"].specifications == "PHC600AB110-12"
    assert all(item.section_name == "土建配套部分" for item in result.main_equipment_list)


def test_source_rows_should_expand_rowspan_and_keep_continuation_items():
    """跨行合并的编码、名称和备注不能导致后续明细行丢失。"""
    source_context = (
        "4、项目需求清单（直流侧）\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th><th>备注</th></tr>"
        "<tr><td rowspan='2'>2.2</td><td rowspan='2'>低压电缆</td><td>3*185</td><td>m</td><td></td><td rowspan='2'>按设计</td></tr>"
        "<tr><td>3*240</td><td>m</td><td></td></tr></table>"
    )

    tables = _source_rows_from_context(source_context)

    assert len(tables) == 1
    assert [(row.item_code, row.item_name, row.specifications) for row in tables[0]] == [
        ("2.2", "低压电缆", "3*185"),
        ("2.2", "低压电缆", "3*240"),
    ]


def test_engineering_section_evidence_should_match_html_cells_after_tag_removal():
    """HTML 单元格标签不应阻断模型返回的表内分组证据。"""
    item = EquipmentItem(
        item_name="设备A",
        section_name="系统A",
        section_evidence="(一) 系统A",
    )
    source_context = (
        "<table><tr><th>序号</th><th>名称</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>系统A</td><td></td></tr>"
        "<tr><td>1</td><td>设备A</td><td>1</td></tr></table>"
    )

    from app.services.metadata.engineering_service import validate_engineering_section_evidence

    assert validate_engineering_section_evidence(item, source_context, {"设备A"}) is True
