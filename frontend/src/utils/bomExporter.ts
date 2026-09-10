/**
 * 智能 BOM 成本测算表格导出工具 (bomExporter.ts)
 *
 * 支持将 BOM 成本测算清单分别导出为 Excel (.xlsx) 与 Word (.docx) 文档。
 * 文件命名自动关联当前招标文件名称，表尾包含规范的小写与人民币大写总价统计。
 */

import { apiFetch, API_BASE_URL } from './api';
import { normalizeMarkupText } from './textNormalizer';

/** 原文表格的主分组模式，避免导出时把两种分组语义并行展开。 */
export type BomGroupingMode = 'external' | 'internal' | 'none';
type BomGroupingDisplayMode = BomGroupingMode | 'mixed';

export interface BomExportItem {
  id?: string | number;
  item_code?: string | null;
  name?: string;
  item_name?: string;
  section_name?: string | null;
  part_name?: string | null;
  group_path?: string[] | null;
  source_table_index?: number | null;
  grouping_mode?: BomGroupingMode | string | null;
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

export interface BomExportTreeRow {
  kind: 'section' | 'group' | 'item';
  item?: BomExportItem;
  sectionName?: string;
  groupName?: string;
  hierarchyNumber?: string;
  depth?: number;
  isParent?: boolean;
}

/**
 * 统一清洗表内 BOQ 分组路径，兼容模型返回的对象型路径节点。
 */
function normalizeGroupPath(value: unknown): string[] {
  const values = Array.isArray(value) ? value : value === null || value === undefined ? [] : [value];
  return values.flatMap((item) => {
    const candidate = item && typeof item === 'object'
      ? (item as { input?: unknown; value?: unknown; name?: unknown }).input
        ?? (item as { value?: unknown }).value
        ?? (item as { name?: unknown }).name
      : item;
    const text = exportText(candidate);
    return text ? [text] : [];
  });
}

/**
 * 组合并去重表内分组路径，保留原始层级顺序，避免父节点与路径首节点重复展示。
 */
export function getBomGroupContext(item: Pick<BomExportItem, 'part_name' | 'group_path'>): string[] {
  const partName = exportText(item.part_name);
  const groupPath = normalizeGroupPath(item.group_path);
  const values = partName ? [partName, ...groupPath] : groupPath;
  return values.filter((value, index) => index === 0 || value !== values[index - 1]);
}

/**
 * 读取表内分类上下文；该上下文只用于导出展示，不参与 BOM 父子汇总。
 */
function getGroupContext(item: BomExportItem): string[] {
  return getBomGroupContext(item);
}

/** 只接受解析阶段约定的模式值，避免异常数据改变导出结构。 */
function normalizeBomGroupingMode(value: unknown): BomGroupingMode | null {
  const mode = exportText(value);
  return mode === 'external' || mode === 'internal' || mode === 'none' ? mode : null;
}

/** 汇总导出输入的主模式；兼容没有 grouping_mode 的历史数据。 */
export function resolveBomGroupingDisplayMode(items: BomExportItem[]): BomGroupingDisplayMode {
  const modes = new Set<BomGroupingMode>();
  const collect = (nodes: BomExportItem[]): void => {
    nodes.forEach((item) => {
      if (!item || typeof item !== 'object') return;
      const explicitMode = normalizeBomGroupingMode(item.grouping_mode);
      if (explicitMode) {
        modes.add(explicitMode);
      } else if (exportText(item.section_name)) {
        modes.add('external');
      } else if (getGroupContext(item).length) {
        modes.add('internal');
      }
      if (Array.isArray(item.children)) collect(item.children as BomExportItem[]);
    });
  };
  collect(items);
  modes.delete('none');
  if (modes.size === 0) return 'none';
  if (modes.size === 1) return Array.from(modes)[0];
  return 'mixed';
}


/**
 * 按根项顺序补齐跨行或跨页解析造成的表内分组上下文断点。
 */
function buildRootGroupContexts(items: BomExportItem[], respectSections = true): string[][] {
  const contexts: string[][] = [];
  let activeContext: string[] = [];
  let activePartName = '';
  let previousSection: string | undefined;

  items.forEach((item) => {
    const sectionName = exportText(item.section_name);
    if (respectSections && previousSection !== undefined && sectionName !== previousSection) {
      activeContext = [];
      activePartName = '';
    }
    previousSection = sectionName;

    const explicitPartName = exportText(item.part_name);
    const rawContext = getGroupContext(item);
    let effectiveContext: string[];
    if (explicitPartName) {
      effectiveContext = rawContext.length ? rawContext : [explicitPartName];
      activePartName = explicitPartName;
    } else if (rawContext.length) {
      effectiveContext = activePartName && rawContext[0] !== activePartName
        ? getBomGroupContext({ part_name: activePartName, group_path: rawContext })
        : rawContext;
    } else {
      effectiveContext = activeContext;
    }

    contexts.push(effectiveContext);
    if (effectiveContext.length) activeContext = effectiveContext;
  });

  return contexts;
}

/**
 * 读取节点所属的大分组键，仅使用明确的表内分组上下文，不从名称猜测分组。
 */
function getNumberingGroupKey(item: BomExportItem): string | undefined {
  const groupContext = getGroupContext(item);
  if (groupContext.length) return groupContext[0];
  const children = Array.isArray(item.children) ? item.children : [];
  for (const child of children) {
    if (child && typeof child === 'object') {
      const childGroupKey = getNumberingGroupKey(child as BomExportItem);
      if (childGroupKey) return childGroupKey;
    }
  }
  return undefined;
}

/**
 * 生成表内大分组的根序号，让内部表内分组占用同级序号。
 */
function buildGroupedRootNumberPaths(
  items: BomExportItem[],
  rootGroupContexts: string[][],
): { hasNumberingGroups: boolean; paths: Map<number, number[]> } {
  const groupKeys = items.map((item, itemIndex) => (
    rootGroupContexts[itemIndex]?.[0] || getNumberingGroupKey(item)
  ));
  if (!groupKeys.some(Boolean)) {
    return { hasNumberingGroups: false, paths: new Map() };
  }

  const groupIndices = new Map<string | null, number>();
  const ungroupedItemCounts = new Map<string | null, number>();
  const siblingCounts = new Map<string, number>();
  const groupNumberPaths = new Map<string, number[]>();
  const paths = new Map<number, number[]>();

  items.forEach((item, itemIndex) => {
    const groupKey = groupKeys[itemIndex] || null;
    if (!groupIndices.has(groupKey)) {
      groupIndices.set(groupKey, groupIndices.size + 1);
    }
    const groupIndex = groupIndices.get(groupKey) as number;

    const groupContext = rootGroupContexts[itemIndex] || [];
    if (!groupContext.length) {
      const nextItemCount = (ungroupedItemCounts.get(groupKey) || 0) + 1;
      ungroupedItemCounts.set(groupKey, nextItemCount);
      paths.set(itemIndex + 1, [groupIndex, nextItemCount]);
      return;
    }

    for (let depth = 1; depth <= groupContext.length; depth += 1) {
      const prefix = groupContext.slice(0, depth);
      const prefixKey = prefix.join(' / ');
      if (groupNumberPaths.has(prefixKey)) continue;
      if (depth === 1) {
        groupNumberPaths.set(prefixKey, [groupIndex]);
        continue;
      }
      const parentKey = groupContext.slice(0, depth - 1).join(' / ');
      const nextSiblingNumber = (siblingCounts.get(parentKey) || 0) + 1;
      siblingCounts.set(parentKey, nextSiblingNumber);
      groupNumberPaths.set(prefixKey, [
        ...(groupNumberPaths.get(parentKey) || [groupIndex]),
        nextSiblingNumber,
      ]);
    }

    const contextKey = groupContext.join(' / ');
    const nextItemNumber = (siblingCounts.get(contextKey) || 0) + 1;
    siblingCounts.set(contextKey, nextItemNumber);
    paths.set(itemIndex + 1, [
      ...(groupNumberPaths.get(contextKey) || [groupIndex]),
      nextItemNumber,
    ]);
  });

  return { hasNumberingGroups: true, paths };
}

/**
 * 统一清理导出单元格文本，避免独立调用导出工具时遗漏展示标记。
 */
function exportText(value: unknown, fallback = ''): string {
  const normalized = normalizeMarkupText(value);
  return String(normalized ?? fallback).trim();
}

/**
 * 递归展开 BOM 树，统一保留所有父项、子项和分区切换信息。
 */
export function flattenBomExportItems(items: BomExportItem[] = []): BomExportTreeRow[] {
  const groupingDisplayMode = resolveBomGroupingDisplayMode(items);
  const useExternalSections = groupingDisplayMode === 'external';
  const useInternalGroups = groupingDisplayMode === 'internal';
  const nestedRows: Array<{
    item: BomExportItem;
    sectionName?: string;
    hierarchyNumber: string;
    rootOrdinal: number;
    treePath: number[];
    depth: number;
    isParent: boolean;
    groupContext: string[];
  }> = [];

  const visit = (
    item: BomExportItem,
    path: number[],
    depth: number,
    inheritedSection?: string,
    inheritedGroupContext: string[] = [],
    rootOrdinal = 0,
    rootGroupContext?: string[],
  ): void => {
    const sectionName = useExternalSections
      ? String(item.section_name || '').trim() || inheritedSection
      : undefined;
    const children = Array.isArray(item.children) ? item.children : [];
    const groupContext = useInternalGroups
      ? (rootGroupContext ?? getGroupContext(item))
      : [];
    nestedRows.push({
      item,
      sectionName,
      hierarchyNumber: path.join('.'),
      rootOrdinal,
      treePath: path,
      depth,
      isParent: children.length > 0,
      groupContext: groupContext.length ? groupContext : inheritedGroupContext,
    });
    children.forEach((child, childIndex) => {
      if (child && typeof child === 'object') {
        visit(
          child as BomExportItem,
          [...path, childIndex + 1],
          depth + 1,
          sectionName,
          groupContext.length ? groupContext : inheritedGroupContext,
          rootOrdinal,
        );
      }
    });
  };

  const sectionNames = new Set(
    (() => {
      const names: string[] = [];
      const collect = (nodes: BomExportItem[]): void => {
        nodes.forEach((item) => {
          if (useExternalSections) {
            const sectionName = String(item.section_name || '').trim();
            if (sectionName) names.push(sectionName);
          }
          if (Array.isArray(item.children)) collect(item.children as BomExportItem[]);
        });
      };
      collect(items);
      return names;
    })(),
  );
  const showSectionHeaders = useExternalSections && sectionNames.size > 1;
  const rootGroupContexts = useInternalGroups
    ? buildRootGroupContexts(items, false)
    : items.map(() => []);

  const sectionRootIndices = new Map<string, number>();
  let globalRootIndex = 0;
  items.forEach((item, itemIndex) => {
    if (!item || typeof item !== 'object') return;
    let rootPath: number[];
    if (showSectionHeaders) {
      const sectionKey = String(item.section_name || '').trim() || '__no_section__';
      const sectionItemIndex = (sectionRootIndices.get(sectionKey) || 0) + 1;
      sectionRootIndices.set(sectionKey, sectionItemIndex);
      rootPath = [sectionItemIndex];
    } else {
      globalRootIndex += 1;
      rootPath = [globalRootIndex];
    }
    visit(
      item,
      rootPath,
      0,
      undefined,
      [],
      itemIndex + 1,
      rootGroupContexts[itemIndex] || [],
    );
  });

  const groupedRootPaths = buildGroupedRootNumberPaths(
    items,
    rootGroupContexts,
  );
  let currentRootOrdinal: number | undefined;
  let currentRootBasePath: number[] | undefined;
  let currentSection: string | undefined;
  let currentGroup = '';
  const rows: BomExportTreeRow[] = [];

  nestedRows.forEach((row) => {
    if (groupedRootPaths.hasNumberingGroups) {
      if (row.rootOrdinal !== currentRootOrdinal) {
        currentRootOrdinal = row.rootOrdinal;
        currentRootBasePath = groupedRootPaths.paths.get(row.rootOrdinal);
      }
      if (currentRootBasePath) {
        row.hierarchyNumber = [...currentRootBasePath, ...row.treePath.slice(1)].join('.');
      }
    }
    if (showSectionHeaders && row.sectionName !== currentSection) {
      rows.push({
        kind: 'section',
        sectionName: row.sectionName || '通用及其他分项',
      });
      currentSection = row.sectionName;
      currentGroup = '';
    }
    const groupKey = row.groupContext.join(' / ');
    if (groupKey && groupKey !== currentGroup) {
      const numberParts = row.hierarchyNumber.split('.');
      let commonDepth = 0;
      while (
        commonDepth < currentGroup.split(' / ').length
        && commonDepth < row.groupContext.length
        && currentGroup.split(' / ')[commonDepth] === row.groupContext[commonDepth]
      ) {
        commonDepth += 1;
      }
      for (let groupDepth = commonDepth; groupDepth < row.groupContext.length; groupDepth += 1) {
        rows.push({
          kind: 'group',
          groupName: row.groupContext[groupDepth],
          hierarchyNumber: groupedRootPaths.hasNumberingGroups
            ? numberParts.slice(0, groupDepth + 1).join('.')
            : undefined,
        });
      }
      currentGroup = groupKey;
    } else if (!groupKey) {
      currentGroup = '';
    }
    rows.push({ kind: 'item', ...row });
  });
  return rows;
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
