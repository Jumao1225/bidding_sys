from html.parser import HTMLParser
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest

from app.services.metadata.engineering_service import (
    EquipmentItem,
    EngineeringSchema,
    EngineeringService,
    _build_table_parts_with_internal_group_state,
    _build_table_scoped_engineering_chunks,
    build_engineering_table_section_hints,
    extract_engineering_section_name_from_heading,
    normalize_engineering_section_name,
    resolve_engineering_table_grouping_mode,
    _extract_inner_section_candidates,
    _collect_source_measurement_names,
    _parse_source_composition_components,
    _source_rows_from_context,
    _is_likely_external_table_continuation,
    _deduplicate_equipment_items,
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
    assert "分块 1 结构化结果" in log_text
    assert "测试设备" in log_text
    assert "工程清单最终归一化结果" in log_text


def test_resolve_engineering_table_grouping_mode_should_prioritize_external_heading():
    """同一张表同时存在两类上下文时优先使用表格前置分区。"""
    table = """
    <table>
      <tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>
      <tr><td>1</td><td>表内分组</td><td></td><td></td></tr>
      <tr><td>1.1</td><td>明细项</td><td>项</td><td>2</td></tr>
    </table>
    """

    assert resolve_engineering_table_grouping_mode("表外上下文", table) == "external"


def test_resolve_engineering_table_grouping_mode_should_use_external_heading_without_inner_groups():
    """只有表格前置标题时应使用外置分区模式。"""
    table = """
    <table>
      <tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>
      <tr><td>1</td><td>明细项</td><td>项</td><td>2</td></tr>
    </table>
    """

    assert resolve_engineering_table_grouping_mode("表外上下文", table) == "external"


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


def test_engineering_extraction_should_retry_only_failed_chunk_and_keep_source_context(monkeypatch):
    """模型输出达到长度限制时，应按完整行重试并保留外部分区及原始表头。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "表格前置说明\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>结构分类</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>条目甲</td><td>项</td><td>1</td></tr>"
        "<tr><td>2</td><td>条目乙</td><td>项</td><td>2</td></tr>"
        "<tr><td>3</td><td>条目丙</td><td>项</td><td>3</td></tr>"
        "<tr><td>4</td><td>条目丁</td><td>项</td><td>4</td></tr></table>"
    )
    rows = {
        "条目甲": ("1", 1),
        "条目乙": ("2", 2),
        "条目丙": ("3", 3),
        "条目丁": ("4", 4),
    }
    prompts: list[str] = []

    def generate_result(*, prompt: str, **_: object) -> EngineeringSchema:
        """模拟首个分块超限，后续子块按其可见原始行返回结果。"""
        prompts.append(prompt)
        if len(prompts) == 1:
            raise ValueError(
                "Could not parse response content as the length limit was reached"
            )
        items = [
            EquipmentItem(
                item_code=code,
                item_name=name,
                quantity=quantity,
                unit="项",
            )
            for name, (code, quantity) in rows.items()
            if name in prompt
        ]
        return EngineeringSchema(main_equipment_list=items)

    with patch.object(
        service, "_save_to_db"
    ), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        side_effect=generate_result,
    ):
        result = service.extract_metadata(source_context, "document-length-retry")

    assert len(prompts) > 1
    assert all("外层部分" in prompt for prompt in prompts[1:])
    assert all("序号" in prompt for prompt in prompts[1:])
    assert [item.item_name for item in result.main_equipment_list] == [
        "结构分类",
        "条目甲",
        "条目乙",
        "条目丙",
        "条目丁",
    ]
    assert result.main_equipment_list[0].parent_item is None
    assert all(
        item.parent_item == "结构分类"
        for item in result.main_equipment_list[1:]
    )
    assert all(item.grouping_mode == "external" for item in result.main_equipment_list)


def test_engineering_extraction_should_keep_model_bom_hierarchy_when_source_postprocessing_disabled(monkeypatch):
    """默认关闭源表后处理时，应保留模型识别的父子关系且不恢复源表遗漏节点。"""
    monkeypatch.delenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", raising=False)
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>源表结构父项</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>模型父项</td><td>套</td><td>1</td></tr>"
        "<tr><td>1.1</td><td>模型子项</td><td>台</td><td>2</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="1",
                item_name="模型父项",
                quantity=1,
                unit="套",
                root_item="模型父项",
                tree_level=1,
                grouping_mode="external",
            ),
            EquipmentItem(
                item_code="1.1",
                item_name="模型子项",
                quantity=2,
                unit="台",
                parent_item="模型父项",
                root_item="模型父项",
                tree_level=2,
                grouping_mode="external",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-model-hierarchy")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["模型父项", "模型子项"]
    assert items[0].parent_item is None
    assert items[1].parent_item == "模型父项"
    assert items[0].root_item == "模型父项"
    assert items[1].root_item == "模型父项"
    assert all(item.item_name != "源表结构父项" for item in items)


def test_engineering_extraction_should_not_retry_unsplittable_length_limited_chunk():
    """长度超限但只有一条清单行时，应安全结束，避免无限重试。"""
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>单条目</td><td>项</td><td>1</td></tr></table>"
    )

    with patch.object(
        service, "_save_to_db"
    ), patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        side_effect=ValueError(
            "Could not parse response content as the length limit was reached"
        ),
    ) as generate_mock:
        result = service.extract_metadata(source_context, "document-length-boundary")

    assert generate_mock.call_count == 1
    assert result.main_equipment_list == []


def test_deduplicate_equipment_items_should_merge_retry_metadata_without_reordering():
    """同一来源行被重复返回时，应保留一项并合并补充层级字段。"""
    current = EquipmentItem(
        item_code="1",
        item_name="清单项",
        quantity=1,
        unit="项",
        source_table_index=0,
        key_parameters=["已有参数"],
    )
    duplicate = EquipmentItem(
        item_code="1",
        item_name="清单项",
        quantity=1,
        unit="项",
        source_table_index=0,
        parent_item="父项",
        root_item="根项",
        tree_level=2,
    )
    # 模拟模型或历史对象在校验后仍携带 null，验证合并层的防御性处理。
    duplicate.key_parameters = None

    result = _deduplicate_equipment_items([current, duplicate])

    assert len(result) == 1
    assert result[0].parent_item == "父项"
    assert result[0].root_item == "根项"
    assert result[0].tree_level == 2
    assert result[0].key_parameters == ["已有参数"]


def test_deduplicate_equipment_items_should_keep_identical_uncoded_rows_separate():
    """没有原始编码时，即使内容相同也不能证明来自同一行。"""
    first = EquipmentItem(
        item_name="无编码清单项",
        specifications="相同规格",
        quantity=1,
        unit="项",
        source_table_index=0,
    )
    second = EquipmentItem(
        item_name="无编码清单项",
        specifications="相同规格",
        quantity=1,
        unit="项",
        source_table_index=0,
    )

    result = _deduplicate_equipment_items([first, second])

    assert len(result) == 2
    assert result[0] is first
    assert result[1] is second


def test_deduplicate_equipment_items_should_keep_same_code_across_bom_roots():
    """不同 BOM 根项下的同编码同名节点不能被错误合并。"""
    first = EquipmentItem(
        item_code="1",
        item_name="一级组件",
        quantity=2,
        unit="套",
        parent_item="根设备甲",
        root_item="根设备甲",
        tree_level=2,
        source_table_index=0,
    )
    second = EquipmentItem(
        item_code="1",
        item_name="一级组件",
        quantity=2,
        unit="套",
        parent_item="根设备乙",
        root_item="根设备乙",
        tree_level=2,
        source_table_index=0,
    )

    result = _deduplicate_equipment_items([first, second])

    assert len(result) == 2
    assert [item.root_item for item in result] == [
        "根设备甲",
        "根设备乙",
    ]


def test_parse_source_composition_components_should_merge_parameter_continuations():
    """成套设备中的型号和性能续行应并入前一设备规格，不能生成伪物料节点。"""
    components = _parse_source_composition_components(
        "组件甲:;型号A-100;10.5±2*2.5%/0.4kV;"
        "参数=4%;冷却方式:自然冷却;组件乙:100A/4P,1只"
    )

    assert [component[0] for component in components] == [
        "组件甲",
        "组件乙",
    ]
    assert "型号A-100" in components[0][1]
    assert "参数=4%" in components[0][1]
    assert "冷却方式:自然冷却" in components[0][1]
    assert components[1][2] == 1.0
    assert components[1][3] == "只"


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


def test_extract_inner_section_candidates_should_support_chinese_and_dotted_groups():
    """表内中文大序号和点号目录在有递进子行时应识别为结构分组。"""
    table = (
            "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
            "<tr><td>一</td><td>安装分部</td><td></td><td></td></tr>"
            "<tr><td>1.1</td><td>安装明细</td><td>项</td><td>1</td></tr>"
            "<tr><td>二</td><td>材料分部</td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>电缆分类</td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>电缆明细</td><td>米</td><td>10</td></tr>"
        "<tr><td>2.6.1</td><td>普通明细</td><td>米</td><td>20</td></tr></table>"
    )

    candidates = _extract_inner_section_candidates(table)

    assert candidates == [("一", "安装分部"), ("二", "材料分部"), ("2.1", "电缆分类")]


def test_table_parts_should_inherit_previous_internal_group_state():
    """表格拆块后，后续分块应继承前序行确定的有效内部分组。"""
    table = (
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>二</td><td>材料分部</td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>电缆分类</td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>电缆A</td><td>米</td><td>10</td></tr>"
        "<tr><td>2.1.2</td><td>电缆B</td><td>米</td><td>20</td></tr>"
        "<tr><td>2.2</td><td>接头分类</td><td></td><td></td></tr>"
        "<tr><td>2.2.1</td><td>接头A</td><td>只</td><td>2</td></tr>"
        "<tr><td>2.2.2</td><td>接头B</td><td>只</td><td>3</td></tr></table>"
    )

    parts = _build_table_parts_with_internal_group_state(table, max_chars=1000, max_rows=2)

    assert len(parts) == 4
    assert "表内分区状态（由当前表格前序行继承）" not in parts[0]
    assert "编码 二 / 名称 材料分部" in parts[1]
    assert "编码 2.1 / 名称 电缆分类" in parts[1]
    assert "编码 2.2 / 名称 接头分类" in parts[3]


def test_table_scoped_chunks_should_inherit_group_state_between_page_fragments():
    """相邻页面被解析成独立表格时，后页明细仍应带上前页分组状态。"""
    context = (
        "原始清单\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>二</td><td>材料分部</td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>电缆分类</td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>电缆A</td><td>米</td><td>10</td></tr></table>"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>2.1.2</td><td>电缆B</td><td>米</td><td>20</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, _, table_indexes = _build_table_scoped_engineering_chunks(
        context,
        table_matches,
        max_chars=1000,
    )

    assert table_indexes == [0, 1]
    assert "编码 2.1 / 名称 电缆分类" in chunks[1]


def test_table_scoped_chunks_should_not_inject_internal_state_for_external_section():
    """表格外分区模式拆分时不应注入表内分组状态。"""
    context = (
        "项目清单（外层分区）\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>一</td><td>分类行</td><td></td><td></td></tr>"
        "<tr><td>1.1</td><td>明细A</td><td>台</td><td>1</td></tr></table>"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1.2</td><td>明细B</td><td>台</td><td>2</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, _, table_indexes = _build_table_scoped_engineering_chunks(
        context,
        table_matches,
        max_chars=1000,
        table_grouping_modes={0: "external", 1: "external"},
    )

    assert table_indexes == [0, 1]
    assert all("表内分区状态（由当前表格前序行继承）" not in chunk for chunk in chunks)


def test_table_scoped_chunks_should_stop_group_state_at_unrelated_table():
    """工程量清单后的非计量表不应继承上一张清单的表内分组状态。"""
    context = (
        "项目需求清单（某分部）\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>二</td><td>材料分部</td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>电缆分类</td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>电缆A</td><td>米</td><td>10</td></tr></table>"
        "<table><tr><th>列A</th><th>列B</th></tr>"
        "<tr><td>值A</td><td>值B</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, _, table_indexes = _build_table_scoped_engineering_chunks(
        context,
        table_matches,
        max_chars=1000,
    )

    assert table_indexes == [0, 1]
    assert "编码 2.1 / 名称 电缆分类" not in chunks[1]


def test_table_scoped_chunks_should_not_leak_internal_state_into_unclassified_table():
    """不同表头的普通表格即使含点号编码，也不得继承上一张表的分组状态。"""
    context = (
        "<table><tr><th>编码</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>groupA</td><td></td><td></td></tr>"
        "<tr><td>1.1</td><td>itemA</td><td>项</td><td>1</td></tr></table>"
        "<table><tr><th>编码</th><th>名称</th><th>属性</th><th>值</th></tr>"
        "<tr><td>1.1</td><td>recordB</td><td>类型</td><td>2</td></tr></table>"
    )
    table_matches = list(re.finditer(r"<table[\s\S]*?</table>", context, re.IGNORECASE))

    chunks, _, table_indexes = _build_table_scoped_engineering_chunks(
        context,
        table_matches,
        max_chars=1000,
    )

    assert table_indexes == [0, 1]
    assert "groupA" not in chunks[1]


def test_extract_inner_section_candidates_should_ignore_standalone_marker():
    """没有后续结构行的括号编码不能单独触发表内分组模式。"""
    table = (
        "<table><tr><th>编码</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(1)</td><td>root</td><td></td><td></td></tr></table>"
    )

    assert _extract_inner_section_candidates(table) == []
    assert resolve_engineering_table_grouping_mode(None, table) == "none"


def test_collect_source_measurement_names_should_ignore_non_measurement_table():
    """原文计量行审计应保留尾部数值行，忽略没有计量列的相邻表。"""
    context = (
        "<table><tr><th>列A</th><th>列B</th><th>列C</th><th>列D</th></tr>"
        "<tr><td>编码A</td><td>项目A</td><td>说明A</td><td>1</td></tr></table>"
        "<table><tr><th>列E</th><th>列F</th></tr>"
        "<tr><td>值E</td><td>值F</td></tr></table>"
    )

    assert _collect_source_measurement_names(context) == ["项目A"]


def test_markdown_source_rows_should_support_structure_repair_and_measurement_audit():
    """Markdown 清单应与 HTML 清单一样参与源表对齐和计量行审计。"""
    context = (
        "| 序号 | 名称 | 规格型号 | 单位 | 数量 |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 | itemA | modelA | ea | 2 |"
    )

    source_tables = _source_rows_from_context(context)

    assert len(source_tables) == 1
    assert source_tables[0][0].item_code == "1"
    assert source_tables[0][0].item_name == "itemA"
    assert source_tables[0][0].quantity == 2
    assert _collect_source_measurement_names(context) == ["itemA"]


def test_boq_group_context_should_not_become_cost_parent():
    """表内报价分部和材料分类应回写路径，不能把明细挂成 BOM 子项。"""
    source_context = (
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>一</td><td>安装分部</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>设备A</td><td>项</td><td>1</td></tr>"
        "<tr><td>二</td><td>材料分部</td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>材料分类</td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>材料A</td><td>米</td><td>10</td></tr></table>"
    )
    items = [
        EquipmentItem(item_code="一", item_name="安装分部"),
        EquipmentItem(
            item_code="1",
            item_name="设备A",
            quantity=1,
            unit="项",
            parent_item=None,
            root_item=None,
            tree_level=2,
        ),
        EquipmentItem(item_code="二", item_name="材料分部"),
        EquipmentItem(item_code="2.1", item_name="材料分类"),
        EquipmentItem(
            item_code="2.1.1",
            item_name="材料A",
            quantity=10,
            unit="米",
            parent_item="材料分类",
            root_item="材料分部",
            tree_level=3,
        ),
    ]

    normalized = EngineeringService._normalize_model_boq_group_context(
        items,
        source_context,
    )

    assert [item.item_name for item in normalized] == ["安装分部", "设备A", "材料分部", "材料分类", "材料A"]
    assert normalized[0].parent_item is None
    assert normalized[1].parent_item is None
    assert normalized[4].parent_item is None
    assert normalized[0].tree_level == 1
    assert normalized[1].part_name == "安装分部"
    assert normalized[1].group_path == []
    assert normalized[4].part_name == "材料分部"
    assert normalized[4].group_path == ["材料分类"]


def test_boq_group_context_should_cross_blank_code_fragments_and_switch_groups():
    """无首列编码的续表行应继承旧分组，遇到新分组编码后应切换路径。"""
    source_context = (
        "<table><tr><th>序号</th><th>名称</th><th>说明</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>一</td><td>分部A</td><td></td><td></td><td></td></tr>"
        "<tr><td>1</td><td>明细A</td><td>说明A</td><td>项</td><td>1</td></tr></table>"
        "<table><tr><td></td><td>明细B</td><td>说明B</td><td>项</td><td>2</td></tr></table>"
        "<table><tr><td>二</td><td>分部B</td><td></td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>分类B</td><td></td><td></td><td></td></tr>"
        "<tr><td>2.1.1</td><td>明细C</td><td>说明C</td><td>项</td><td>3</td></tr></table>"
    )
    items = [
        EquipmentItem(item_code="1", item_name="明细A", quantity=1, unit="项"),
        EquipmentItem(item_name="明细B", quantity=2, unit="项"),
        EquipmentItem(item_code="2.1.1", item_name="明细C", quantity=3, unit="项"),
    ]

    normalized = EngineeringService._normalize_model_boq_group_context(
        items,
        source_context,
    )

    assert normalized[0].part_name == "分部A"
    assert normalized[1].part_name == "分部A"
    assert normalized[2].part_name == "分部B"
    assert normalized[2].group_path == ["分类B"]


def test_boq_group_context_should_match_source_after_markup_normalization():
    """续表规格含公式标记时，仍应按同一清单行继承前序顶层分组。"""
    source_context = (
        "<table><tr><th>序号</th><th>名称</th><th>说明</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>一</td><td>顶层分部</td><td></td><td></td><td></td></tr>"
        "<tr><td>1</td><td>首项</td><td>说明</td><td>项</td><td>1</td></tr></table>"
        "<table><tr><td></td><td>续项 $100 \\times 50$</td><td>说明</td><td>m</td><td>2</td></tr></table>"
    )
    items = [
        EquipmentItem(
            item_name="续项 100 × 50",
            quantity=2,
            unit="m",
            part_name="内部分类",
            group_path=["内部分类"],
        )
    ]

    normalized = EngineeringService._normalize_model_boq_group_context(
        items,
        source_context,
    )

    assert normalized[0].part_name == "顶层分部"
    assert normalized[0].group_path == ["内部分类"]


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


def test_external_section_extraction_should_preserve_bom_hierarchy_and_skip_internal_cleanup():
    """表格外分区模式不应把真实 BOM 结构父项清理成表内分类。"""
    service = EngineeringService()
    source_context = (
        "## 外层分区\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>主成套项</td><td>套</td><td>1</td></tr>"
        "<tr><td>1</td><td>中间结构项</td><td></td><td></td></tr>"
        "<tr><td>1.1</td><td>底层明细</td><td>台</td><td>2</td></tr></table>"
    )
    mock_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="(一)",
                item_name="主成套项",
                quantity=1,
                unit="套",
                root_item="主成套项",
                tree_level=1,
            ),
            EquipmentItem(
                item_code="1",
                item_name="中间结构项",
                parent_item="主成套项",
                root_item="主成套项",
                tree_level=2,
            ),
            EquipmentItem(
                item_code="1.1",
                item_name="底层明细",
                quantity=2,
                unit="台",
                parent_item="中间结构项",
                root_item="主成套项",
                tree_level=3,
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=mock_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-bom")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["主成套项", "中间结构项", "底层明细"]
    assert items[1].parent_item == "主成套项"
    assert items[2].parent_item == "中间结构项"
    assert all(item.section_name == "外层分区" for item in items)
    assert all(item.grouping_mode == "external" for item in items)
    assert all(item.part_name is None and item.group_path == [] for item in items)


def test_external_section_extraction_should_restore_priced_marker_parent_from_source(monkeypatch):
    """表格外分区下，模型漏返回带计量分组父行时应依据原表恢复。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>计价汇总项</td><td>项</td><td>1</td></tr>"
        "<tr><td>1</td><td>明细项甲</td><td>台</td><td>2</td></tr>"
        "<tr><td>2</td><td>明细项乙</td><td>台</td><td>3</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_code="1", item_name="明细项甲", quantity=2, unit="台"),
            EquipmentItem(item_code="2", item_name="明细项乙", quantity=3, unit="台"),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-priced-marker")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["计价汇总项", "明细项甲", "明细项乙"]
    assert items[0].item_code == "(一)"
    assert items[0].quantity == 1
    assert items[0].unit == "项"
    assert items[0].root_item == "计价汇总项"
    assert items[0].grouping_mode == "external"
    assert all(item.section_name == "外层部分" for item in items)
    assert items[1].parent_item == "计价汇总项"
    assert items[2].parent_item == "计价汇总项"


def test_external_section_extraction_should_restore_unpriced_structural_parent_from_source(monkeypatch):
    """表格外分区下，无计量但承载连续明细的结构行也应保留。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>结构分类</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>明细项甲</td><td>台</td><td>2</td></tr>"
        "<tr><td>2</td><td>明细项乙</td><td>台</td><td>3</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_code="1", item_name="明细项甲", quantity=2, unit="台"),
            EquipmentItem(item_code="2", item_name="明细项乙", quantity=3, unit="台"),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-structural")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["结构分类", "明细项甲", "明细项乙"]
    assert items[0].item_code == "(一)"
    assert items[0].quantity is None
    assert items[0].unit is None
    assert items[0].root_item == "结构分类"
    assert items[0].tree_level == 1
    assert items[0].grouping_mode == "external"
    assert items[1].parent_item == "结构分类"
    assert items[2].parent_item == "结构分类"
    assert all(item.tree_level == level for item, level in zip(items, [1, 2, 2]))


def test_external_section_extraction_should_restore_numeric_structural_parent_from_source(monkeypatch):
    """表格外分区下，遗漏的普通整数结构父项应恢复并挂接递进明细。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "4、项目需求清单（直流侧太阳能板、逆变器等）\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td colspan=\"4\">光伏发电设备</td></tr>"
        "<tr><td>1.1</td><td>太阳能光伏组件</td><td>720Wp</td><td>块</td><td>15110</td></tr>"
        "<tr><td>1.2</td><td>逆变器</td><td>320kW</td><td>台</td><td>34</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="1.1",
                item_name="太阳能光伏组件",
                specifications="720Wp",
                quantity=15110,
                unit="块",
            ),
            EquipmentItem(
                item_code="1.2",
                item_name="逆变器",
                specifications="320kW",
                quantity=34,
                unit="台",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-numeric-parent")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["光伏发电设备", "太阳能光伏组件", "逆变器"]
    assert items[0].item_code == "1"
    assert items[0].quantity is None
    assert items[0].unit is None
    assert items[0].parent_item is None
    assert items[0].root_item == "光伏发电设备"
    assert items[1].parent_item == "光伏发电设备"
    assert items[2].parent_item == "光伏发电设备"
    assert all(item.root_item == "光伏发电设备" for item in items)
    assert all(item.tree_level == level for item, level in zip(items, [1, 2, 2]))
    assert all(item.section_name == "直流侧太阳能板、逆变器等" for item in items)
    assert all(item.grouping_mode == "external" for item in items)


def test_external_section_extraction_should_restore_rowspan_parent_names_from_source(monkeypatch):
    """表格外分区下，rowspan 父名称遗漏时应恢复父项并将规格行挂接到父项。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 二次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>型号和规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(六)</td><td colspan=\"4\">其他</td></tr>"
        "<tr><td rowspan=\"2\">1</td><td rowspan=\"2\">屏蔽控制电缆</td><td>ZC-A 汇总</td><td>米</td><td></td></tr>"
        "<tr><td>ZC-A 4X2.5</td><td>米</td><td></td></tr>"
        "<tr><td rowspan=\"2\">2</td><td rowspan=\"2\">主要标的物低压电力电缆</td><td>NH-A 汇总</td><td>米</td><td></td></tr>"
        "<tr><td>NH-A 2X4</td><td>米</td><td></td></tr>"
        "<tr><td>3</td><td>普通明细</td><td>TMY</td><td>米</td><td></td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_name="ZC-A 汇总", unit="米"),
            EquipmentItem(item_name="ZC-A 4X2.5", unit="米"),
            EquipmentItem(item_name="NH-A 汇总", unit="米"),
            EquipmentItem(item_name="NH-A 2X4", unit="米"),
            EquipmentItem(item_code="3", item_name="普通明细", unit="米"),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-rowspan-parent")

    items = result.main_equipment_list
    names = [item.item_name for item in items]
    assert names[:3] == ["其他", "屏蔽控制电缆", "ZC-A 汇总"]
    assert "主要标的物低压电力电缆" in names
    screen_parent = next(item for item in items if item.item_name == "屏蔽控制电缆")
    low_voltage_parent = next(
        item for item in items if item.item_name == "主要标的物低压电力电缆"
    )
    other_parent = items[0]
    assert other_parent.item_name == "其他"
    assert screen_parent.parent_item == "其他"
    assert low_voltage_parent.parent_item == "其他"
    assert screen_parent.quantity is None and screen_parent.unit is None
    assert low_voltage_parent.quantity is None and low_voltage_parent.unit is None
    assert any(item.parent_item == "屏蔽控制电缆" for item in items)
    assert any(item.parent_item == "主要标的物低压电力电缆" for item in items)
    assert all(item.section_name == "二次侧部分" for item in items)
    assert all(item.grouping_mode == "external" for item in items)


def test_external_section_extraction_should_restore_missing_explicit_bom_rows_from_source(monkeypatch):
    """外部分区下模型只返回箱变根项时，应依据每套包含恢复完整组成。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 一次侧部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(三)</td><td>1600kVA光伏升压箱变</td><td></td><td>套</td><td>2</td></tr>"
        "<tr><td></td><td></td><td>每套包含:</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>环网柜</td><td></td><td>套</td><td>1</td></tr>"
        "<tr><td>1.1</td><td>高压真空断路器</td><td>630,25kA</td><td>组</td><td>1</td></tr>"
        "<tr><td>1.2</td><td>隔离开关</td><td>630A</td><td>组</td><td>1</td></tr>"
        "<tr><td>2</td><td>10kV变压器</td><td></td><td></td><td></td></tr>"
        "<tr><td>2.1</td><td>10kV升压变压器</td><td>SCB14-1600/10.5</td><td>台</td><td>1</td></tr>"
        "<tr><td>3</td><td>辅助配电柜</td><td></td><td>套</td><td>1</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="(三)",
                item_name="1600kVA光伏升压箱变",
                quantity=2,
                unit="套",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-explicit-bom")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == [
        "1600kVA光伏升压箱变",
        "环网柜",
        "高压真空断路器",
        "隔离开关",
        "10kV变压器",
        "10kV升压变压器",
        "辅助配电柜",
    ]
    root, ring, breaker, isolator, transformer_group, transformer, cabinet = items
    assert root.quantity == 2 and root.tree_level == 1 and root.parent_item is None
    assert ring.parent_item == root.item_name and ring.quantity == 2
    assert ring.per_set_quantity == 1 and ring.tree_level == 2
    assert breaker.parent_item == ring.item_name and breaker.quantity == 2
    assert breaker.per_set_quantity == 1 and breaker.tree_level == 3
    assert isolator.parent_item == ring.item_name and isolator.quantity == 2
    assert transformer_group.parent_item == root.item_name
    assert transformer_group.quantity is None and transformer_group.tree_level == 2
    assert transformer.parent_item == transformer_group.item_name
    assert transformer.quantity == 2 and transformer.tree_level == 3
    assert cabinet.parent_item == root.item_name and cabinet.quantity == 2
    assert all(item.root_item == root.item_name for item in items)
    assert all(item.section_name == "一次侧部分" for item in items)
    assert all(item.grouping_mode == "external" for item in items)


def test_external_bom_should_restore_rowspan_composition_components_under_generic_parent(monkeypatch):
    """成套父项名称和组成提示来自源表时，应恢复通用三级组成项。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "<table><tr><th>项目名称</th><th>技术要求</th></tr>"
        "<tr><td></td><td></td></tr></table>"
        "## 一次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>型号规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>10kV高压设备</td><td></td><td></td><td></td></tr>"
        "<tr><td rowspan='3'>1</td><td rowspan='3'>10kV并网开关柜,每套包含:</td>"
        "<td>金属铠装移开式高压开关柜,12kV,630A,25kA;</td><td>面</td><td>2</td></tr>"
        "<tr><td>真空断路器:12kV,630A,25kA,1台;</td><td></td><td></td></tr>"
        "<tr><td>电流互感器:500/5,5P30,3只;</td><td></td><td></td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_code="(一)", item_name="10kV高压设备")
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-rowspan-bom")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == [
        "10kV高压设备",
        "10kV并网开关柜",
        "金属铠装移开式高压开关柜",
        "真空断路器",
        "电流互感器",
    ]
    root, parent, cabinet, breaker, current_transformer = items
    assert parent.parent_item == root.item_name
    assert parent.quantity == 2 and parent.unit == "面"
    assert cabinet.parent_item == parent.item_name
    assert cabinet.quantity == 2 and cabinet.unit == "面"
    assert cabinet.per_set_quantity is None
    assert breaker.parent_item == parent.item_name
    assert breaker.quantity == 2 and breaker.per_set_quantity == 1
    assert current_transformer.parent_item == parent.item_name
    assert current_transformer.quantity == 6 and current_transformer.per_set_quantity == 3
    assert all(item.root_item == root.item_name for item in items)


def test_external_bom_should_merge_rowspan_specification_continuations_into_one_component(monkeypatch):
    """同一 rowspan 组成组中的型号与参数续行应合并到对应组件，而不是生成平级节点。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 外部分区\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>成套设备甲</td><td></td><td></td><td></td></tr>"
        "<tr><td rowspan='5'>1</td><td rowspan='5'>总成组件甲,每套包含:</td>"
        "<td>组件甲:</td><td>件</td><td>2</td></tr>"
        "<tr><td>型号A-100</td><td></td><td></td></tr>"
        "<tr><td>参数=4%</td><td></td><td></td></tr>"
        "<tr><td>功能说明:远程控制</td><td></td><td></td></tr>"
        "<tr><td>组件乙:100A/4P,1只</td><td></td><td></td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="(一)",
                item_name="成套设备甲",
                quantity=2,
                unit="套",
            )
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-rowspan-spec-continuation")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == [
        "成套设备甲",
        "总成组件甲",
        "组件甲",
        "组件乙",
    ]
    component_a = items[2]
    assert "型号A-100" in component_a.specifications
    assert "参数=4%" in component_a.specifications
    assert "功能说明:远程控制" in component_a.specifications
    assert component_a.quantity == 2 and component_a.unit == "件"
    assert items[3].quantity == 2 and items[3].unit == "只"
    assert all(item.parent_item for item in items[1:])


def test_external_bom_should_isolate_duplicate_children_by_parent_branch_range():
    """两个箱变分支出现同名同编码子项时，不应互相覆盖父级关系。"""
    source_context = (
        "<table><tr><th>项目名称</th><th>技术要求</th></tr>"
        "<tr><td></td><td></td></tr></table>"
        "## 一次侧部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(二)</td><td>2000kVA光伏升压箱变</td><td></td><td>套</td><td>4</td></tr>"
        "<tr><td></td><td></td><td>每套包含:</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>环网柜</td><td></td><td>套</td><td>1</td></tr>"
        "<tr><td>1.4</td><td>电流互感器</td><td>200/5A</td><td>只</td><td>3</td></tr>"
        "<tr><td>(三)</td><td>1600kVA光伏升压箱变</td><td></td><td>套</td><td>2</td></tr>"
        "<tr><td></td><td></td><td>每套包含:</td><td></td><td></td></tr>"
        "<tr><td>1</td><td>环网柜</td><td></td><td>套</td><td>1</td></tr>"
        "<tr><td>1.4</td><td>电流互感器</td><td>150/5A</td><td>只</td><td>3</td></tr></table>"
    )
    root_2000 = EquipmentItem(
        item_code="(二)", item_name="2000kVA光伏升压箱变", quantity=4, unit="套"
    )
    ring_2000 = EquipmentItem(
        item_code="1", item_name="环网柜", quantity=1, unit="套", root_item="1600kVA光伏升压箱变"
    )
    current_2000 = EquipmentItem(
        item_code="1.4", item_name="电流互感器", specifications="200/5A", quantity=3, unit="只"
    )
    root_1600 = EquipmentItem(
        item_code="(三)", item_name="1600kVA光伏升压箱变", quantity=2, unit="套"
    )
    ring_1600 = EquipmentItem(
        item_code="1", item_name="环网柜", quantity=1, unit="套", root_item="2000kVA光伏升压箱变"
    )
    current_1600 = EquipmentItem(
        item_code="1.4", item_name="电流互感器", specifications="150/5A", quantity=3, unit="只"
    )
    items = [root_2000, ring_2000, current_2000, root_1600, ring_1600, current_1600]
    for item in items:
        item.source_table_index = 0
    table_indexes = {id(item): 0 for item in items}

    structural_items = [item.model_copy(deep=True) for item in items]
    structural_indexes = {id(item): 0 for item in structural_items}
    structural_result = EngineeringService._restore_missing_structural_nodes_from_source(
        structural_items,
        source_context,
        item_table_indexes=structural_indexes,
        allowed_table_indexes={0},
    )
    assert len(structural_result) == len(structural_items)

    result = EngineeringService._restore_missing_explicit_bom_rows_from_source(
        items,
        source_context,
        item_table_indexes=table_indexes,
        allowed_table_indexes={0},
    )

    result_by_name_and_spec = {
        (item.item_name, item.specifications): item
        for item in result
        if item.item_name in {"环网柜", "电流互感器"}
    }
    # 同名环网柜通过位置隔离后仍需保留两行，规格项分别归属对应箱变。
    ring_items = [item for item in result if item.item_name == "环网柜"]
    assert len(ring_items) == 2
    assert ring_items[0].parent_item == root_2000.item_name
    assert ring_items[1].parent_item == root_1600.item_name
    assert result_by_name_and_spec[("电流互感器", "200/5A")].root_item == root_2000.item_name
    assert result_by_name_and_spec[("电流互感器", "150/5A")].root_item == root_1600.item_name


def test_external_section_extraction_should_drop_bare_chinese_boq_category_from_items(monkeypatch):
    """外部分区表中的无计量中文大序号分类不应被保留为清单或 BOM 根项。"""
    monkeypatch.setenv("ENGINEERING_SOURCE_BOM_POSTPROCESSING_ENABLED", "true")
    service = EngineeringService()
    source_context = (
        "## 一次侧部分\n"
        "<table><tr><th>序号</th><th>设备名称</th><th>规格</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>一</td><td colspan=\"4\">光伏</td></tr>"
        "<tr><td>(一)</td><td>10kV高压设备</td><td></td><td></td><td></td></tr>"
        "<tr><td>1</td><td>10kV并网开关柜</td><td>12kV</td><td>套</td><td>2</td></tr></table>"
    )
    model_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(item_code="一", item_name="光伏"),
            EquipmentItem(item_code="(一)", item_name="10kV高压设备"),
            EquipmentItem(
                item_code="1",
                item_name="10kV并网开关柜",
                specifications="12kV",
                quantity=2,
                unit="套",
            ),
        ]
    )

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        return_value=model_result,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-drop-boq-category")

    items = result.main_equipment_list
    assert [item.item_name for item in items] == ["10kV高压设备", "10kV并网开关柜"]
    assert items[0].parent_item is None
    assert items[1].parent_item == "10kV高压设备"
    assert all(item.item_name != "光伏" for item in items)


def test_external_section_extraction_should_inherit_context_to_repeated_header_continuation():
    """外部分区清单分页后重复表头时，续表仍应沿用外部分区模式。"""
    service = EngineeringService()
    source_context = (
        "## 外层部分\n"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>(一)</td><td>主项</td><td>套</td><td>1</td></tr></table>"
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1.1</td><td>续表明细</td><td>台</td><td>2</td></tr></table>"
    )
    first_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="(一)",
                item_name="主项",
                quantity=1,
                unit="套",
                root_item="主项",
                tree_level=1,
            )
        ]
    )
    second_result = EngineeringSchema(
        main_equipment_list=[
            EquipmentItem(
                item_code="1.1",
                item_name="续表明细",
                quantity=2,
                unit="台",
                parent_item="主项",
                root_item="主项",
                tree_level=2,
            )
        ]
    )

    def result_for_chunk(prompt: str, **_kwargs: object) -> EngineeringSchema:
        """根据当前分块中的原文标识返回对应的通用模拟结果。"""
        return second_result if "续表明细" in prompt else first_result

    with patch(
        "app.services.metadata.engineering_service.llm_service.generate_structured_output",
        side_effect=result_for_chunk,
    ), patch.object(service, "_save_to_db"):
        result = service.extract_metadata(source_context, "document-external-continuation")

    assert len(result.main_equipment_list) == 2
    continuation_item = result.main_equipment_list[1]
    assert continuation_item.section_name == "外层部分"
    assert continuation_item.grouping_mode == "external"
    assert continuation_item.parent_item == "主项"


def test_external_table_continuation_should_accept_increasing_plain_integer_code():
    """重复表头且编号递增的外部分区续表应继续继承外部分区。"""
    previous_table = (
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>1</td><td>项目A</td><td>项</td><td>1</td></tr></table>"
    )
    current_table = (
        "<table><tr><th>序号</th><th>名称</th><th>单位</th><th>数量</th></tr>"
        "<tr><td>2</td><td>项目B</td><td>项</td><td>1</td></tr></table>"
    )

    assert _is_likely_external_table_continuation(previous_table, current_table)


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
    assert "rowspan" in prompt
    assert "每套包含/每套含有/每套包括" in prompt
    assert "表内 BOQ 分组与 BOM 父项必须分开" in prompt
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
