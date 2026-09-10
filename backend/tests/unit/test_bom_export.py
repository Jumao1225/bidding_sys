"""
单元测试：BOM 成本测算 Word 导出服务与大写金额汇总 (test_bom_export.py)
"""

import io
import pytest
from docx import Document

from app.services.bom_export_service import (
    _calculate_export_total,
    _collect_export_rows,
    _item_group_context,
    generate_bom_docx,
    generate_bom_xlsx,
)
from app.utils.rmb_formatter import number_to_chinese_rmb


def test_bom_export_docx_generation_with_chinese_rmb():
    """测试生成 BOM Word 文档，验证表格结构与表尾大小写总价"""
    test_items = [
        {
            "name": "单晶光伏组件",
            "section_name": "光伏发电设备",
            "spec_requirement": "≥630Wp，组件效率≥20.2%",
            "matched_name": "单晶光伏组件",
            "matched_brand": "天合光能",
            "matched_model": "635Wp",
            "matched_manufacturer": "天合光能股份有限公司",
            "match_quality": "精准匹配",
            "qty": 763,
            "unit": "块",
            "ref_price": 882.69,
            "subtotal": 673492.47,
        },
        {
            "name": "组串式逆变器",
            "section_name": "逆变与配电系统",
            "spec_requirement": "110kW 组串式逆变器",
            "matched_brand": "华为",
            "matched_model": "SUN2000-110KTL",
            "matched_manufacturer": "华为技术有限公司",
            "match_quality": "精准匹配",
            "qty": 5,
            "unit": "台",
            "ref_price": 25000.0,
            "subtotal": 125000.0,
        },
    ]

    total_cost = 798492.47
    expected_chinese_rmb = number_to_chinese_rmb(total_cost)
    assert expected_chinese_rmb == "柒拾玖万捌仟肆佰玖拾贰元肆角柒分"

    doc_io = generate_bom_docx(
        document_title="某新能源光伏电站标书",
        items=test_items,
        total_cost=total_cost,
        budget_limit="¥1,000,000.00",
        status_text="在最高投标限价内可控（使用率 79.8%）",
        analysis_summary="本批次2项设备均与参考库精准匹配，建议按指导价起草报价清单。"
    )

    assert isinstance(doc_io, io.BytesIO)
    doc_bytes = doc_io.getvalue()
    assert len(doc_bytes) > 0

    # 重新读取并验证 docx 内部内容
    doc = Document(io.BytesIO(doc_bytes))
    
    # 验证标题
    assert "拟投入设备及 BOM 成本测算清单" in doc.paragraphs[0].text
    
    # 验证项目信息
    info_text = doc.paragraphs[1].text
    assert "某新能源光伏电站标书" in info_text
    assert "1,000,000.00" in info_text
    assert "在最高投标限价内可控" in info_text

    # 验证表格行数与内容
    assert len(doc.tables) >= 1
    table = doc.tables[0]
    # 表头(1) + 分区行(2) + 数据行(2) + 表尾合计(1) = 6
    assert len(table.rows) == 6

    # 验证第一行数据
    row_1_text = " ".join(c.text for c in table.rows[2].cells)
    assert "单晶光伏组件" in row_1_text
    assert "天合光能" in row_1_text
    assert "673,492.47" in row_1_text
    assert table.rows[4].cells[0].text == "1"

    # 验证表尾合计行包含大写总价与小写数值
    footer_row_text = " ".join(c.text for c in table.rows[5].cells)
    assert "【合计】预估总成本" in footer_row_text
    assert "柒拾玖万捌仟肆佰玖拾贰元肆角柒分" in footer_row_text
    assert "798,492.47" in footer_row_text

    # 验证专家评估意见
    full_doc_text = "\n".join(p.text for p in doc.paragraphs)
    assert "专家评估指导意见" in full_doc_text
    assert "建议按指导价起草报价清单" in full_doc_text
    assert "¥" not in full_doc_text
    assert "￥" not in full_doc_text


def test_bom_export_docx_should_keep_item_name_without_tree_prefix():
    """测试 Word 名称列不写入树形缩进与分支符号，层级由序号列表达。"""
    items = [
        {
            "name": "父项",
            "children": [{"name": "子项", "qty": 1, "unit": "项"}],
            "qty": 1,
            "unit": "项",
        },
    ]

    doc_io = generate_bom_docx(document_title="测试文件", items=items)
    document = Document(io.BytesIO(doc_io.getvalue()))
    table = document.tables[0]

    assert table.rows[1].cells[1].text == "父项"
    assert table.rows[2].cells[1].text == "子项"
    assert "└─" not in table.rows[2].cells[1].text


def test_bom_export_xlsx_generation_with_chinese_rmb():
    """测试生成 BOM Excel (.xlsx) 工作簿，验证 9 列格式与表尾大小写合计"""
    from openpyxl import load_workbook
    test_items = [
        {
            "name": "单晶光伏组件",
            "spec_requirement": "≥630Wp 单晶硅组件",
            "matched_brand": "天合光能",
            "matched_model": "635Wp",
            "matched_manufacturer": "天合光能股份有限公司",
            "qty": 763,
            "unit": "块",
            "ref_price": 882.69,
            "subtotal": 673492.47,
        },
        {
            "name": "组串式逆变器",
            "spec_requirement": "110kW 组串式逆变器",
            "matched_brand": "华为",
            "matched_model": "SUN2000-110KTL",
            "matched_manufacturer": "华为技术有限公司",
            "qty": 5,
            "unit": "台",
            "ref_price": 25000.0,
            "subtotal": 125000.0,
        },
    ]

    total_cost = 798492.47
    excel_io = generate_bom_xlsx(
        document_title="某新能源光伏电站标书",
        items=test_items,
        total_cost=total_cost,
        budget_limit="¥1,000,000.00",
        status_text="在最高投标限价内可控",
        analysis_summary="本批次设备均与参考库精准对标。"
    )

    assert isinstance(excel_io, io.BytesIO)
    excel_bytes = excel_io.getvalue()
    assert len(excel_bytes) > 0

    wb = load_workbook(io.BytesIO(excel_bytes))
    ws = wb.active
    assert ws.title == "BOM成本测算清单"

    # 验证标题与信息
    assert "拟投入设备及 BOM 成本测算清单" in ws['A1'].value
    assert "某新能源光伏电站标书" in ws['A2'].value

    # 验证表头（9 列）
    headers = [ws.cell(row=5, column=c).value for c in range(1, 10)]
    assert headers == ["序号", "标的物名称", "品牌、规格、型号", "生产厂家", "单位", "数量", "单价(元)", "总价(元)", "备注"]

    # 验证数据行
    assert ws['B6'].value == "单晶光伏组件"
    assert ws['C6'].value == "天合光能 635Wp"
    assert ws['D6'].value == "天合光能股份有限公司"
    assert ws['F6'].value == 763
    assert ws['F6'].number_format == '#,##0'
    assert ws['G6'].value == 882.69
    assert ws['G6'].number_format == '#,##0.00'
    assert ws['H6'].value == 673492.47
    assert ws['H6'].number_format == '#,##0.00'

    # 验证表尾合计行 (Row 8)
    footer_row_val = ws['A8'].value
    assert "【合计】预估总成本" in footer_row_val
    assert "柒拾玖万捌仟肆佰玖拾贰元肆角柒分" in footer_row_val
    assert ws['H8'].value == 798492.47


def test_bom_export_xlsx_should_keep_item_name_without_tree_prefix():
    """测试 Excel 名称列不写入树形缩进与分支符号，层级由序号列表达。"""
    from openpyxl import load_workbook

    items = [
        {
            "name": "父项",
            "children": [{"name": "子项", "qty": 1, "unit": "项"}],
            "qty": 1,
            "unit": "项",
        },
    ]

    excel_io = generate_bom_xlsx(document_title="测试文件", items=items)
    workbook = load_workbook(io.BytesIO(excel_io.getvalue()))
    worksheet = workbook.active

    assert worksheet["B6"].value == "父项"
    assert worksheet["B7"].value == "子项"
    assert "└─" not in worksheet["B7"].value


def test_bom_export_should_render_internal_group_headers_without_affecting_total():
    """测试表内 BOQ 分组可导出为结构行，且不参与金额合计。"""
    items = [
        {
            "name": "明细甲",
            "part_name": "分组甲",
            "group_path": ["分类甲"],
            "qty": 2,
            "unit": "项",
            "ref_price": 10,
            "subtotal": 20,
        },
        {
            "name": "明细乙",
            "part_name": "分组乙",
            "group_path": ["分类乙"],
            "qty": 3,
            "unit": "项",
            "ref_price": 15,
            "subtotal": 45,
        },
    ]

    rows = _collect_export_rows(items)
    assert [row.group_name for row in rows if row.is_group_header] == [
        "分组甲", "分类甲", "分组乙", "分类乙",
    ]
    assert _calculate_export_total(rows) == 65

    excel_io = generate_bom_xlsx(document_title="测试文件", items=items)
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(excel_io.getvalue()))
    worksheet = workbook.active
    assert worksheet["A6"].value == "1"
    assert worksheet["B6"].value == "分组甲"
    assert worksheet["A7"].value == "1.1"
    assert worksheet["B7"].value == "分类甲"
    assert worksheet["A9"].value == "2"
    assert worksheet["B9"].value == "分组乙"
    assert worksheet["A10"].value == "2.1"
    assert worksheet["B10"].value == "分类乙"
    assert worksheet["H12"].value == 65


def test_bom_export_should_deduplicate_repeated_parent_group_path():
    """父分组已出现在路径首节点时，导出上下文只保留一次。"""
    item = {
        "name": "明细项",
        "part_name": "父分组",
        "group_path": ["父分组", "子分类"],
    }

    assert _item_group_context(item) == ("父分组", "子分类")
    rows = _collect_export_rows([item])
    assert [row.group_name for row in rows if row.is_group_header] == ["父分组", "子分类"]

    doc_io = generate_bom_docx(document_title="测试文件", items=[item])
    document = Document(io.BytesIO(doc_io.getvalue()))
    group_rows = [
        (row.cells[0].text, row.cells[1].text)
        for row in document.tables[0].rows
        if row.cells[1].text in {"父分组", "子分类"}
    ]
    assert group_rows == [("1", "父分组"), ("1.1", "子分类")]


def test_bom_export_should_number_roots_independently_inside_each_group():
    """前端已传入表内树时，导出序号直接沿用树节点层级。"""
    items = [
        {
            "name": "明细甲",
            "part_name": "大分组甲",
            "group_path": ["大分组甲"],
        },
        {
            "name": "明细乙",
            "part_name": "大分组甲",
            "group_path": ["大分组甲", "子分类"],
        },
        {
            "name": "明细丙",
            "part_name": "大分组乙",
            "group_path": ["大分组乙"],
            "children": [{"name": "明细丙-子项"}],
        },
        {
            "name": "明细丁",
            "part_name": "大分组乙",
            "group_path": ["大分组乙"],
        },
    ]

    rows = _collect_export_rows(items)
    item_numbers = [
        row.hierarchy_number
        for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]
    assert item_numbers == ["1", "2", "3", "3.1", "4"]
    assert not any(row.is_group_header for row in rows)


def test_bom_export_should_keep_frontend_internal_group_siblings_at_same_level():
    """前端表内分组的同级节点应导出为 2.1、2.2，不能重复生成虚拟分组行。"""
    items = [
        {
            "name": "安装工程",
            "part_name": "安装工程",
            "group_path": ["安装工程"],
        },
        {
            "name": "乙供设备及材料",
            "part_name": "乙供设备及材料",
            "group_path": ["乙供设备及材料"],
            "children": [
                {
                    "name": "直流电缆",
                    "part_name": "直流电缆",
                    "group_path": ["直流电缆"],
                },
                {
                    "name": "电力电缆",
                    "part_name": "电力电缆",
                    "group_path": ["电力电缆"],
                },
            ],
        },
    ]

    rows = _collect_export_rows(items)
    item_rows = [
        row for row in rows
        if row.item is not None and not row.is_section_header and not row.is_group_header
    ]

    assert [(row.hierarchy_number, row.item["name"]) for row in item_rows] == [
        ("1", "安装工程"),
        ("2", "乙供设备及材料"),
        ("2.1", "直流电缆"),
        ("2.2", "电力电缆"),
    ]
    assert not any(row.is_group_header for row in rows)

    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(generate_bom_xlsx(
        document_title="测试文件",
        items=items,
    ).getvalue()))
    worksheet = workbook.active
    assert [
        (worksheet.cell(row=row_index, column=1).value, worksheet.cell(row=row_index, column=2).value)
        for row_index in range(6, 10)
    ] == [
        ("1", "安装工程"),
        ("2", "乙供设备及材料"),
        ("2.1", "直流电缆"),
        ("2.2", "电力电缆"),
    ]


def test_bom_export_should_preserve_frontend_item_code_instead_of_deepening_tree_path():
    """前端已有多级序号时，导出不得用 children 路径额外拼接层级。"""
    items = [
        {
            "name": "接地",
            "item_code": "2.6",
            "grouping_mode": "internal",
            "children": [
                {
                    "name": "接地绝缘钢绞线",
                    "item_code": "2.6.1",
                    "grouping_mode": "internal",
                    "children": [
                        {
                            "name": "接地干线",
                            "item_code": "2.6.3",
                            "grouping_mode": "internal",
                        },
                    ],
                },
                {
                    "name": "接地绝缘钢绞线",
                    "item_code": "2.6.2",
                    "grouping_mode": "internal",
                },
            ],
        },
    ]

    rows = _collect_export_rows(items)
    item_rows = [
        row for row in rows
        if row.item is not None and not row.is_section_header and not row.is_group_header
    ]

    assert [(row.hierarchy_number, row.item["name"]) for row in item_rows] == [
        ("2.6", "接地"),
        ("2.6.1", "接地绝缘钢绞线"),
        ("2.6.3", "接地干线"),
        ("2.6.2", "接地绝缘钢绞线"),
    ]
    assert all("2.6.1.1" not in row.hierarchy_number for row in item_rows)


def test_bom_export_should_inherit_previous_group_when_flat_row_loses_context():
    """平铺表格中间明细缺少分组字段时，应沿用最近的有效表内分组。"""
    items = [
        {
            "name": "大分组甲明细",
            "part_name": "大分组甲",
            "group_path": ["大分组甲"],
        },
        {
            "name": "子分类明细一",
            "part_name": "大分组甲",
            "group_path": ["大分组甲", "子分类"],
        },
        {"name": "子分类明细二"},
        {
            "name": "另一分组明细",
            "part_name": "大分组乙",
            "group_path": ["大分组乙", "另一分类"],
        },
    ]

    rows = _collect_export_rows(items)
    item_numbers = [
        row.hierarchy_number
        for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]

    assert item_numbers == ["1.1", "1.2.1", "1.2.2", "2.1.1"]
    assert [row.hierarchy_number for row in rows if row.is_group_header] == [
        "1", "1.2", "2", "2.1",
    ]
    assert [row.group_name for row in rows if row.is_group_header] == [
        "大分组甲",
        "子分类",
        "大分组乙",
        "另一分类",
    ]


def test_bom_export_should_create_nested_group_rows_for_each_path_level():
    """三级表内分组应逐级占用序号，明细从末级分组下继续编号。"""
    items = [
        {"name": "一级分组明细", "part_name": "一级分组", "group_path": ["一级分组"]},
        {"name": "二级分组明细", "part_name": "二级分组", "group_path": ["二级分组"]},
        {
            "name": "三级路径明细一",
            "part_name": "三级分组",
            "group_path": ["三级分组", "中间分类", "末级分类"],
        },
        {
            "name": "三级路径明细二",
            "part_name": "三级分组",
            "group_path": ["三级分组", "中间分类", "末级分类"],
        },
    ]

    rows = _collect_export_rows(items)
    item_numbers = [
        row.hierarchy_number
        for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]

    assert item_numbers == ["1.1", "2.1", "3.1.1.1", "3.1.1.2"]
    assert [row.hierarchy_number for row in rows if row.is_group_header] == [
        "1", "2", "3", "3.1", "3.1.1",
    ]
    assert [row.group_name for row in rows if row.is_group_header] == [
        "一级分组", "二级分组", "三级分组", "中间分类", "末级分类",
    ]


def test_bom_export_should_preserve_section_local_numbering_without_table_groups():
    """没有表内大分组时，多个表外分区继续保持原有分区内编号。"""
    items = [
        {"name": "分区甲明细一", "section_name": "表外分区甲"},
        {"name": "分区乙明细一", "section_name": "表外分区乙"},
        {"name": "分区甲明细二", "section_name": "表外分区甲"},
    ]

    rows = _collect_export_rows(items)
    item_numbers = [
        row.hierarchy_number
        for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]
    assert item_numbers == ["1", "1", "2"]


def test_bom_export_should_prioritize_external_sections_over_inner_group_fields():
    """同一批导出数据同时带两类字段时，优先输出表格外分区。"""
    rows = _collect_export_rows([
        {
            "name": "明细甲",
            "section_name": "表外分区甲",
            "part_name": "表内分类甲",
            "group_path": ["子分类甲"],
        },
        {
            "name": "明细乙",
            "section_name": "表外分区乙",
            "part_name": "表内分类乙",
            "group_path": ["子分类乙"],
        },
    ])

    assert [row.section_name for row in rows if row.is_section_header] == ["表外分区甲", "表外分区乙"]
    assert not any(row.is_group_header for row in rows)


def test_bom_export_should_repair_rowspan_duplicate_codes_before_dotted_continuation():
    """跨行合并导致的重复纯数字序号应补齐为点号子序号。"""
    items = [
        {"name": "光伏组件", "item_code": "1", "section_name": "安装工程"},
        {"name": "组件支架一", "item_code": "1", "section_name": "安装工程"},
        {"name": "组件支架二", "item_code": "1", "section_name": "安装工程"},
        {"name": "逆变器支架", "item_code": "1", "section_name": "安装工程"},
        {"name": "组串式逆变器", "item_code": "1", "section_name": "安装工程"},
        {"name": "箱式变压器", "item_code": "1.6", "section_name": "安装工程"},
        {"name": "箱式变压器二", "item_code": "1.7", "section_name": "安装工程"},
    ]

    rows = _collect_export_rows(items)
    item_rows = [
        row for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]

    assert [row.hierarchy_number for row in item_rows] == [
        "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7",
    ]

    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(generate_bom_xlsx(
        document_title="测试文件",
        items=items,
    ).getvalue()))
    worksheet = workbook.active
    assert [worksheet.cell(row=row_index, column=1).value for row_index in range(6, 13)] == [
        "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7",
    ]


def test_bom_export_should_keep_same_code_when_it_belongs_to_different_sections():
    """不同表外分区可以各自从 1 编号，不能被跨分区去重。"""
    rows = _collect_export_rows([
        {"name": "甲分区明细", "item_code": "1", "section_name": "分区甲"},
        {"name": "乙分区明细", "item_code": "1", "section_name": "分区乙"},
    ])

    item_rows = [
        row for row in rows
        if row.item is not None and not row.is_group_header and not row.is_section_header
    ]
    assert [row.hierarchy_number for row in item_rows] == ["1", "1"]
