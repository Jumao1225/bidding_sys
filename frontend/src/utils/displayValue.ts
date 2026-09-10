/**
 * 将后端返回的动态 JSON 值转换为可安全展示的文本。
 * AI 提取结果允许出现嵌套对象，不能把对象直接作为 React 子节点渲染。
 */
export function format_analysis_value(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }

  if (typeof value === 'string') {
    return value;
  }

  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => format_analysis_value(item))
      .filter(Boolean)
      .join('；');
  }

  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested_value]) => {
        const nested_text = format_analysis_value(nested_value);
        return nested_text ? `${key}：${nested_text}` : key;
      })
      .join('；');
  }

  return '';
}
