/**
 * 人民币大写金额转换工具模块 (rmbFormatter.ts)
 *
 * 提供将数值或数字字符串转换为规范人民币大写汉字的工具函数。
 * 算法逻辑与后端 rmb_formatter.py 保持 100% 一致。
 * 例：967840.36 -> 玖拾陆万柒仟捌佰肆拾元叁角陆分
 */

export function numberToChineseRmb(numVal: number | string | null | undefined): string {
  if (numVal === null || numVal === undefined) {
    return '零元整';
  }

  let val: number;
  if (typeof numVal === 'string') {
    const cleanStr = numVal.replace(/,/g, '').replace(/\s+/g, '').trim();
    if (!cleanStr) return '零元整';
    val = parseFloat(cleanStr);
  } else {
    val = Number(numVal);
  }

  if (isNaN(val) || val <= 0) {
    return '零元整';
  }

  const units = ['', '拾', '佰', '仟', '万', '拾', '佰', '仟', '亿', '拾', '佰', '仟'];
  const digits = ['零', '壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖'];

  const numStr = val.toFixed(2);
  const [integerStr, decimalStr] = numStr.split('.');

  const integerVal = parseInt(integerStr, 10);
  const jiao = parseInt(decimalStr[0], 10);
  const fen = parseInt(decimalStr[1], 10);

  if (integerVal === 0 && jiao === 0 && fen === 0) {
    return '零元整';
  }

  let res = '';
  if (integerVal > 0) {
    const length = integerStr.length;
    let zeroFlag = false;
    for (let idx = 0; idx < length; idx++) {
      const d = parseInt(integerStr[idx], 10);
      const pos = length - 1 - idx;
      if (d !== 0) {
        if (zeroFlag) {
          res += '零';
          zeroFlag = false;
        }
        res += digits[d] + units[pos % 12];
      } else {
        zeroFlag = true;
        if (pos % 4 === 0 && pos > 0) {
          res += units[pos % 12];
          zeroFlag = false;
        }
      }
    }
    res += '元';
  }

  if (jiao === 0 && fen === 0) {
    res += '整';
  } else {
    if (jiao > 0) {
      res += digits[jiao] + '角';
    } else if (integerVal > 0 && fen > 0) {
      res += '零';
    }

    if (fen > 0) {
      res += digits[fen] + '分';
    }
  }

  return res;
}

/**
 * 将数值格式化为标准千分位货币字符串 (如 ¥910,065.36)
 */
export function formatCurrency(numVal: number | string | null | undefined): string {
  if (numVal === null || numVal === undefined) return '¥0.00';
  const val = typeof numVal === 'string' ? parseFloat(numVal.replace(/,/g, '')) : Number(numVal);
  if (isNaN(val)) return '¥0.00';
  return `¥${val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
