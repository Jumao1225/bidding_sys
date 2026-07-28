"""
人民币大写金额转换工具模块 (rmb_formatter.py)

提供将数值/字符串格式的人民币金额转换为标准中文大写的工具函数。
例：967840.36 -> 玖拾陆万柒仟捌佰肆拾元叁角陆分

遵循项目规范：
1. 中文注释与 Docstrings；
2. 类型提示 (Type Hints)；
3. loguru 详细日志记录；
4. 防御性编程与尽早返回 (Early Return)。
"""

from typing import Optional, Union
from loguru import logger


def number_to_chinese_rmb(num_val: Optional[Union[float, int, str]]) -> str:
    """
    将数字或数字字符串转换为人民币汉字大写。

    :param num_val: 浮点数、整数或数字字符串 (如 1234.56, "1234.56")
    :return: 标准人民币大写字符串 (如 "壹仟贰佰叁拾肆元伍角陆分")
    """
    logger.debug(f"收到人民币大写转换请求, 原始输入: {num_val}")

    if num_val is None:
        logger.warning("转换输入为 None，默认返回 '零元整'")
        return "零元整"

    # 类型防御与转换
    try:
        if isinstance(num_val, str):
            # 清理千分位逗号与空格
            clean_str = num_val.replace(",", "").replace(" ", "").strip()
            if not clean_str:
                return "零元整"
            val = float(clean_str)
        else:
            val = float(num_val)
    except (ValueError, TypeError) as e:
        logger.error(f"金额转换失败，非法输入: {num_val}, 错误: {e}")
        return "零元整"

    if val <= 0:
        return "零元整"

    units = ["", "拾", "佰", "仟", "万", "拾", "佰", "仟", "亿", "拾", "佰", "仟"]
    digits = ["零", "壹", "贰", "叁", "肆", "伍", "陆", "柒", "捌", "玖"]

    # 格式化为两位小数
    num_str = f"{val:.2f}"
    integer_str, decimal_str = num_str.split(".")

    integer_val = int(integer_str)
    jiao = int(decimal_str[0])
    fen = int(decimal_str[1])

    if integer_val == 0 and jiao == 0 and fen == 0:
        return "零元整"

    res = ""
    if integer_val > 0:
        length = len(str(integer_val))
        zero_flag = False
        for idx, char in enumerate(str(integer_val)):
            d = int(char)
            pos = length - 1 - idx
            if d != 0:
                if zero_flag:
                    res += "零"
                    zero_flag = False
                res += digits[d] + units[pos % 12]
            else:
                zero_flag = True
                if pos % 4 == 0 and pos > 0:
                    res += units[pos % 12]
                    zero_flag = False
        res += "元"

    if jiao == 0 and fen == 0:
        res += "整"
    else:
        if jiao > 0:
            res += digits[jiao] + "角"
        elif integer_val > 0 and fen > 0:
            res += "零"

        if fen > 0:
            res += digits[fen] + "分"

    logger.info(f"人民币大写转换成功: {num_val} -> {res}")
    return res
