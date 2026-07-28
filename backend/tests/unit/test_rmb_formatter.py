"""
单元测试：人民币大写金额转换工具 (test_rmb_formatter.py)
"""

import pytest
from app.utils.rmb_formatter import number_to_chinese_rmb


def test_rmb_formatter_basic_integers():
    """测试整数金额转换"""
    assert number_to_chinese_rmb(100) == "壹佰元整"
    assert number_to_chinese_rmb(10000) == "壹万元整"
    assert number_to_chinese_rmb(967840) == "玖拾陆万柒仟捌佰肆拾元整"


def test_rmb_formatter_decimals():
    """测试带角分的浮点数金额转换"""
    assert number_to_chinese_rmb(967840.36) == "玖拾陆万柒仟捌佰肆拾元叁角陆分"
    assert number_to_chinese_rmb("12345.50") == "壹万贰仟叁佰肆拾伍元伍角"
    assert number_to_chinese_rmb(0.05) == "伍分"


def test_rmb_formatter_edge_cases():
    """测试边界与异常条件"""
    assert number_to_chinese_rmb(0) == "零元整"
    assert number_to_chinese_rmb(None) == "零元整"
    assert number_to_chinese_rmb("invalid_str") == "零元整"
    assert number_to_chinese_rmb("") == "零元整"
