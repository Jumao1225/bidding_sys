/**
 * 清理结构化文本中常见的 HTML 实体、Markdown 加粗和行内 LaTeX 标记。
 */
export function normalizeMarkupText(value: unknown): unknown {
  if (typeof value !== 'string') return value;

  let normalized = value;
  // 兼容历史数据中的二次实体转义，限制次数避免反复解码。
  for (let index = 0; index < 2; index += 1) {
    const decoded = normalized.replace(/&#x([\da-f]+);|&#(\d+);|&(amp|lt|gt|quot);/gi, (entity, hex, decimal, named) => {
      if (hex) return String.fromCodePoint(Number.parseInt(hex, 16));
      if (decimal) return String.fromCodePoint(Number.parseInt(decimal, 10));
      const namedEntities: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"' };
      return namedEntities[String(named).toLowerCase()] ?? entity;
    });
    if (decoded === normalized) break;
    normalized = decoded;
  }

  const latexSymbols: Record<string, string> = {
    times: '×', cdot: '·', pm: '±', ge: '≥', le: '≤', ne: '≠',
    approx: '≈', rightarrow: '→', leftarrow: '←', degree: '°', '%': '%',
  };
  const replaceMath = (_match: string, content: string): string => content
    .replace(/\\([A-Za-z]+|%)/g, (_command, name: string) => latexSymbols[name] ?? '')
    .replace(/\\([{}])/g, '$1')
    .replace(/[{}]/g, '')
    .trim();

  normalized = normalized.replace(/<[A-Za-z][^>]*>/g, ' ');
  normalized = normalized.replace(/\$\$(.*?)\$\$/gs, replaceMath);
  normalized = normalized.replace(/\$(?=[^$\r\n]*\\(?:[A-Za-z]+|%))([^$\r\n]+?)\$/g, replaceMath);
  normalized = normalized.replace(/\*\*(.*?)\*\*/gs, '$1');
  return normalized.trim();
}
