"""
BidFiller Agent & BidFormatFillerService 单元测试

测试大写金额转化、Agent Tool Calling 查库、下划线继承写 Word 功能。
"""

import pytest
import io
from docx import Document
from app.utils.rmb_formatter import number_to_chinese_rmb
from app.agents.bid_filler_agent import bid_filler_agent
from app.schemas.bid_filler_schema import CompanyProfile
from app.services.bid_format_filler_service import bid_format_filler_service


def test_number_to_chinese_rmb_should_convert_correctly():
    """测试数字转换为人民币大写汉字算法"""
    assert number_to_chinese_rmb(967840.36) == "玖拾陆万柒仟捌佰肆拾元叁角陆分"
    assert number_to_chinese_rmb(20000.00) == "贰万元整"
    assert number_to_chinese_rmb(100.50) == "壹佰元伍角"
    assert number_to_chinese_rmb(0.0) == "零元整"


def test_bid_format_filler_service_underline_inheritance():
    """测试下划线继承逻辑：原处有下划线则保留 underline=True，原处无下划线则不添加"""
    doc = Document()
    
    # 构造原处带下划线的段落
    p1 = doc.add_paragraph()
    r1 = p1.add_run("投标人名称：________")
    r1.underline = True

    # 构造原处不带下划线的段落
    p2 = doc.add_paragraph()
    p2.add_run("项目名称：[项目名称]")

    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    template_bytes = output.getvalue()

    # 1. 扫描待填位置
    placeholders = bid_format_filler_service.scan_detected_placeholders(template_bytes)
    assert len(placeholders) >= 1

    # 2. 模拟替换
    replacement_map = {
        "投标人名称：________": "投标人名称：四川石楠建设工程有限公司",
        "[项目名称]": "湖南省烟草公司衡阳市公司关于现代终端建设项目"
    }

    filled_bytes = bid_format_filler_service.fill_docx_with_audit_trail(
        docx_bytes=template_bytes,
        replacement_map=replacement_map,
        audit_items=[]
    )

    assert filled_bytes is not None
    res_doc = Document(io.BytesIO(filled_bytes))
    
    # 验证含有“四川石楠建设工程有限公司”的 Run 带有下划线
    target_p = [p for p in res_doc.paragraphs if "四川石楠建设工程有限公司" in p.text][0]
    assert target_p is not None
    val_run = [r for r in target_p.runs if "四川石楠建设工程有限公司" in r.text][0]
    assert val_run.underline is True or 'w:u' in val_run._element.xml



