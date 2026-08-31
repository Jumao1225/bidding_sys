"""
标的物清单表格智能过滤提取单元测试 (test_equipment_table_filter.py)
"""

import pytest
from app.utils.table_utils import extract_equipment_tables_and_context

def test_extract_equipment_tables_and_context_preserves_all_table_blocks():
    """测试后端只做表格结构识别，不因固定业务关键词丢弃表格。"""
    sample_text = """
    # 第四章 项目需求与施工规范
    
    一、通用法律与安全条款
    本工程施工必须严格执行国家各项安全生产法规，落实五险一金政策，严禁非法用工。
    投标人必须为所有进场人员购买人身意外伤害险，保额不低于100万元。
    
    二、人员资质要求
    <table>
        <tr><th>序号</th><th>岗位</th><th>姓名</th><th>执业证书</th><th>社保缴纳</th></tr>
        <tr><td>1</td><td>项目经理</td><td>张三</td><td>一级建造师</td><td>已缴纳</td></tr>
    </table>
    
    三、主要设备与材料需求一览表
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>备注</th></tr>
        <tr><td>1</td><td>2000kVA光伏升压箱变</td><td>2000kVA, 10kV</td><td>套</td><td>4</td><td>主要标的物</td></tr>
        <tr><td>2</td><td>10kV高压真空断路器</td><td>12kV, 630A, 25kA</td><td>台</td><td>4</td><td>箱变内部配套</td></tr>
    </table>
    
    四、现场特殊工况与要求
    现场临近水域，必须搭设水上作业平台并做好防倾覆措施。

    五、安全文明施工违章库
    <table>
        <tr><th>工序</th><th>违章分类</th><th>违章等级</th></tr>
        <tr><td>通用</td><td>管理违章</td><td>一类</td></tr>
    </table>
    """
    
    filtered = extract_equipment_tables_and_context(sample_text)
    
    # 所有表格都交给大模型判断，避免不同文件使用不同列名时漏表。
    assert "一级建造师" in filtered
    assert "执业证书" in filtered
    assert "2000kVA光伏升压箱变" in filtered
    assert "10kV高压真空断路器" in filtered
    assert "主要设备与材料需求一览表" in filtered
    assert "水上作业平台" in filtered
    assert "管理违章" in filtered

def test_extract_equipment_tables_and_context_empty_fallback():
    """测试空文本与无表格文本的安全兜底"""
    assert extract_equipment_tables_and_context("") == ""
    assert extract_equipment_tables_and_context(None) == ""
    
    plain_text = "这是一段纯文字描述，没有任何表格。"
    assert extract_equipment_tables_and_context(plain_text) == plain_text


def test_extract_equipment_tables_and_context_keeps_split_boq_continuation():
    """测试工程量清单跨页拆成无重复表头的续表时仍能完整保留。"""
    sample_text = """
    附件1：工程量清单及报价明细、设备材料品牌表
    <table>
        <tr><th>序号</th><th>项目名称</th><th>项目特征</th><th>单位</th><th>数量</th></tr>
        <tr><td>1</td><td>设备A</td><td>满足施工规范要求</td><td>台</td><td>2</td></tr>
    </table>
    <table>
        <tr><td>2</td><td>设备B</td><td>续表项目，满足施工规范要求</td><td>m</td><td>10</td></tr>
    </table>

    设备材料品牌表
    <table>
        <tr><th>类别</th><th>合格供应商名单</th></tr>
        <tr><td>电缆</td><td>品牌A</td></tr>
    </table>
    """

    filtered = extract_equipment_tables_and_context(sample_text)

    assert "设备A" in filtered
    assert "设备B" in filtered
    assert "品牌A" in filtered


def test_extract_equipment_tables_and_context_preserves_context_without_section_keywords():
    """测试没有固定分区关键词时，表格和表前上下文仍完整保留。"""
    sample_text = """
    ## 合同条款
    <table>
        <tr><th>货物名称</th><th>数量</th><th>单位</th><th>单价</th></tr>
        <tr><td></td><td></td><td></td><td></td></tr>
    </table>

    ## 项目需求
    **某区域**
    本区域包含屋面光伏及配套电气设备，具体数量以本表为准。
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>技术要求</th></tr>
        <tr><td>1</td><td>设备A</td><td>型号A</td><td>台</td><td>2</td><td>满足要求</td></tr>
    </table>

    **另一区域**
    <table>
        <tr><th>序号</th><th>设备名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>技术要求</th></tr>
        <tr><td>1</td><td>设备B</td><td>型号B</td><td>台</td><td>3</td><td>满足要求</td></tr>
    </table>

    ## 投标人员信息
    <table>
        <tr><th>序号</th><th>姓名</th><th>证书</th><th>备注</th></tr>
        <tr><td>1</td><td>人员A</td><td>证书A</td><td>已提供</td></tr>
    </table>

    ## 供货一览表
    <table>
        <tr><th>序号</th><th>货物名称</th><th>规格型号</th><th>单位</th><th>数量</th></tr>
        <tr><td></td><td></td><td></td><td></td><td></td></tr>
    </table>
    """

    filtered = extract_equipment_tables_and_context(sample_text)

    assert filtered.count("<table>") == 5
    assert "设备A" in filtered
    assert "设备B" in filtered
    assert "**某区域**" in filtered
    assert "本区域包含屋面光伏及配套电气设备" in filtered
    assert "**另一区域**" in filtered
    assert "人员A" in filtered
    assert "货物名称" in filtered


def test_extract_equipment_tables_and_context_recognizes_generic_name_header_with_boq_title():
    """测试使用通用“名称”表头的项目需求清单能够被识别。"""
    sample_text = """
    ## 项目需求
    4、项目需求清单（某类设备部分）
    <table>
        <tr><th>序号</th><th>名称</th><th>规格</th><th>单位</th><th>数量</th><th>备注</th></tr>
        <tr><td>1</td><td>设备A</td><td>型号A</td><td>套</td><td>2</td><td>主要标的物</td></tr>
    </table>
    """

    filtered = extract_equipment_tables_and_context(sample_text)

    assert filtered.count("<table>") == 1
    assert "4、项目需求清单（某类设备部分）" in filtered
    assert "设备A" in filtered
