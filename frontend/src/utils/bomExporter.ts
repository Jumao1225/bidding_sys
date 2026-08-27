/**
 * 智能 BOM 成本测算表格导出工具 (bomExporter.ts)
 *
 * 支持将 BOM 成本测算清单分别导出为 Excel/CSV 表格与 Word (.docx) 文档。
 * 文件命名自动关联当前招标文件名称，表尾包含规范的小写与人民币大写总价统计。
 */

import { apiFetch, API_BASE_URL } from './api';
import { numberToChineseRmb } from './rmbFormatter';

export interface BomExportItem {
  id?: string | number;
  item_code?: string | null;
  name?: string;
  item_name?: string;
  section_name?: string | null;
  spec_requirement?: string | null;
  key_parameters?: string[] | any;
  matched_name?: string | null;
  matched_brand?: string | null;
  matched_model?: string | null;
  matched_manufacturer?: string | null;
  brand?: string | null;
  model?: string | null;
  manufacturer?: string | null;
  match_quality?: string | null;
  qty?: number | null;
  quantity?: number | null;
  unit?: string | null;
  ref_price?: number | null;
  price?: number | null;
  subtotal?: number | null;
  remark?: string | null;
  isParent?: boolean;
  children?: any[];
  [key: string]: any;
}

export interface BomExportOptions {
  documentId?: string;
  documentTitle?: string;
  items: BomExportItem[];
  totalCost?: number;
  budgetLimit?: string;
  statusText?: string;
  analysisSummary?: string;
}

/**
 * 清理并提取纯粹的招标文件标题（去除 .pdf / .docx 等后缀）
 */
export function cleanDocumentTitle(title?: string | null): string {
  if (!title || typeof title !== 'string') return '招标文件';
  const trimmed = title.trim();
  if (!trimmed) return '招标文件';
  return trimmed.replace(/\.(pdf|docx|doc|xlsx|xls|txt)$/i, '').trim() || '招标文件';
}

/**
 * 转义 CSV 单元格内容（包含逗号、换行或双引号时包裹双引号，并对内部双引号进行转义）
 */
function escapeCsvCell(val: unknown): string {
  if (val === null || val === undefined) return '';
  const str = String(val);
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * 导出为 Excel / CSV (.csv) 表格
 */
export function exportBomToCsv(options: BomExportOptions): void {
  const {
    documentTitle,
    items = [],
    totalCost = 0,
    budgetLimit,
    statusText,
    analysisSummary
  } = options;

  const cleanTitle = cleanDocumentTitle(documentTitle);
  const totalCostUpper = numberToChineseRmb(totalCost);
  const nowStr = new Date().toLocaleString('zh-CN', { hour12: false });

  const csvRows: string[] = [];

  // 1. 顶部项目与测算信息
  csvRows.push([escapeCsvCell('拟投入设备及 BOM 成本测算清单')].join(','));
  csvRows.push([escapeCsvCell('关联招标文件'), escapeCsvCell(cleanTitle)].join(','));
  csvRows.push([escapeCsvCell('导出时间'), escapeCsvCell(nowStr)].join(','));
  if (budgetLimit) {
    csvRows.push([escapeCsvCell('最高投标限价/预算'), escapeCsvCell(budgetLimit)].join(','));
  }
  if (statusText) {
    csvRows.push([escapeCsvCell('预算控制状态'), escapeCsvCell(statusText)].join(','));
  }
  csvRows.push(''); // 空行分隔

  // 2. 表头（严格对齐规范 9 列格式）
  const headers = [
    '序号',
    '标的物名称',
    '品牌、规格、型号',
    '生产厂家',
    '单位',
    '数量',
    '单价(元)',
    '总价(元)',
    '备注'
  ];
  csvRows.push(headers.map(escapeCsvCell).join(','));

  // 3. 数据行
  items.forEach((item, idx) => {
    const name = item.name || item.item_name || '';
    
    // 品牌、规格、型号组合
    const brand = String(item.matched_brand || item.brand || '').trim();
    const model = String(item.matched_model || item.model || '').trim();
    const brandSpecModelParts: string[] = [];
    if (brand && model) {
      brandSpecModelParts.push(`${brand} ${model}`);
    } else if (brand) {
      brandSpecModelParts.push(brand);
    } else if (model) {
      brandSpecModelParts.push(model);
    } else {
      brandSpecModelParts.push('--');
    }
    const brandSpecModelText = brandSpecModelParts.join(' / ');

    const manufacturer = String(item.matched_manufacturer || item.manufacturer || '--').trim();
    const unit = item.unit || '项';
    const qty = item.qty !== undefined && item.qty !== null ? item.qty : (item.quantity ?? 1);
    const price = item.ref_price !== undefined && item.ref_price !== null ? item.ref_price : (item.price ?? 0);
    const subtotal = item.subtotal !== undefined && item.subtotal !== null ? item.subtotal : (Number(qty) * Number(price));

    // 备注列：严格使用前端 BOM 清单的备注 (remark) 字段
    const remarkText = String(item.remark || '').trim();

    const row = [
      idx + 1,
      name,
      brandSpecModelText,
      manufacturer,
      unit,
      qty,
      Number(price).toFixed(2),
      Number(subtotal).toFixed(2),
      remarkText
    ];
    csvRows.push(row.map(escapeCsvCell).join(','));
  });

  // 4. 表尾统计行（包含小写金额与人民币大写总价）
  csvRows.push(''); // 空行分隔
  csvRows.push([
    escapeCsvCell('【合计】预估总成本（小写）'),
    '',
    '',
    '',
    '',
    '',
    '',
    escapeCsvCell(`¥${Number(totalCost).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`),
    escapeCsvCell(`人民币（大写）${totalCostUpper}`)
  ].join(','));

  if (budgetLimit) {
    csvRows.push([
      escapeCsvCell('【基准】最高投标限价/预算'),
      escapeCsvCell(budgetLimit),
      '',
      escapeCsvCell('【状态】预算达标情况'),
      escapeCsvCell(statusText || '正常')
    ].join(','));
  }

  if (analysisSummary) {
    csvRows.push([
      escapeCsvCell('【专家评估指导意见】'),
      escapeCsvCell(analysisSummary)
    ].join(','));
  }

  // 5. UTF-8 BOM (\uFEFF) 构造 Blob 并触发下载
  const csvContent = '\uFEFF' + csvRows.join('\r\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `【BOM成本测算清单】${cleanTitle}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/**
 * 导出为 Word (.docx) 文档（调用后端高保真 python-docx 渲染接口）
 */
export async function exportBomToDocx(options: BomExportOptions): Promise<void> {
  const {
    documentId,
    documentTitle,
    items = [],
    totalCost = 0,
    budgetLimit,
    statusText,
    analysisSummary
  } = options;

  const cleanTitle = cleanDocumentTitle(documentTitle);
  const docId = documentId || 'current';

  const response = await apiFetch(`${API_BASE_URL}/api/v1/analysis/${docId}/export-bom-docx`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      document_title: cleanTitle,
      items,
      total_cost: totalCost,
      budget_limit: budgetLimit,
      status_text: statusText,
      analysis_summary: analysisSummary
    })
  });

  if (!response.ok) {
    const errJson = await response.json().catch(() => ({}));
    throw new Error(errJson.detail || '导出 Word 文档失败');
  }

  const blob = await response.blob();
  const contentDisposition = response.headers.get('Content-Disposition') || '';
  let filename = `【BOM成本测算清单】${cleanTitle}.docx`;

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (utf8Match && utf8Match[1]) {
    try {
      filename = decodeURIComponent(utf8Match[1]);
    } catch {
      filename = utf8Match[1];
    }
  } else if (plainMatch && plainMatch[1]) {
    try {
      filename = decodeURIComponent(plainMatch[1]);
    } catch {
      filename = plainMatch[1];
    }
  }

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/**
 * 导出为标准 Excel 工作簿 (.xlsx) 文档（调用后端 openpyxl 高保真渲染接口）
 */
export async function exportBomToXlsx(options: BomExportOptions): Promise<void> {
  const {
    documentId,
    documentTitle,
    items = [],
    totalCost = 0,
    budgetLimit,
    statusText,
    analysisSummary
  } = options;

  const cleanTitle = cleanDocumentTitle(documentTitle);
  const docId = documentId || 'current';

  const response = await apiFetch(`${API_BASE_URL}/api/v1/analysis/${docId}/export-bom-xlsx`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      document_title: cleanTitle,
      items,
      total_cost: totalCost,
      budget_limit: budgetLimit,
      status_text: statusText,
      analysis_summary: analysisSummary
    })
  });

  if (!response.ok) {
    const errJson = await response.json().catch(() => ({}));
    throw new Error(errJson.detail || '导出 Excel 工作簿失败');
  }

  const blob = await response.blob();
  const contentDisposition = response.headers.get('Content-Disposition') || '';
  let filename = `【BOM成本测算清单】${cleanTitle}.xlsx`;

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (utf8Match && utf8Match[1]) {
    try {
      filename = decodeURIComponent(utf8Match[1]);
    } catch {
      filename = utf8Match[1];
    }
  } else if (plainMatch && plainMatch[1]) {
    try {
      filename = decodeURIComponent(plainMatch[1]);
    } catch {
      filename = plainMatch[1];
    }
  }

  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

