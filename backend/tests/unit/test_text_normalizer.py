"""结构化文本格式标记归一化单元测试。"""

from app.utils.text_normalizer import normalize_markup_text


def test_normalize_markup_text_should_decode_entity_and_math_markup():
    """正常场景：实体、加粗和行内公式应转换为可读文本。"""
    value = "说明&#x4E86; **$100 \\times 50$**"

    assert normalize_markup_text(value) == "说明了 100 × 50"


def test_normalize_markup_text_should_keep_plain_currency_expression():
    """边界场景：不含 LaTeX 命令的货币表达式不应误删美元符号。"""
    value = "预算 $100"

    assert normalize_markup_text(value) == value


def test_normalize_markup_text_should_remove_opening_and_closing_html_tags():
    """正常场景：金额与单位被下划线标签拆开时，应保留可识别的文本内容。"""
    value = "<u>2600</u><u> 万元</u>"

    assert normalize_markup_text(value) == "2600   万元"


def test_normalize_markup_text_should_return_non_string_value_unchanged():
    """异常输入场景：非字符串结构化值交由上层类型校验处理。"""
    value = {"input": "测试"}

    assert normalize_markup_text(value) is value
