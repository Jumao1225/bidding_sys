import React, { useState, useEffect } from 'react';
import { 
  App as AntdApp,
  ConfigProvider, 
  Table, 
  Tag, 
  Input, 
  InputNumber, 
  Button, 
  Tooltip, 
  Popconfirm,
  Empty,
  Dropdown,
  Modal,
  Select
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import zhCN from 'antd/locale/zh_CN';
import { 
  CheckOutlined, 
  CloseOutlined, 
  EditOutlined, 
  DeleteOutlined, 
  PlusOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  DownOutlined,
  UpOutlined,
  DownloadOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  PlusCircleOutlined,
  UndoOutlined,
  SwapOutlined
} from '@ant-design/icons';
import { apiFetch, API_BASE_URL } from '../utils/api';
import { exportBomToDocx, exportBomToXlsx, getBomGroupContext } from '../utils/bomExporter';
import { normalizeMarkupText } from '../utils/textNormalizer';

/** 原文表格的主分组模式。该类型只描述解析语义，不绑定具体业务名称。 */
export type CostGroupingMode = 'external' | 'internal' | 'none';
type CostGroupingDisplayMode = CostGroupingMode | 'mixed';

/**
 * 树形节点物料数据接口
 */
interface CostItemNode {
  key: string;
  originalIndex: number;
  id?: string;
  /** 稳定的 BOM 节点标识，避免同名标的物发生父子串挂。 */
  node_id?: string;
  /** 稳定的父节点标识；为空表示顶层标的物。 */
  parent_node_id?: string | null;
  /** 同级节点排序值。 */
  sort_order?: number;
  item_code?: string | null;
  name: string;
  brand?: string;
  model?: string;
  manufacturer?: string;
  spec_requirement?: string;
  qty: number | null;
  unit: string | null;
  ref_price: number;
  subtotal?: number;
  matched_name?: string;
  matched_brand?: string;
  matched_model?: string;
  matched_manufacturer?: string;
  key_parameters?: string[];
  brand_requirements?: string;
  match_quality?: string;
  warning?: string;
  comparison_note?: string;
  remark?: string;
  parent_item?: string | null;
  root_item?: string | null;
  tree_level?: number;
  per_set_qty?: number | string | null;
  per_set_quantity?: number | string | null;
  part_name?: string | null;
  group_path?: string[];
  section_name?: string | null;
  source_table_index?: number | null;
  grouping_mode?: CostGroupingMode | string | null;
  /** 分组筛选时仅用于保留 BOM 层级路径的父节点，不代表该父节点属于当前分组。 */
  isInternalFilterContextNode?: boolean;
  isParent?: boolean;
  childCount?: number;
  isRollupPrice?: boolean;
  isPartialRollup?: boolean;
  rollupChildCount?: number;
  missingChildPriceCount?: number;
  children?: CostItemNode[];
  // 基线快照与父子互斥状态属性
  is_parent_modified?: boolean;
  is_child_modified?: boolean;
  is_custom_added?: boolean;
  pricing_mode?: 'parent' | 'children' | 'auto';
  isLockedByParent?: boolean;
  isLockedByChildren?: boolean;
  hasModifiedChildren?: boolean;
  hasPricedChildren?: boolean;
  raw_ref_price?: number;
  raw_brand?: string;
  raw_model?: string;
  raw_manufacturer?: string;
  raw_spec?: string;
  raw_qty?: number;
  raw_unit?: string;
  raw_name?: string;
  raw_match_quality?: string;
}

interface CostTableProps {
  documentId?: string;
  documentFilename?: string;
  equipmentList?: any[];
  financial?: any;
  costAnalysis?: any;
  onReextract?: () => void;
  onReextractEquipment?: () => void;
  onCostUpdated?: (updatedData: any) => void;
  isRetrying?: boolean;
  isExtractingEquipment?: boolean;
  // 工程清单刚提取完成时，只展示原始清单，不读取旧成本结果，也不触发价格匹配。
  isEquipmentOnly?: boolean;
}

/** BOM 表格支持拖拽调整的列标识。 */
export type CostTableColumnKey =
  | 'name'
  | 'matched_name'
  | 'match_quality'
  | 'qty'
  | 'ref_price'
  | 'subtotal'
  | 'remark'
  | 'action';

/** 操作按钮采用 Ant Design small 尺寸时的实际占位宽度。 */
const COST_TABLE_ACTION_BUTTON_WIDTH = 24;
/** 操作按钮组使用 Tailwind gap-0.5，对应 2px 间距。 */
const COST_TABLE_ACTION_BUTTON_GAP = 2;
/** 固定操作列左右内边距与边界安全余量。 */
const COST_TABLE_ACTION_HORIZONTAL_PADDING = 12;
/** 常态操作按钮数量，覆盖未显示条件按钮时的基础操作集合。 */
const COST_TABLE_BASE_ACTION_BUTTON_COUNT = 5;
/** 数量输入框在编辑态的最低可用宽度，覆盖常见的多位数量。 */
const COST_TABLE_QTY_INPUT_MIN_WIDTH = 64;
/** 单字单位输入框的最低可用宽度，同时保留“单位”占位提示。 */
const COST_TABLE_UNIT_INPUT_MIN_WIDTH = 40;
/** 数量和单位输入框之间的间距。 */
const COST_TABLE_QTY_INPUT_GAP = 4;
/** 数量列左右单元格内边距的总和。 */
const COST_TABLE_QTY_CELL_HORIZONTAL_PADDING = 16;
/** 数量/单位列的基础最低宽度，按实际编辑控件占位计算。 */
const COST_TABLE_QTY_COLUMN_MIN_WIDTH =
  COST_TABLE_QTY_INPUT_MIN_WIDTH
  + COST_TABLE_UNIT_INPUT_MIN_WIDTH
  + COST_TABLE_QTY_INPUT_GAP
  + COST_TABLE_QTY_CELL_HORIZONTAL_PADDING;
/** 多选列的固定预留宽度，需计入横向滚动总宽度。 */
const COST_TABLE_SELECTION_COLUMN_WIDTH = 40;
/** 主布局顶部导航栏的固定高度，与 MainLayout 中的 h-20 保持一致。 */
const COST_TABLE_GLOBAL_HEADER_HEIGHT = 80;
/** 顶部横向滚动条的紧凑高度，避免表格上方出现突兀的大块空白。 */
const COST_TABLE_HORIZONTAL_SCROLLBAR_HEIGHT = 10;
/** 表头吸顶位置，预留主导航栏和顶部横向滚动条的空间。 */
const COST_TABLE_STICKY_HEADER_TOP =
  COST_TABLE_GLOBAL_HEADER_HEIGHT + COST_TABLE_HORIZONTAL_SCROLLBAR_HEIGHT;

/** 各列拖拽时的最小宽度，保证编辑控件和操作按钮仍可用。 */
export const COST_TABLE_COLUMN_MIN_WIDTHS: Record<CostTableColumnKey, number> = {
  name: 240,
  matched_name: 220,
  match_quality: 90,
  qty: COST_TABLE_QTY_COLUMN_MIN_WIDTH,
  ref_price: 110,
  subtotal: 110,
  remark: 100,
  // 五个常态操作按钮的最低宽度，实际有条件按钮时会动态增加。
  action:
    COST_TABLE_BASE_ACTION_BUTTON_COUNT * COST_TABLE_ACTION_BUTTON_WIDTH
    + (COST_TABLE_BASE_ACTION_BUTTON_COUNT - 1) * COST_TABLE_ACTION_BUTTON_GAP
    + COST_TABLE_ACTION_HORIZONTAL_PADDING,
};

/** 将用户拖拽后的列宽约束为合法整数，并保留各列的最低可用宽度。 */
export function normalizeCostTableColumnWidth(
  columnKey: string,
  width: number,
  minimumWidth?: number,
): number {
  const defaultMinWidth = COST_TABLE_COLUMN_MIN_WIDTHS[columnKey as CostTableColumnKey] || 80;
  const minWidth = Number.isFinite(minimumWidth) && (minimumWidth as number) > 0
    ? Math.max(defaultMinWidth, Math.round(minimumWidth as number))
    : defaultMinWidth;
  if (!Number.isFinite(width)) return minWidth;
  return Math.max(minWidth, Math.round(width));
}

type CostTableActionRecord = Pick<
  CostItemNode,
  | 'isParent'
  | 'parent_node_id'
  | 'is_parent_modified'
  | 'pricing_mode'
  | 'hasModifiedChildren'
  | 'is_child_modified'
  | 'match_quality'
  | 'isLockedByParent'
>;

/** 根据行状态计算实际会展示的操作按钮数量，避免固定列预留无效空白。 */
export function getCostTableActionButtonCount(record: CostTableActionRecord): number {
  if (record.isParent) {
    const isParentModified = Boolean(record.is_parent_modified || record.pricing_mode === 'parent');
    const hasModifiedChildren = Boolean(record.hasModifiedChildren);

    return COST_TABLE_BASE_ACTION_BUTTON_COUNT
      + Number(Boolean(record.parent_node_id))
      + Number(isParentModified)
      + Number(hasModifiedChildren);
  }

  const isLockedByParent = Boolean(record.isLockedByParent);
  const isChildModified = Boolean(
    record.is_child_modified || record.match_quality === '手动修改',
  );

  return COST_TABLE_BASE_ACTION_BUTTON_COUNT
    + Number(Boolean(record.parent_node_id))
    + Number(isChildModified && !isLockedByParent);
}

/** 根据当前清单中最多的操作按钮数量计算操作列的动态最小宽度。 */
export function getCostTableActionMinimumWidth(
  records: ReadonlyArray<CostTableActionRecord>,
): number {
  const maxButtonCount = records.reduce(
    (currentMax, record) => Math.max(currentMax, getCostTableActionButtonCount(record)),
    COST_TABLE_BASE_ACTION_BUTTON_COUNT,
  );

  return maxButtonCount * COST_TABLE_ACTION_BUTTON_WIDTH
    + (maxButtonCount - 1) * COST_TABLE_ACTION_BUTTON_GAP
    + COST_TABLE_ACTION_HORIZONTAL_PADDING;
}

/** 计算整张 BOM 表所需的真实横向滚动宽度，保证所有列都能通过滚动查看。 */
export function getCostTableScrollWidth(
  columnWidths: ReadonlyArray<number | string | undefined>,
  selectionColumnWidth = 0,
): number {
  const columnWidthTotal = columnWidths.reduce<number>(
    (total, width) => total + (typeof width === 'number' && Number.isFinite(width) ? width : 0),
    0,
  );
  const safeSelectionColumnWidth = Number.isFinite(selectionColumnWidth) && selectionColumnWidth > 0
    ? selectionColumnWidth
    : 0;

  return Math.max(1, Math.ceil(columnWidthTotal + safeSelectionColumnWidth));
}

interface ResizableHeaderCellProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  width?: number;
  onResize?: (width: number) => void;
}

/** 使用原生 Pointer Events 实现表头右侧拖拽，避免额外引入表格拖拽依赖。 */
function ResizableHeaderCell({
  width,
  onResize,
  children,
  ...restProps
}: ResizableHeaderCellProps) {
  const [isResizing, setIsResizing] = React.useState(false);

  const handlePointerDown = (event: React.PointerEvent<HTMLSpanElement>) => {
    if (!onResize || !width) return;
    event.preventDefault();
    event.stopPropagation();

    const startX = event.clientX;
    const startWidth = width;
    const pointerId = event.pointerId;
    const resizeHandle = event.currentTarget;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;

    const handlePointerMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault();
      onResize(startWidth + moveEvent.clientX - startX);
    };
    const handlePointerUp = () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
      window.removeEventListener('pointercancel', handlePointerUp);
      window.removeEventListener('blur', handlePointerUp);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      if (resizeHandle.hasPointerCapture(pointerId)) {
        resizeHandle.releasePointerCapture(pointerId);
      }
      setIsResizing(false);
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    resizeHandle.setPointerCapture(pointerId);
    setIsResizing(true);
    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);
    window.addEventListener('pointercancel', handlePointerUp);
    window.addEventListener('blur', handlePointerUp);
  };

  return (
    <th {...restProps} style={{ ...restProps.style, width }}>
      {children}
      {onResize && width ? (
        <span
          className={`cost-table-resize-handle${isResizing ? ' is-resizing' : ''}`}
          role="separator"
          aria-orientation="vertical"
          aria-label="拖动调整此列宽度"
          title="拖动调整列宽"
          onPointerDown={handlePointerDown}
        />
      ) : null}
    </th>
  );
}

/**
 * 将接口或历史数据中的结构化值安全转换为可展示文本。
 * 兼容 {type, input} 等旧版结构化输出，避免 React 直接渲染对象。
 */
export function normalizeCostText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return String(normalizeMarkupText(value));
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    return value.map(normalizeCostText).filter(Boolean).join('；');
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    for (const key of ['input', 'text', 'value', 'content']) {
      if (key in record) {
        const nestedText = normalizeCostText(record[key]);
        if (nestedText) return nestedText;
      }
    }
    try {
      return JSON.stringify(value);
    } catch (error) {
      console.warn('成本分析字段序列化失败，已使用空文本兜底。', error);
      return '';
    }
  }
  return String(value);
}

/**
 * 归一化关键参数数组，保证展示和保存时始终符合后端 List[str] 契约。
 */
export function normalizeCostTextList(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  const values = Array.isArray(value) ? value : [value];
  return values.map(normalizeCostText).filter(Boolean);
}

/** 解析新增标的物的默认单位；父项为设备面数或台数时沿用设备单位，其余通用分项使用“项”。 */
export function resolveCostNewNodeUnit(parentUnit: unknown): string {
  const normalizedUnit = normalizeCostText(parentUnit).trim();
  return normalizedUnit === '面' || normalizedUnit === '台' ? '台' : '项';
}

/**
 * 判断成本行是否存在可展示的表内分组上下文，避免空数组长度 0 被 React 当作文本渲染。
 */
export function hasBomGroupContext(item: Pick<CostItemNode, 'part_name' | 'group_path'>): boolean {
  const partName = normalizeCostText(item.part_name).trim();
  const groupPath = normalizeCostTextList(item.group_path);
  return Boolean(partName || groupPath.length > 0);
}

/**
 * 生成表内分组徽章文本，避免筛选结果中的路径父节点被误认为属于当前分组。
 */
export function getCostInternalGroupDisplayText(
  item: Pick<CostItemNode, 'part_name' | 'group_path'> & {
    isInternalFilterContextNode?: boolean;
  },
  selectedPart: string,
): string {
  const normalizedSelectedPart = normalizeCostText(selectedPart).trim();
  if (item.isInternalFilterContextNode && normalizedSelectedPart !== 'ALL') {
    return '当前筛选项的父级路径';
  }
  // 筛选命中行统一显示当前选中的主分组，避免历史 group_path 残留的其他分类名称串组。
  if (
    normalizedSelectedPart !== 'ALL'
    && normalizeCostText(item.part_name).trim() === normalizedSelectedPart
  ) {
    return normalizedSelectedPart;
  }
  return getBomGroupContext(item).slice(-1)[0] || '';
}

/**
 * 同步修改表内分组路径，并保留目标路径下更深层的子分组。
 * 主分组为空时拒绝保存；末级分组为空时使用主分组作为唯一层级。
 */
export function updateCostGroupContext(
  items: Record<string, any>[],
  target: Pick<CostItemNode, 'part_name' | 'group_path'>,
  nextPartName: string,
  nextGroupName: string,
): { items: Record<string, any>[]; updatedCount: number } {
  const normalizedNextPartName = normalizeCostText(nextPartName).trim();
  const normalizedNextGroupName = normalizeCostText(nextGroupName).trim();
  const targetContext = getBomGroupContext(target);
  if (!normalizedNextPartName || targetContext.length === 0) {
    return { items, updatedCount: 0 };
  }

  // 没有独立末级分类时，主分组本身就是唯一的分组层级。
  const nextContext = [normalizedNextPartName, normalizedNextGroupName].filter(
    (segment, index, context) => Boolean(segment) && (index === 0 || segment !== context[index - 1]),
  );
  let updatedCount = 0;
  const updatedItems = items.map((item) => {
    const itemContext = getBomGroupContext(item);
    const isSameTargetPath = targetContext.every((segment, index) => itemContext[index] === segment);
    if (!isSameTargetPath) return item;

    // 只替换当前目标路径，保留其下方的子分组层级。
    const updatedContext = [...nextContext, ...itemContext.slice(targetContext.length)];
    const updatedPartName = updatedContext[0] || normalizedNextPartName;
    const updatedGroupPath = updatedContext;
    const currentPartName = normalizeCostText(item.part_name).trim();
    const currentGroupPath = normalizeCostTextList(item.group_path);
    const isUnchanged = currentPartName === updatedPartName
      && currentGroupPath.length === updatedGroupPath.length
      && currentGroupPath.every((segment, index) => segment === updatedGroupPath[index]);
    if (isUnchanged) return item;

    updatedCount += 1;
    return {
      ...item,
      part_name: updatedPartName,
      group_path: updatedGroupPath,
    };
  });

  return { items: updatedItems, updatedCount };
}

/**
 * 兼容旧调用：仅修改末级分组时复用完整路径更新逻辑。
 */
export function renameCostGroupLeaf(
  items: Record<string, any>[],
  target: Pick<CostItemNode, 'part_name' | 'group_path'>,
  nextGroupName: string,
): { items: Record<string, any>[]; updatedCount: number } {
  const normalizedNextName = normalizeCostText(nextGroupName).trim();
  const targetContext = getBomGroupContext(target);
  const targetLeafName = targetContext.slice(-1)[0] || '';
  if (!normalizedNextName || !targetLeafName || normalizedNextName === targetLeafName) {
    return { items, updatedCount: 0 };
  }

  const targetPartName = normalizeCostText(target.part_name).trim();
  // 历史数据没有 group_path 时，part_name 就是唯一的分组层级。
  if (normalizeCostTextList(target.group_path).length === 0) {
    return updateCostGroupContext(items, target, normalizedNextName, '');
  }
  return updateCostGroupContext(items, target, targetPartName, normalizedNextName);
}

/**
 * 为原本没有表内分组的节点设置主分组和末级分组，并同步其整棵 BOM 子树。
 */
export function assignCostGroupContext(
  items: Record<string, any>[],
  targetIndex: number,
  partName: string,
  groupName: string,
): { items: Record<string, any>[]; updatedCount: number } {
  return assignCostGroupContextToNodes(items, [targetIndex], partName, groupName);
}

/**
 * 批量为多个节点设置表内分组；父子节点重复选择时只计算一次其合并后的子树。
 */
export function assignCostGroupContextToNodes(
  items: Record<string, any>[],
  targetIndices: number[],
  partName: string,
  groupName: string,
): { items: Record<string, any>[]; updatedCount: number } {
  const normalizedPartName = normalizeCostText(partName).trim();
  const normalizedGroupName = normalizeCostText(groupName).trim();
  if (!normalizedPartName || items.length === 0) {
    return { items, updatedCount: 0 };
  }

  // 没有独立末级分类时，主分组本身就是唯一的分组层级。
  const effectiveGroupName = normalizedGroupName || normalizedPartName;
  const groupPath = [normalizedPartName, effectiveGroupName].filter(
    (segment, index, path) => index === 0 || segment !== path[index - 1],
  );
  const selectedIndices = new Set<number>();
  targetIndices.forEach((targetIndex) => {
    getCostSubtreeIndices(items, targetIndex).forEach((index) => selectedIndices.add(index));
  });
  if (selectedIndices.size === 0) return { items, updatedCount: 0 };

  const updatedItems = items.map((item, index) => {
    if (!selectedIndices.has(index)) return item;
    return {
      ...item,
      part_name: normalizedPartName,
      group_path: [...groupPath],
      grouping_mode: 'internal',
    };
  });

  return { items: updatedItems, updatedCount: selectedIndices.size };
}

/** 只接受后端约定的分组模式，历史数据或异常值按未标记处理。 */
export function normalizeCostGroupingMode(value: unknown): CostGroupingMode | null {
  const mode = normalizeCostText(value).trim();
  return mode === 'external' || mode === 'internal' || mode === 'none' ? mode : null;
}

/** 从单条记录读取主分组模式；旧数据没有模式时按字段形态兼容推断。 */
export function inferCostItemGroupingMode(
  item: Pick<CostItemNode, 'grouping_mode' | 'part_name' | 'group_path' | 'section_name'>,
): CostGroupingMode {
  const explicitMode = normalizeCostGroupingMode(item.grouping_mode);
  if (explicitMode) return explicitMode;
  if (normalizeSectionName(item.section_name)) return 'external';
  if (hasBomGroupContext(item)) return 'internal';
  return 'none';
}

/** 汇总当前清单的模式，混合来源表格时不再生成并行的全局分组控件。 */
export function resolveCostGroupingDisplayMode(items: unknown[]): CostGroupingDisplayMode {
  const modes = new Set<CostGroupingMode>();
  const visit = (nodes: unknown[]): void => {
    nodes.forEach((value) => {
      if (!value || typeof value !== 'object') return;
      const item = value as CostItemNode;
      modes.add(inferCostItemGroupingMode(item));
      if (Array.isArray(item.children)) visit(item.children);
    });
  };
  visit(items);
  modes.delete('none');
  if (modes.size === 0) return 'none';
  if (modes.size === 1) return Array.from(modes)[0];
  return 'mixed';
}

/**
 * 清理成本明细中的历史异常值，统一前端渲染和请求边界的数据类型，并保留基线初始值。
 */
export function normalizeCostItem(item: unknown): Record<string, any> {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return {};

  const normalized = { ...(item as Record<string, unknown>) } as Record<string, any>;
  if (!normalized.name && normalized.item_name) {
    normalized.name = normalized.item_name;
  }
  // 工程元数据与成本结果使用不同字段名，进入 BOM 表前统一为成本表字段。
  if (normalized.spec_requirement === undefined && normalized.specifications !== undefined) {
    normalized.spec_requirement = normalized.specifications;
  }
  if (normalized.qty === undefined && normalized.quantity !== undefined) {
    normalized.qty = normalized.quantity;
  }
  if (normalized.per_set_qty === undefined && normalized.per_set_quantity !== undefined) {
    normalized.per_set_qty = normalized.per_set_quantity;
  }
  const textFields = [
    'item_code', 'name', 'spec_requirement', 'unit', 'matched_name',
    'matched_brand', 'matched_model', 'matched_manufacturer',
    'brand_requirements', 'match_quality', 'warning', 'comparison_note',
    'remark', 'parent_item', 'root_item', 'section_name', 'part_name', 'brand', 'model',
    'manufacturer', 'pricing_mode', 'raw_brand', 'raw_model', 'raw_manufacturer',
    'raw_spec', 'raw_unit', 'raw_name', 'raw_match_quality', 'grouping_mode'
  ];
  textFields.forEach((field) => {
    if (field in normalized && normalized[field] !== null && normalized[field] !== undefined) {
      normalized[field] = normalizeCostText(normalized[field]);
    }
  });
  normalized.key_parameters = normalizeCostTextList(normalized.key_parameters);
  // 表内 BOQ 分组是分类路径，不参与 BOM 父子树计算，但要保留供页面展示。
  normalized.group_path = normalizeCostTextList(normalized.group_path);

  // 初始化基线快照（如果尚未记录）
  if (normalized.raw_ref_price === undefined || normalized.raw_ref_price === null) {
    normalized.raw_ref_price = normalized.ref_price !== undefined && normalized.ref_price !== null ? Number(normalized.ref_price) : 0;
  }
  if (normalized.raw_name === undefined) {
    normalized.raw_name = normalized.name || '';
  }
  if (normalized.raw_brand === undefined) {
    normalized.raw_brand = normalized.brand || normalized.matched_brand || '';
  }
  if (normalized.raw_model === undefined) {
    normalized.raw_model = normalized.model || normalized.matched_model || '';
  }
  if (normalized.raw_manufacturer === undefined) {
    normalized.raw_manufacturer = normalized.manufacturer || normalized.matched_manufacturer || '';
  }
  if (normalized.raw_spec === undefined) {
    normalized.raw_spec = normalized.spec_requirement || '';
  }
  if (normalized.raw_qty === undefined) {
    normalized.raw_qty = normalized.qty !== undefined && normalized.qty !== null ? Number(normalized.qty) : 1;
  }
  if (normalized.raw_unit === undefined) {
    normalized.raw_unit = normalized.unit || '';
  }
  if (normalized.raw_match_quality === undefined) {
    normalized.raw_match_quality = normalized.match_quality || '';
  }

  return normalized;
}

/** 为手工新增节点生成稳定且不依赖名称的客户端 ID。 */
export function createCostNodeId(prefix = 'custom'): string {
  const randomUuid = globalThis.crypto?.randomUUID;
  if (typeof randomUuid === 'function') {
    return `${prefix}_${randomUuid.call(globalThis.crypto)}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

/** 获取节点 ID；历史数据没有 ID 时由原始位置和名称生成兼容标识。 */
function getCostNodeId(item: Record<string, any>, index: number): string {
  const explicitId = normalizeCostText(item.node_id || item.id).trim();
  if (explicitId) return explicitId;

  const itemCode = normalizeCostText(item.item_code).trim();
  const name = normalizeCostText(item.name || item.item_name).trim();
  const identity = itemCode || name || 'item';
  return `legacy_${index}_${identity.replace(/[^\w\u4e00-\u9fff-]+/g, '_')}`;
}

/** 展平树节点，供父节点选择器和节点关系操作复用。 */
export function flattenCostTreeNodes(nodes: CostItemNode[]): CostItemNode[] {
  const result: CostItemNode[] = [];
  const visit = (currentNodes: CostItemNode[]): void => {
    currentNodes.forEach((node) => {
      result.push(node);
      if (Array.isArray(node.children) && node.children.length > 0) {
        visit(node.children);
      }
    });
  };
  visit(nodes);
  return result;
}

/** 返回一个扁平 BOM 数组中指定节点及其全部后代的索引。 */
export function getCostSubtreeIndices(items: Record<string, any>[], targetIndex: number): number[] {
  if (targetIndex < 0 || targetIndex >= items.length) return [];

  const target = items[targetIndex];
  const targetId = normalizeCostText(target.node_id).trim();
  const targetName = normalizeCostText(target.name || target.item_name).trim();
  const nodeById = new Map<string, Record<string, any>>();
  items.forEach((item) => {
    const nodeId = normalizeCostText(item.node_id).trim();
    if (nodeId) nodeById.set(nodeId, item);
  });

  const isDescendant = (item: Record<string, any>): boolean => {
    const visited = new Set<string>();
    let parentId = normalizeCostText(item.parent_node_id).trim();
    while (parentId && !visited.has(parentId)) {
      if (parentId === targetId) return true;
      visited.add(parentId);
      const parent = nodeById.get(parentId);
      parentId = parent ? normalizeCostText(parent.parent_node_id).trim() : '';
    }

    // 历史数据兼容：没有可用节点 ID 时至少支持直接父项删除。
    return Boolean(targetName && normalizeCostText(item.parent_item).trim() === targetName);
  };

  return items.reduce<number[]>((indices, item, index) => {
    if (index === targetIndex || isDescendant(item)) indices.push(index);
    return indices;
  }, []);
}

/** 返回节点整棵子树在扁平数组中的结束位置，用于保持前序树顺序插入新节点。 */
export function getCostSubtreeEndIndex(items: Record<string, any>[], targetIndex: number): number {
  const subtreeIndices = getCostSubtreeIndices(items, targetIndex);
  return subtreeIndices.length > 0 ? Math.max(...subtreeIndices) : targetIndex;
}

/**
 * 获取“重置所有子项”真正需要处理的后代索引，确保目标节点永远不会被误判为自己的子项。
 * 稳定父节点 ID 优先，历史数据再使用父项名称与顶层根项兼容回溯。
 */
export function getCostResetChildIndices(items: Record<string, any>[], targetIndex: number): number[] {
  if (targetIndex < 0 || targetIndex >= items.length) return [];

  const target = items[targetIndex];
  const targetId = normalizeCostText(target.node_id).trim();
  const targetName = normalizeCostText(target.name || target.item_name).trim();
  const targetParentId = normalizeCostText(target.parent_node_id).trim();
  const targetParentName = normalizeCostText(target.parent_item).trim();
  const targetRootName = normalizeCostText(target.root_item).trim();
  const childIndices = new Set(
    getCostSubtreeIndices(items, targetIndex).filter((index) => index !== targetIndex),
  );

  // 历史清单可能没有完整的 parent_node_id；按已确认的子节点逐层补齐名称链路。
  let changed = true;
  while (changed) {
    changed = false;
    const knownParentIds = new Set<string>([targetId]);
    const knownParentNames = new Set<string>([targetName]);

    childIndices.forEach((index) => {
      const node = items[index];
      const nodeId = normalizeCostText(node.node_id).trim();
      const nodeName = normalizeCostText(node.name || node.item_name).trim();
      if (nodeId) knownParentIds.add(nodeId);
      if (nodeName) knownParentNames.add(nodeName);
    });

    items.forEach((item, index) => {
      if (index === targetIndex || childIndices.has(index)) return;

      const parentId = normalizeCostText(item.parent_node_id).trim();
      const parentName = normalizeCostText(item.parent_item).trim();
      const matchedById = Boolean(parentId && knownParentIds.has(parentId));
      const matchedByName = Boolean(parentName && knownParentNames.has(parentName));
      if (matchedById || matchedByName) {
        childIndices.add(index);
        changed = true;
      }
    });
  }

  // 对顶层历史根项，补齐仅保留 root_item、没有父项字段的旧子节点；目标节点本身已明确排除。
  const isTopLevelTarget = !targetParentId && !targetParentName;
  if (isTopLevelTarget && targetRootName && targetRootName === targetName) {
    items.forEach((item, index) => {
      if (index === targetIndex) return;
      if (normalizeCostText(item.root_item).trim() === targetRootName) {
        childIndices.add(index);
      }
    });
  }

  return Array.from(childIndices).sort((left, right) => left - right);
}

/**
 * 重置成套设备的原始子项，同时保留手动新增项及其完整编辑状态。
 * 返回统计信息，供界面提示和操作日志使用。
 */
export function resetCostChildrenPreservingCustomItems(
  items: Record<string, any>[],
  targetIndex: number,
): {
  items: Record<string, any>[];
  restoredChildCount: number;
  preservedCustomCount: number;
} {
  if (targetIndex < 0 || targetIndex >= items.length) {
    return {
      items,
      restoredChildCount: 0,
      preservedCustomCount: 0,
    };
  }

  const descendantIndices = new Set(getCostResetChildIndices(items, targetIndex));
  let restoredChildCount = 0;
  let preservedCustomCount = 0;

  const updatedItems = items.map((item, index) => {
    if (descendantIndices.has(index)) {
      // 手动新增项不是原始提取结果，重置时保留其价格、层级和修改状态。
      if (item.is_custom_added) {
        preservedCustomCount += 1;
        return { ...item };
      }

      const restoredItem = { ...item };
      // 原始子项恢复到解析完成时的基线字段。
      restoredItem.name = restoredItem.raw_name || restoredItem.name;
      restoredItem.matched_brand = restoredItem.raw_brand || '';
      restoredItem.brand = restoredItem.raw_brand || '';
      restoredItem.matched_model = restoredItem.raw_model || '';
      restoredItem.model = restoredItem.raw_model || '';
      restoredItem.matched_manufacturer = restoredItem.raw_manufacturer || '';
      restoredItem.manufacturer = restoredItem.raw_manufacturer || '';
      restoredItem.spec_requirement = restoredItem.raw_spec || restoredItem.spec_requirement;
      restoredItem.qty = restoredItem.raw_qty !== undefined ? restoredItem.raw_qty : restoredItem.qty;
      restoredItem.unit = restoredItem.raw_unit || restoredItem.unit;
      restoredItem.ref_price = restoredItem.raw_ref_price !== undefined ? restoredItem.raw_ref_price : 0;
      restoredItem.subtotal = Number(((restoredItem.qty || 1) * restoredItem.ref_price).toFixed(2));
      restoredItem.match_quality = restoredItem.raw_match_quality
        || (restoredItem.ref_price > 0 ? '精准匹配' : '未匹配');
      restoredItem.is_child_modified = false;
      restoredChildCount += 1;
      return restoredItem;
    }

    if (index === targetIndex) {
      // 子项恢复后，父项回到子项汇总模式并重新允许直接编辑。
      return {
        ...item,
        is_parent_modified: false,
        pricing_mode: 'children',
      };
    }

    return item;
  });

  return {
    items: updatedItems,
    restoredChildCount,
    preservedCustomCount,
  };
}

/** 判断目标节点是否位于指定节点的后代链路中。 */
export function isCostDescendant(
  items: Record<string, any>[],
  targetNodeId: string,
  ancestorNodeId: string,
): boolean {
  if (!targetNodeId || !ancestorNodeId || targetNodeId === ancestorNodeId) return false;

  const nodeById = new Map<string, Record<string, any>>();
  items.forEach((item) => {
    const nodeId = normalizeCostText(item.node_id).trim();
    if (nodeId) nodeById.set(nodeId, item);
  });

  const visited = new Set<string>();
  let currentParentId = normalizeCostText(nodeById.get(targetNodeId)?.parent_node_id).trim();
  while (currentParentId && !visited.has(currentParentId)) {
    if (currentParentId === ancestorNodeId) return true;
    visited.add(currentParentId);
    currentParentId = normalizeCostText(nodeById.get(currentParentId)?.parent_node_id).trim();
  }
  return false;
}

/** 拖拽节点的落点类型：成为子项，或插入锚点节点前/后。 */
export type CostMovePlacement = 'inside' | 'before' | 'after';

/** 根据鼠标在目标行中的垂直位置判断拖拽落点，用于区分同级排序和父子挂载。 */
export function resolveCostDropPlacement(
  clientY: number,
  rowTop: number,
  rowHeight: number,
): CostMovePlacement {
  if (!Number.isFinite(clientY) || !Number.isFinite(rowTop) || !Number.isFinite(rowHeight) || rowHeight <= 0) {
    return 'inside';
  }

  const relativeY = (clientY - rowTop) / rowHeight;
  if (relativeY <= 0.28) return 'before';
  if (relativeY >= 0.72) return 'after';
  return 'inside';
}

/** 释放拖拽时优先用当前位置重新判定落点，几何信息异常时回退到最近一次拖拽提示。 */
export function resolveCostDropPlacementAtDrop(
  clientY: number,
  rowTop: number,
  rowHeight: number,
  fallbackPlacement: CostMovePlacement | null,
): CostMovePlacement | null {
  if (Number.isFinite(clientY) && Number.isFinite(rowTop) && Number.isFinite(rowHeight) && rowHeight > 0) {
    return resolveCostDropPlacement(clientY, rowTop, rowHeight);
  }
  return fallbackPlacement;
}

/**
 * 返回拖拽操作前的展开键，避免节点挂载后表格依据新树结构自动展开目标父项。
 * 未处于拖拽流程时保留当前状态，供非拖拽移动操作继续使用。
 */
export function restoreCostExpandedKeysAfterDrag(
  currentKeys: readonly React.Key[],
  dragStartKeys: readonly React.Key[] | null,
): readonly React.Key[] {
  return dragStartKeys ? [...dragStartKeys] : [...currentKeys];
}

/** 表内 BOQ 分组上下文；父子关系调整时由目标父项提供。 */
interface CostGroupingContext {
  part_name: string | null;
  group_path: string[];
  grouping_mode: CostGroupingMode | null;
}

/** 从节点提取可复用的表内分组上下文，避免移动时引用可变树节点。 */
function getCostGroupingContext(node: Record<string, any> | null): CostGroupingContext | null {
  if (!node) return null;
  return {
    part_name: normalizeCostText(node.part_name).trim() || null,
    group_path: normalizeCostTextList(node.group_path),
    grouping_mode: normalizeCostGroupingMode(node.grouping_mode),
  };
}

/** 解析新增节点应使用的表内分组，优先采用父项或同级锚点，保证筛选视图下新增项立即可见。 */
export function resolveCostGroupingForNewNode(
  targetParent: Record<string, any> | null,
  anchorNode: Record<string, any> | null,
  selectedPart: string,
  displayMode: CostGroupingDisplayMode,
): CostGroupingContext {
  const context = getCostGroupingContext(targetParent || anchorNode);
  const fallbackPartName = selectedPart !== 'ALL' ? normalizeCostText(selectedPart).trim() || null : null;
  return {
    part_name: context?.part_name || fallbackPartName,
    group_path: context?.group_path || (fallbackPartName ? [fallbackPartName] : []),
    grouping_mode: context?.grouping_mode
      || (displayMode === 'mixed' ? 'none' : displayMode),
  };
}

/** 判断父项下拉选项是否匹配搜索词，支持名称、层级标签等展示文本。 */
export function filterCostParentOption(
  input: string,
  option: { label?: unknown } | null | undefined,
): boolean {
  const keyword = normalizeCostText(input).trim().toLowerCase();
  if (!keyword) return true;
  return normalizeCostText(option?.label).toLowerCase().includes(keyword);
}

/** 将目标父项的表内分组同步到移动子树的每个节点。 */
function applyCostGroupingContext(
  node: Record<string, any>,
  context: CostGroupingContext | null,
): void {
  if (!context) return;
  node.part_name = context.part_name;
  node.group_path = [...context.group_path];
  node.grouping_mode = context.grouping_mode;
}

/** 将一棵扁平 BOM 子树移动到指定落点，并同步修正层级上下文。 */
function moveCostSubtreeToPlacement(
  items: Record<string, any>[],
  sourceNodeId: string,
  targetParentNodeId: string | null,
  anchorNodeId: string | null,
  placement: CostMovePlacement,
): { items: Record<string, any>[]; moved: boolean; reason?: 'source_not_found' | 'target_not_found' | 'descendant_target' } {
  const sourceIndex = items.findIndex((item) => normalizeCostText(item.node_id).trim() === sourceNodeId);
  if (sourceIndex < 0) return { items, moved: false, reason: 'source_not_found' };

  const anchorIndex = anchorNodeId
    ? items.findIndex((item) => normalizeCostText(item.node_id).trim() === anchorNodeId)
    : -1;
  if (anchorNodeId && anchorIndex < 0) {
    return { items, moved: false, reason: 'target_not_found' };
  }
  if (anchorNodeId === sourceNodeId || isCostDescendant(items, anchorNodeId || '', sourceNodeId)) {
    return { items, moved: false, reason: 'descendant_target' };
  }

  const subtreeIndices = new Set(getCostSubtreeIndices(items, sourceIndex));
  const movingItems = items
    .filter((_, index) => subtreeIndices.has(index))
    .map((item) => ({ ...item }));
  const remainingItems = items.filter((_, index) => !subtreeIndices.has(index));
  const parentNode = targetParentNodeId
    ? remainingItems.find((item) => normalizeCostText(item.node_id).trim() === targetParentNodeId) || null
    : null;
  const anchorNode = anchorNodeId
    ? items.find((item) => normalizeCostText(item.node_id).trim() === anchorNodeId) || null
    : null;
  const movingRoot = movingItems.find((item) => normalizeCostText(item.node_id).trim() === sourceNodeId);
  if (!movingRoot) return { items, moved: false, reason: 'source_not_found' };

  // 只有实际改变父项归属时才联动表内分组；单纯调整同级前后顺序不改变原分组。
  const sourceParentNodeId = normalizeCostText(movingRoot.parent_node_id).trim() || null;
  const targetStructureParentId = normalizeCostText(targetParentNodeId).trim() || null;
  const parentChanged = sourceParentNodeId !== targetStructureParentId;
  // 脱离到顶层时没有新的父项，使用原父项作为同级分组锚点，保持分组语义连续。
  const groupingContextOwner = parentChanged
    ? (parentNode || (placement !== 'inside' ? anchorNode : null))
    : null;
  const groupingContext = getCostGroupingContext(groupingContextOwner);

  const rewriteContext = (
    node: Record<string, any>,
    parent: Record<string, any> | null,
    level: number,
  ): void => {
    node.parent_node_id = parent ? normalizeCostText(parent.node_id).trim() : null;
    node.parent_item = parent ? normalizeCostText(parent.name).trim() : null;
    node.tree_level = level;
    node.root_item = parent
      ? (normalizeCostText(parent.root_item).trim() || normalizeCostText(parent.name).trim())
      : normalizeCostText(node.name).trim();
    applyCostGroupingContext(node, groupingContext);

    const nodeId = normalizeCostText(node.node_id).trim();
    movingItems
      .filter((candidate) => normalizeCostText(candidate.parent_node_id).trim() === nodeId)
      .forEach((child) => rewriteContext(child, node, level + 1));
  };

  rewriteContext(movingRoot, parentNode, parentNode ? (Number(parentNode.tree_level) || 1) + 1 : 1);

  const remainingAnchorIndex = anchorNodeId
    ? remainingItems.findIndex((item) => normalizeCostText(item.node_id).trim() === anchorNodeId)
    : -1;
  const insertIndex = placement === 'inside'
    ? (parentNode
      ? getCostSubtreeEndIndex(remainingItems, remainingItems.findIndex((item) => item === parentNode)) + 1
      : remainingItems.length)
    : (placement === 'before'
      ? remainingAnchorIndex
      : getCostSubtreeEndIndex(remainingItems, remainingAnchorIndex) + 1);
  const reorderedItems = [...remainingItems];
  reorderedItems.splice(insertIndex, 0, ...movingItems);

  return {
    items: reorderedItems.map((item, index) => ({ ...item, sort_order: index })),
    moved: true,
  };
}

/** 将一棵扁平 BOM 子树移动到新的父节点下。 */
export function moveCostSubtree(
  items: Record<string, any>[],
  sourceNodeId: string,
  targetParentNodeId: string | null,
): { items: Record<string, any>[]; moved: boolean; reason?: 'source_not_found' | 'target_not_found' | 'descendant_target' } {
  return moveCostSubtreeToPlacement(items, sourceNodeId, targetParentNodeId, targetParentNodeId, 'inside');
}

/** 将一棵扁平 BOM 子树移动到目标节点的同级前/后位置。 */
export function moveCostSubtreeAsSibling(
  items: Record<string, any>[],
  sourceNodeId: string,
  anchorNodeId: string,
  placement: 'before' | 'after',
): { items: Record<string, any>[]; moved: boolean; reason?: 'source_not_found' | 'target_not_found' | 'descendant_target' } {
  const anchor = items.find((item) => normalizeCostText(item.node_id).trim() === anchorNodeId);
  if (!anchor) return { items, moved: false, reason: 'target_not_found' };
  const targetParentNodeId = normalizeCostText(anchor.parent_node_id).trim() || null;
  return moveCostSubtreeToPlacement(items, sourceNodeId, targetParentNodeId, anchorNodeId, placement);
}

/** 解析脱离节点时使用的当前父项 ID，优先采用树构建阶段校准后的关系。 */
export function resolveCostDetachParentNodeId(
  record: Record<string, any>,
  sourceItem: Record<string, any> | null | undefined,
): string {
  return normalizeCostText(record.parent_node_id || sourceItem?.parent_node_id).trim();
}

/**
 * 解析脱离操作的父项锚点；父项 ID 不在原始扁平清单时按当前父项名称回退查找。
 * 兼容树构建阶段依据 tree_level 校准关系、但旧数据未同步回写 parent_node_id 的场景。
 */
export function resolveCostDetachAnchorNodeId(
  items: Record<string, any>[],
  record: Record<string, any>,
  sourceItem: Record<string, any> | null | undefined,
): string {
  const preferredParentId = resolveCostDetachParentNodeId(record, sourceItem);
  const sourceNodeId = normalizeCostText(record.node_id || sourceItem?.node_id).trim();
  const preferredParentExists = items.some(
    (item) => normalizeCostText(item.node_id).trim() === preferredParentId,
  );
  if (preferredParentId && preferredParentExists) return preferredParentId;

  const parentName = normalizeCostText(record.parent_item || sourceItem?.parent_item).trim();
  if (!parentName) return preferredParentId;

  const rootName = normalizeCostText(record.root_item || sourceItem?.root_item).trim();
  const sectionName = normalizeCostText(record.section_name || sourceItem?.section_name).trim();
  const fallbackParent = items.find((item) => {
    const itemNodeId = normalizeCostText(item.node_id).trim();
    const itemName = normalizeCostText(item.name || item.item_name).trim();
    const itemRootName = normalizeCostText(item.root_item).trim();
    const itemSectionName = normalizeCostText(item.section_name).trim();
    const sameRoot = !rootName || !itemRootName || rootName === itemRootName;
    const sameSection = !sectionName || !itemSectionName || sectionName === itemSectionName;
    return itemNodeId !== sourceNodeId && itemName === parentName && sameRoot && sameSection;
  });

  return normalizeCostText(fallbackParent?.node_id).trim() || preferredParentId;
}

/**
 * 归一化成本清单，过滤无法作为表格行使用的异常值并记录诊断信息。
 */
export function normalizeCostItems(value: unknown): any[] {
  if (!Array.isArray(value)) {
    if (value !== null && value !== undefined) {
      console.warn('成本分析 items 不是数组，已按空清单处理。');
    }
    return [];
  }
  const normalizedItems = value
    .map(normalizeCostItem)
    .filter((item) => Boolean(item.name));
  const usedIds = new Set<string>();

  // 首先补齐节点 ID，保证后续即使同名也能准确挂载到指定父节点。
  normalizedItems.forEach((item, index) => {
    let nodeId = getCostNodeId(item, index);
    let suffix = 1;
    while (usedIds.has(nodeId)) {
      nodeId = `${nodeId}_${suffix}`;
      suffix += 1;
    }
    usedIds.add(nodeId);
    item.node_id = nodeId;
    item.sort_order = item.sort_order ?? index;
  });

  // 兼容旧数据：仅有 parent_item 时，优先按原有就近规则补出 parent_node_id；
  // 若父项因分块合并排在子项之后，则在同一层级作用域内执行后向查找。
  normalizedItems.forEach((item, index) => {
    if (normalizeCostText(item.parent_node_id).trim()) return;
    const parentName = normalizeCostText(item.parent_item).trim();
    if (!parentName) {
      item.parent_node_id = null;
      return;
    }

    const currentRoot = normalizeCostText(item.root_item).trim();
    const currentSection = normalizeCostText(item.section_name).trim();
    const currentSourceTable = item.source_table_index;
    const isSameScope = (candidate: Record<string, any>): boolean => {
      const candidateRoot = normalizeCostText(candidate.root_item).trim();
      const candidateSection = normalizeCostText(candidate.section_name).trim();
      const candidateSourceTable = candidate.source_table_index;
      const sameRoot = !currentRoot || !candidateRoot || currentRoot === candidateRoot;
      const sameSection = !currentSection || !candidateSection || currentSection === candidateSection;
      const sameSourceTable = currentSourceTable === null
        || currentSourceTable === undefined
        || candidateSourceTable === null
        || candidateSourceTable === undefined
        || currentSourceTable === candidateSourceTable;
      return sameRoot && sameSection && sameSourceTable;
    };
    const isParentCandidate = (candidate: Record<string, any>): boolean => (
      candidate !== item
      && normalizeCostText(candidate.name).trim() === parentName
      && isSameScope(candidate)
    );
    const parent = normalizedItems
      .slice(0, index)
      .reverse()
      .find(isParentCandidate)
      || normalizedItems.slice(index + 1).find(isParentCandidate);
    item.parent_node_id = parent?.node_id || null;
  });

  return normalizedItems;
}

/** 提取用于判断“本地保存回写”与“外部刷新”的结构指纹，不包含价格等展示字段。 */
function getCostStructureFingerprint(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return JSON.stringify(value.map((rawItem, index) => {
    const item = normalizeCostItem(rawItem);
    return {
      node_id: normalizeCostText(item.node_id || item.id || item.item_code || `${item.name || 'item'}_${index}`),
      parent_node_id: normalizeCostText(item.parent_node_id),
      parent_item: normalizeCostText(item.parent_item),
      sort_order: item.sort_order ?? index,
      name: normalizeCostText(item.name),
    };
  }));
}

/**
 * 根据输入内容估算编辑框宽度，避免数量或单位较长时被输入框裁剪。
 */
export function getAdaptiveInputWidth(value: unknown, minWidth: number, charWidth: number): number {
  const text = normalizeCostText(value).trim();
  const safeMinWidth = Number.isFinite(minWidth) && minWidth > 0 ? minWidth : 80;
  const safeCharWidth = Number.isFinite(charWidth) && charWidth > 0 ? charWidth : 10;
  if (!text) return safeMinWidth;

  return Math.max(safeMinWidth, Math.ceil(text.length * safeCharWidth + 24));
}

/**
 * 分部/工程大类规范化函数 (Section Normalization)
 * 忠实保留标书提取的原始 section_name，去除多余空白，杜绝任何硬编码与人为破坏性截断。
 */
export function normalizeSectionName(rawSec: unknown): string | null {
  const s = normalizeCostText(rawSec).trim();
  if (!s) return null;

  // 兼容历史清单标题中的包装文字，仅处理明确的“项目需求清单（分项）”结构。
  const wrappedTitle = s.match(/^(?:\d+[、.．]\s*)?项目需求清单\s*[（(]([^（）()]+)[）)]$/);
  return wrappedTitle?.[1]?.trim() || s;
}

export function CostTable({
  documentId,
  documentFilename,
  equipmentList = [],
  financial = {},
  costAnalysis = {},
  onReextract,
  onReextractEquipment,
  onCostUpdated,
  isRetrying = false,
  isExtractingEquipment = false,
  isEquipmentOnly = false
}: CostTableProps) {
  // 使用 Ant Design App 提供带主题上下文的消息实例，避免静态 message 告警。
  const { message } = AntdApp.useApp();
  const [items, setItems] = useState<any[]>(() => {
    const costItems = normalizeCostItems(costAnalysis?.items);
    return !isEquipmentOnly && costItems.length > 0 ? costItems : normalizeCostItems(equipmentList);
  });
  const [isAdding, setIsAdding] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [selectedSection, setSelectedSection] = useState<string>('ALL');
  const [selectedPart, setSelectedPart] = useState<string>('ALL');
  // 仅保存当前表格实例的列宽，不写入 BOM 数据；切换页面或重新加载后恢复紧凑默认值。
  const [columnWidths, setColumnWidths] = useState<Partial<Record<CostTableColumnKey, number>>>({});

  // 行行内编辑 State
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editBrand, setEditBrand] = useState('');
  const [editModel, setEditModel] = useState('');
  const [editManufacturer, setEditManufacturer] = useState('');
  const [editSpec, setEditSpec] = useState('');
  const [editRemark, setEditRemark] = useState('');
  const [editQty, setEditQty] = useState<number>(1);
  const [editUnit, setEditUnit] = useState('台');
  const [editPrice, setEditPrice] = useState<number>(0);

  // 表内 BOQ 分组重命名 State
  const [isGroupEditModalOpen, setIsGroupEditModalOpen] = useState(false);
  const [groupEditingRecord, setGroupEditingRecord] = useState<CostItemNode | null>(null);
  const [groupEditPartName, setGroupEditPartName] = useState('');
  const [groupEditName, setGroupEditName] = useState('');
  const [isGroupAssignModalOpen, setIsGroupAssignModalOpen] = useState(false);
  const [groupAssignRecord, setGroupAssignRecord] = useState<CostItemNode | null>(null);
  const [groupAssignPartName, setGroupAssignPartName] = useState('');
  const [groupAssignName, setGroupAssignName] = useState('');
  const [selectedNodeKeys, setSelectedNodeKeys] = useState<React.Key[]>([]);
  const [isBatchGroupAssignModalOpen, setIsBatchGroupAssignModalOpen] = useState(false);
  const [batchGroupPartName, setBatchGroupPartName] = useState('');
  const [batchGroupName, setBatchGroupName] = useState('');

  // 新增子项专用 Modal 弹窗 State
  const [isAddChildModalOpen, setIsAddChildModalOpen] = useState(false);
  const [targetParentNode, setTargetParentNode] = useState<CostItemNode | null>(null);
  const [addNodeMode, setAddNodeMode] = useState<'child' | 'sibling'>('child');
  const [addAnchorNode, setAddAnchorNode] = useState<CostItemNode | null>(null);
  const [childFormName, setChildFormName] = useState('');
  const [childFormBrand, setChildFormBrand] = useState('');
  const [childFormModel, setChildFormModel] = useState('');
  const [childFormManufacturer, setChildFormManufacturer] = useState('');
  const [childFormSpec, setChildFormSpec] = useState('');
  const [childFormQty, setChildFormQty] = useState<number>(1);
  const [childFormUnit, setChildFormUnit] = useState('项');
  const [childFormPrice, setChildFormPrice] = useState<number>(0);
  const [childFormPerSetQty, setChildFormPerSetQty] = useState<number>(1);
  const [childFormRemark, setChildFormRemark] = useState('');

  // 修改父项归属与拖拽移动 State
  const [isMoveParentModalOpen, setIsMoveParentModalOpen] = useState(false);
  const [movingNode, setMovingNode] = useState<CostItemNode | null>(null);
  const [moveTargetParentId, setMoveTargetParentId] = useState('');
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOverNodeId, setDragOverNodeId] = useState<string | null>(null);
  const [dragOverPlacement, setDragOverPlacement] = useState<CostMovePlacement | null>(null);
  // 记录拖拽开始时的展开状态，防止挂载后目标父项被表格组件自动展开。
  const dragStartExpandedRowKeysRef = React.useRef<readonly React.Key[] | null>(null);

  // 新增自定义费用分项表单 State（底部表单）
  const [newName, setNewName] = useState('');
  const [newBrand, setNewBrand] = useState('');
  const [newModel, setNewModel] = useState('');
  const [newManufacturer, setNewManufacturer] = useState('');
  const [newSpec, setNewSpec] = useState('');
  const [newRemark, setNewRemark] = useState('');
  const [newQty, setNewQty] = useState<number>(1);
  const [newUnit, setNewUnit] = useState('项');
  const [newPrice, setNewPrice] = useState<number>(0);
  const [newParentItem, setNewParentItem] = useState<string>('');
  const lastLocalItemsFingerprintRef = React.useRef('');
  const tableWrapperRef = React.useRef<HTMLDivElement | null>(null);
  const tableHorizontalScrollbarRef = React.useRef<HTMLDivElement | null>(null);
  const isBusy = isRetrying || isExtractingEquipment;
  const editQtyInputWidth = getAdaptiveInputWidth(editQty, COST_TABLE_QTY_INPUT_MIN_WIDTH, 9);
  const editUnitInputWidth = getAdaptiveInputWidth(editUnit, COST_TABLE_UNIT_INPUT_MIN_WIDTH, 14);
  // 编辑态只为数量、单位输入框及单元格内边距预留空间，单位为单字时不再撑宽整列。
  const quantityColumnWidth = Math.max(
    COST_TABLE_QTY_COLUMN_MIN_WIDTH,
    editQtyInputWidth
      + editUnitInputWidth
      + COST_TABLE_QTY_INPUT_GAP
      + COST_TABLE_QTY_CELL_HORIZONTAL_PADDING,
  );

  // 成本模式优先展示测算结果；仅清单模式必须直接展示最新工程提取树。
  useEffect(() => {
    const costItems = normalizeCostItems(costAnalysis?.items);
    const nextItems = !isEquipmentOnly && costItems.length > 0 ? costItems : normalizeCostItems(equipmentList);
    const incomingFingerprint = getCostStructureFingerprint(nextItems);
    const isLocalSaveEcho = Boolean(
      incomingFingerprint && incomingFingerprint === lastLocalItemsFingerprintRef.current,
    );
    setItems(nextItems);

    // 外部刷新时回到折叠状态；保存接口回写当前编辑结果时保留用户正在查看的展开状态。
    if (isLocalSaveEcho) {
      lastLocalItemsFingerprintRef.current = '';
    } else {
      setExpandedRowKeys([]);
    }
  }, [costAnalysis, equipmentList, isEquipmentOnly]);

  // 页面按记录语义展示分组；用户补充表内分组后，混合模式下仍保留两类独立筛选。
  const groupingDisplayMode = React.useMemo(
    () => resolveCostGroupingDisplayMode(items),
    [items],
  );

  // 提取数据中实际包含的所有分标段/分区域名称（忠实保持标书原始出现的自然先后顺序）
  const availableSections = React.useMemo(() => {
    const list: string[] = [];
    const set = new Set<string>();
    let hasUnassigned = false;

    const collectSections = (nodes: any[]): void => {
      nodes.forEach(it => {
        const normalized = normalizeSectionName(it?.section_name);
        if (normalized) {
          if (!set.has(normalized)) {
            set.add(normalized);
            list.push(normalized);
          }
        } else {
          hasUnassigned = true;
        }
        if (Array.isArray(it?.children) && it.children.length > 0) {
          collectSections(it.children);
        }
      });
    };
    if (groupingDisplayMode !== 'external' && groupingDisplayMode !== 'mixed') return list;
    collectSections(items || []);
    
    // 若存在其他明确区域，同时又存在未指定区域的独立项，追加通用分项分类
    if (set.size > 0 && hasUnassigned) {
      list.push('通用及其他分项');
    }

    // 忠实保留标书章节原本的自然出现先后顺序 (Natural Order)
    return list;
  }, [items, equipmentList, groupingDisplayMode]);

  // 当 items 或 availableSections 变更时，自动校准悬空的 selectedSection 状态
  useEffect(() => {
    if (
      selectedSection !== 'ALL'
      && (!['external', 'mixed'].includes(groupingDisplayMode) || !availableSections.includes(selectedSection))
    ) {
      setSelectedSection('ALL');
    }
  }, [availableSections, groupingDisplayMode, selectedSection]);

  // 从接口返回的表内 BOQ 分类动态生成筛选项，不维护任何固定项目名称映射。
  const availableParts = React.useMemo(() => {
    const parts: string[] = [];
    const seen = new Set<string>();
    const collectParts = (nodes: any[]): void => {
      nodes.forEach((item) => {
        const partName = normalizeCostText(item?.part_name).trim();
        if (partName && !seen.has(partName)) {
          seen.add(partName);
          parts.push(partName);
        }
        if (Array.isArray(item?.children) && item.children.length > 0) {
          collectParts(item.children);
        }
      });
    };
    if (groupingDisplayMode !== 'internal' && groupingDisplayMode !== 'mixed') return parts;
    collectParts(items || []);
    return parts;
  }, [items, groupingDisplayMode]);

  // 当重新提取后原分组已不存在时，自动回到全部表内分组。
  useEffect(() => {
    if (
      selectedPart !== 'ALL'
      && (!['internal', 'mixed'].includes(groupingDisplayMode) || !availableParts.includes(selectedPart))
    ) {
      setSelectedPart('ALL');
    }
  }, [availableParts, groupingDisplayMode, selectedPart]);

  // 将 items 数据递归组装为 Ant Design 标准的 Tree Data 多级嵌套树形结构，并自底向上递归汇总母项价格
  const { treeData, allParentKeys, parentCount, childCountTotal } = React.useMemo(() => {
    if (!items || items.length === 0) {
      return { treeData: [], allParentKeys: [], parentCount: 0, childCountTotal: 0 };
    }

    const hasOtherExplicitSections = availableSections.length > 0;

    // 1. 生成扁平节点（包含标准化归一后的 section_name 与实时编辑态联动）
    const allNodes: CostItemNode[] = items.map((item, idx) => {
      const isCurrentlyEditing = editingIndex === idx;
      const nodeName = String(
        isCurrentlyEditing
          ? (editName || item.item_name || item.name || '')
          : (item.item_name || item.name || '')
      ).trim();
      // 行键必须绑定稳定节点 ID，不能使用数组下标，否则移动/脱离后 React 会错认节点。
      const nodeKey = item.node_id
        ? `node_${item.node_id}`
        : item.id
          ? `item_${item.id}`
          : `node_${idx}_${nodeName}`;
      
      const rawQty = isCurrentlyEditing 
        ? editQty 
        : (item.qty !== null && item.qty !== undefined ? item.qty : (item.quantity !== null && item.quantity !== undefined ? item.quantity : null));
      const rawPrice = isCurrentlyEditing 
        ? editPrice 
        : (item.ref_price !== null && item.ref_price !== undefined ? item.ref_price : 0);
      const rawUnit = isCurrentlyEditing ? editUnit : (item.unit ? String(item.unit).trim() : null);

      let normSection = normalizeSectionName(item.section_name);
      if (!normSection && hasOtherExplicitSections) {
        normSection = '通用及其他分项';
      }
      
      const safeQty = rawQty !== null && Number(rawQty) > 0 ? Number(rawQty) : 1;
      const safePrice = Number(rawPrice) >= 0 ? Number(rawPrice) : 0;

      const node: CostItemNode = {
        ...item,
        key: nodeKey,
        originalIndex: idx,
        item_code: item.item_code || null,
        name: nodeName,
        brand: isCurrentlyEditing ? editBrand : (item.brand || item.matched_brand || ''),
        model: isCurrentlyEditing ? editModel : (item.model || item.matched_model || ''),
        manufacturer: isCurrentlyEditing ? editManufacturer : (item.manufacturer || item.matched_manufacturer || ''),
        matched_brand: isCurrentlyEditing ? editBrand : (item.matched_brand || item.brand || ''),
        matched_model: isCurrentlyEditing ? editModel : (item.matched_model || item.model || ''),
        matched_manufacturer: isCurrentlyEditing ? editManufacturer : (item.matched_manufacturer || item.manufacturer || ''),
        spec_requirement: isCurrentlyEditing ? editSpec : (item.spec_requirement || ''),
        parent_item: item.parent_item ? String(item.parent_item).trim() : null,
        root_item: item.root_item ? String(item.root_item).trim() : null,
        tree_level: item.tree_level ? Number(item.tree_level) : 1,
        qty: rawQty !== null && rawQty !== undefined ? Number(rawQty) : null,
        unit: rawUnit || null,
        ref_price: safePrice,
        subtotal: Number((safeQty * safePrice).toFixed(2)),
        section_name: normSection,
        source_table_index: item.source_table_index !== null && item.source_table_index !== undefined
          ? Number(item.source_table_index)
          : null,
        grouping_mode: normalizeCostGroupingMode(item.grouping_mode)
          || inferCostItemGroupingMode(item),
        children: [],
        // 传递基线快照与修改状态
        is_parent_modified: Boolean(item.is_parent_modified),
        is_child_modified: Boolean(item.is_child_modified),
        is_custom_added: Boolean(item.is_custom_added),
        pricing_mode: item.pricing_mode || (item.is_parent_modified ? 'parent' : 'auto'),
        raw_ref_price: item.raw_ref_price !== undefined ? item.raw_ref_price : safePrice,
        raw_name: item.raw_name || nodeName,
        raw_brand: item.raw_brand !== undefined ? item.raw_brand : (item.brand || item.matched_brand || ''),
        raw_model: item.raw_model !== undefined ? item.raw_model : (item.model || item.matched_model || ''),
        raw_manufacturer: item.raw_manufacturer !== undefined ? item.raw_manufacturer : (item.manufacturer || item.matched_manufacturer || ''),
        raw_spec: item.raw_spec !== undefined ? item.raw_spec : (item.spec_requirement || ''),
        raw_qty: item.raw_qty !== undefined ? item.raw_qty : safeQty,
        raw_unit: item.raw_unit !== undefined ? item.raw_unit : (rawUnit || ''),
        raw_match_quality: item.raw_match_quality || item.match_quality || '',
        part_name: item.part_name ? String(item.part_name).trim() : null,
        group_path: normalizeCostTextList(item.group_path),
      };
      return node;
    });

    // 当模型已经给出 tree_level，但 parent_item 因名称清洗或历史字段差异暂时无法命中时，
    // 使用同一分项下最近的上一级节点兜底挂载，避免已提取的父子关系在前端退化为平铺行。
    const isSameHierarchyScope = (current: CostItemNode, previous: CostItemNode): boolean => {
      const currentRoot = current.root_item ? String(current.root_item).trim() : '';
      const previousRoot = previous.root_item ? String(previous.root_item).trim() : '';
      const sameRoot = !currentRoot || !previousRoot || currentRoot === previousRoot;
      const sameSection = !current.section_name || !previous.section_name || current.section_name === previous.section_name;
      const sameExternalScope = current.grouping_mode === 'external'
        && previous.grouping_mode === 'external'
        && sameSection;
      const sameSourceTable = sameExternalScope
        || current.source_table_index === null
        || current.source_table_index === undefined
        || previous.source_table_index === null
        || previous.source_table_index === undefined
        || current.source_table_index === previous.source_table_index;
      return sameRoot && sameSection && sameSourceTable;
    };

    let recoveredHierarchyCount = 0;

    // 2. 就近向上回溯挂载算法（Backward Scope Matching）
    // 纯通用树构建算法：解决同名子节点挂载冲突，支持任意 N 级嵌套树结构
    const rootNodes: CostItemNode[] = [];
    let totalChildren = 0;

    for (let i = 0; i < allNodes.length; i++) {
      const node = allNodes[i];
      let parentName = node.parent_item;

      if (node.parent_node_id || parentName) {
        // 倒序向上查找最近的直接父节点
        let foundParent: CostItemNode | null = null;
        // 优先检查前方节点，再检查后方节点；模型分块合并后父项可能排在子项之后。
        const candidateIndices = [
          ...Array.from({ length: i }, (_, index) => i - index - 1),
          ...Array.from({ length: allNodes.length - i - 1 }, (_, index) => i + index + 1),
        ];
        let partialNameParent: CostItemNode | null = null;
        for (const j of candidateIndices) {
          const prev = allNodes[j];
          const prevName = String(prev.name || '').trim();

          // 新数据优先使用稳定节点 ID；只有历史数据才退回名称匹配。
          const nodeIdMatches = Boolean(node.parent_node_id && prev.node_id === node.parent_node_id);
          if (nodeIdMatches) {
            // 人工维护的稳定父节点关系优先级最高，允许跨来源表保持明确归属。
            foundParent = prev;
            break;
          }

          if (!parentName) continue;

          // 名称匹配：精确匹配，或候选父节点全称包含子项指定的父项名称（如 "4(九) 铁附件、电缆防火封堵" 包含 "铁附件、电缆防火封堵"）
          // 严禁 parentName.includes(prevName)，防止短名称同级兄弟项（如 "铁附件"）误匹配复合名称父项（如 "铁附件、电缆防火封堵"）
          const nameMatches = prevName === parentName || prevName.includes(parentName);
          const nodeRoot = node.root_item ? String(node.root_item).trim() : '';
          const prevRoot = prev.root_item ? String(prev.root_item).trim() : '';
          const rootMatches = !nodeRoot || !prevRoot || nodeRoot === prevRoot || nodeRoot === prevName || prevName.includes(nodeRoot);
          const sectionMatches = !node.section_name || !prev.section_name || node.section_name === prev.section_name || node.section_name === '通用及其他分项';
          const sameExternalScope = node.grouping_mode === 'external'
            && prev.grouping_mode === 'external'
            && sectionMatches;
          const sourceTableMatches = sameExternalScope
            || node.source_table_index === null
            || node.source_table_index === undefined
            || prev.source_table_index === null
            || prev.source_table_index === undefined
            || node.source_table_index === prev.source_table_index;
          
          if (prevName === parentName && rootMatches && sectionMatches && sourceTableMatches && prev !== node) {
            foundParent = prev;
            break;
          }
          if (!partialNameParent && nameMatches && rootMatches && sectionMatches && sourceTableMatches && prev !== node) {
            partialNameParent = prev;
          }
        }

        if (!foundParent && partialNameParent) {
          foundParent = partialNameParent;
        }

        if (foundParent) {
          // 子节点若缺失分部，自动向上继承父节点分部
          if ((!node.section_name || node.section_name === '通用及其他分项') && foundParent.section_name && foundParent.section_name !== '通用及其他分项') {
            node.section_name = foundParent.section_name;
          }
          node.parent_node_id = foundParent.node_id || node.parent_node_id || null;
          node.parent_item = foundParent.name;
          foundParent.children = foundParent.children || [];
          foundParent.children.push(node);
          totalChildren += 1;
        } else {
          // parent_item 文本无法命中时，回退到模型已经明确给出的层级证据。
          const currentLevel = Number(node.tree_level) || 1;
          if (currentLevel > 1) {
            const levelParent = [
              ...allNodes.slice(0, i).reverse(),
              ...allNodes.slice(i + 1),
            ]
              .find((prev) => Number(prev.tree_level) === currentLevel - 1 && isSameHierarchyScope(node, prev));
            if (levelParent) {
              node.parent_item = levelParent.name;
              node.parent_node_id = levelParent.node_id || null;
              parentName = levelParent.name;
              levelParent.children = levelParent.children || [];
              levelParent.children.push(node);
              totalChildren += 1;
              recoveredHierarchyCount += 1;
              continue;
            }
          }
          // 没有可靠的名称或层级证据时，保留为根节点，不强行猜测父项。
          rootNodes.push(node);
        }
      } else {
        // 清单模式下，tree_level 是后端明确提取的结构证据；即使 parent_item 丢失，
        // 也尝试从最近的上一级节点恢复展示关系。
        const currentLevel = Number(node.tree_level) || 1;
        if (currentLevel > 1) {
          const levelParent = [
            ...allNodes.slice(0, i).reverse(),
            ...allNodes.slice(i + 1),
          ]
            .find((prev) => Number(prev.tree_level) === currentLevel - 1 && isSameHierarchyScope(node, prev));
          if (levelParent) {
            node.parent_item = levelParent.name;
            node.parent_node_id = levelParent.node_id || null;
            levelParent.children = levelParent.children || [];
            levelParent.children.push(node);
            totalChildren += 1;
            recoveredHierarchyCount += 1;
            continue;
          }
        }
        rootNodes.push(node);
      }
    }

    if (recoveredHierarchyCount > 0) {
      console.info(`[BOM] 已依据提取的 tree_level 恢复 ${recoveredHierarchyCount} 个父子挂载关系。`);
    }

    // 3. 递归标记 isParent、收集 parentKeys、计算深度与清理空 children
    const parentKeysList: React.Key[] = [];
    const traverseAndClean = (nodes: CostItemNode[], currentLevel: number) => {
      // 子节点按原始清单顺序稳定排列，避免父项后置时出现 7、1、2… 的展示顺序。
      nodes.sort((left, right) => left.originalIndex - right.originalIndex);
      nodes.forEach(node => {
        // 树深度对齐与层级校准
        node.tree_level = Math.max(Number(node.tree_level) || 1, currentLevel);
        if (node.children && node.children.length > 0) {
          node.isParent = true;
          node.childCount = node.children.length;
          parentKeysList.push(node.key);
          traverseAndClean(node.children, currentLevel + 1);
        } else {
          node.isParent = false;
          node.childCount = 0;
          delete node.children;
        }
      });
    };

    traverseAndClean(rootNodes, 1);

    // 3.5 标记父子互斥状态与锁（isLockedByParent, hasModifiedChildren, isLockedByChildren, hasPricedChildren）
    const markMutualExclusion = (node: CostItemNode, parentLockedByAncestor: boolean) => {
      const hasChildren = Boolean(node.children && node.children.length > 0);
      node.isLockedByParent = parentLockedByAncestor;

      if (hasChildren && node.children) {
        // 检查名下所有子项是否有价格或被手动修改
        let anyChildHasPrice = false;
        let anyChildModified = false;

        node.children.forEach(child => {
          const childSubtotal = Number(child.subtotal) || 0;
          const childPrice = Number(child.ref_price) || 0;
          if (childSubtotal > 0 || childPrice > 0) {
            anyChildHasPrice = true;
          }
          if (child.is_child_modified || (child.match_quality === '手动修改' && !child.is_parent_modified)) {
            anyChildModified = true;
          }
        });

        // 判断当前成套设备自身是否处于成套统价模式：
        // 1. 用户手动直接修改了父项价格 (is_parent_modified || pricing_mode === 'parent')
        // 2. 或者父项自身有单价，且名下所有子项目前均未录入有效金额（此时保持父项统价有效）
        const isSelfCustomParent = Boolean(
          (node.is_parent_modified || node.pricing_mode === 'parent') && Number(node.ref_price) > 0
        );
        const isSelfDefaultParentPrice = Boolean(
          node.pricing_mode !== 'children' && Number(node.ref_price) > 0 && !anyChildHasPrice
        );
        const isParentDominant = !parentLockedByAncestor && (isSelfCustomParent || isSelfDefaultParentPrice);

        // 如果父项处于成套统价主导状态，名下所有子项均被母项统价锁定
        node.children.forEach(child => {
          markMutualExclusion(child, parentLockedByAncestor || isParentDominant);
        });

        node.hasPricedChildren = anyChildHasPrice;
        node.hasModifiedChildren = anyChildModified;
        // 若下属子项已有有效金额，成套价格必须由子项汇总驱动，父项直接修改被互斥锁定
        node.isLockedByChildren = anyChildHasPrice;
      }
    };

    rootNodes.forEach(root => markMutualExclusion(root, false));

    // 4. 自底向上（Bottom-Up）递归汇总父节点金额与折算参考单价
    const rollupNodePrices = (node: CostItemNode): number => {
      if (node.children && node.children.length > 0) {
        let childrenSubtotalSum = 0;
        let childrenWithPriceCount = 0;

        node.children.forEach(child => {
          childrenSubtotalSum += rollupNodePrices(child);
          if ((child.subtotal || 0) > 0) {
            childrenWithPriceCount += (child.isRollupPrice && child.rollupChildCount ? child.rollupChildCount : 1);
          }
        });

        // 判断当前父节点自身是否正在被直接行内编辑
        const isSelfEditing = editingIndex === node.originalIndex;
        // 生效的父项自定义统价：自身设定了统价，且【未被上级祖先统价锁定】
        const isParentModified = Boolean((node.is_parent_modified || node.pricing_mode === 'parent') && !node.isLockedByParent);
        const directChildCount = node.children.length;
        const missingCount = Math.max(0, directChildCount - childrenWithPriceCount);

        if (node.isLockedByParent) {
          // 已被上级成套父项统价锁定，自身金额已统入上级成套价，不对外独立输出小计
          node.subtotal = 0;
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        } else if (isSelfEditing) {
          // 用户当前正直接编辑该母项单价
          const safeQty = editQty > 0 ? editQty : 1;
          node.subtotal = Number((safeQty * editPrice).toFixed(2));
          node.ref_price = editPrice;
          node.isRollupPrice = false;
          node.isPartialRollup = false;
          node.match_quality = '手动修改';
        } else if (isParentModified && (node.ref_price > 0 || (node.subtotal && node.subtotal > 0))) {
          // 用户已直接修改父项价格：父项统价优先！不再被子项求和覆盖
          const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
          const safePrice = Number(node.ref_price) >= 0 ? Number(node.ref_price) : 0;
          node.subtotal = Number((safeQty * safePrice).toFixed(2));
          node.isRollupPrice = false;
          node.isPartialRollup = false;
          if (!node.match_quality || node.match_quality === '成套汇总' || node.match_quality === '未匹配') {
            node.match_quality = '手动修改';
          }
        } else if (childrenSubtotalSum > 0) {
          // 子项有金额且父项未自定义 -> 始终由子项自底向上汇总实时驱动！
          node.subtotal = Number(childrenSubtotalSum.toFixed(2));
          const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
          node.ref_price = Number((childrenSubtotalSum / safeQty).toFixed(2));
          node.isRollupPrice = true;
          node.isPartialRollup = missingCount > 0;
          node.rollupChildCount = childrenWithPriceCount;
          node.missingChildPriceCount = missingCount;
          node.match_quality = '成套汇总';
        } else if (node.pricing_mode !== 'children' && node.ref_price > 0 && node.match_quality !== '未匹配' && node.match_quality !== '成套汇总') {
          // 子项无金额，母项自身有打包统价
          const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
          node.subtotal = Number((safeQty * (node.ref_price || 0)).toFixed(2));
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        } else {
          node.subtotal = 0;
          node.ref_price = 0;
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        }

        return node.subtotal || 0;
      } else {
        // 叶子节点
        if (node.isLockedByParent) {
          // 已被上级成套父项统价锁定，金额已统入母项，对外小计规整为 0
          node.subtotal = 0;
          node.isRollupPrice = false;
          return 0;
        }
        const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
        const safePrice = node.ref_price && node.ref_price > 0 ? Number(node.ref_price) : 0;
        node.subtotal = Number((safeQty * safePrice).toFixed(2));
        node.isRollupPrice = false;
        return node.subtotal;
      }
    };

    rootNodes.forEach(root => rollupNodePrices(root));

    return {
      treeData: rootNodes,
      allParentKeys: parentKeysList,
      parentCount: parentKeysList.length,
      childCountTotal: totalChildren
    };
  }, [items, availableSections, editingIndex, editPrice, editQty, editName, editBrand, editModel, editManufacturer, editSpec, editUnit]);

  // 清理删除或重新提取后已经不存在的勾选项，避免批量操作误引用旧行。
  useEffect(() => {
    const validKeys = new Set<React.Key>(flattenCostTreeNodes(treeData).map((node) => node.key));
    setSelectedNodeKeys((currentKeys) => currentKeys.filter((key) => validKeys.has(key)));
  }, [treeData]);

  // 根据选中的分标段/分区域进行视图筛选（纯数据驱动）
  const filteredTreeData = React.useMemo(() => {
    const hasSectionFilter = selectedSection !== 'ALL' && availableSections.includes(selectedSection);
    const hasPartFilter = selectedPart !== 'ALL' && availableParts.includes(selectedPart);
    if (!hasSectionFilter && !hasPartFilter) {
      return treeData;
    }
    const filterNodesBySection = (nodes: CostItemNode[]): CostItemNode[] => (
      nodes.reduce<CostItemNode[]>((matchedNodes, node) => {
        const matchedChildren = node.children
          ? filterNodesBySection(node.children)
          : [];
        const sectionMatches = !hasSectionFilter || node.section_name === selectedSection;
        const partMatches = !hasPartFilter || node.part_name === selectedPart;
        const nodeMatches = sectionMatches && partMatches;
        if (!nodeMatches && matchedChildren.length === 0) {
          return matchedNodes;
        }
        matchedNodes.push({
          ...node,
          ...(node.children ? { children: matchedChildren } : {}),
          ...(hasPartFilter
            ? {
                isInternalFilterContextNode: !partMatches && matchedChildren.length > 0,
              }
            : {}),
        });
        return matchedNodes;
      }, [])
    );

    return filterNodesBySection(treeData);
  }, [treeData, selectedSection, selectedPart, availableSections, availableParts]);

  // 受控展开行 Keys
  const [expandedRowKeys, setExpandedRowKeys] = useState<readonly React.Key[]>([]);

  // 数据源刷新时的折叠行为由上方的 props 同步 Effect 统一处理，不再自动展开树节点。

  // 是否已全部展开
  const isAllExpanded = allParentKeys.length > 0 && expandedRowKeys.length >= allParentKeys.length;

  // 展开所有
  const expandAll = () => {
    setExpandedRowKeys(allParentKeys);
  };

  // 折叠所有
  const collapseAll = () => {
    setExpandedRowKeys([]);
  };

  // 一键智能切换全部展开 / 全部折叠
  const toggleExpandAll = () => {
    if (isAllExpanded) {
      collapseAll();
    } else {
      expandAll();
    }
  };

  // 实时联动计算预估总成本（严格以顶层根节点 subtotal 求和，杜绝父子项双重计费）
  const realTimeTotalCost = React.useMemo(() => {
    return treeData.reduce((sum, rootNode) => sum + (rootNode.subtotal || 0), 0);
  }, [treeData]);

  // 严格优先级提取限价：1. 最高投标限价 (max_price_limit) > 2. 采购总预算 (budget) > 3. costAnalysis.budget_numeric / costAnalysis.budget_limit
  const maxPriceLimitAmount = financial?.max_price_limit?.amount ? Number(financial.max_price_limit.amount) : null;
  const budgetAmount = financial?.budget?.amount ? Number(financial.budget.amount) : null;

  let effectiveLimitAmount: number | null = null;
  let limitTypeLabel = '';

  if (maxPriceLimitAmount && maxPriceLimitAmount > 0) {
    effectiveLimitAmount = maxPriceLimitAmount;
    limitTypeLabel = '最高投标限价';
  } else if (budgetAmount && budgetAmount > 0) {
    effectiveLimitAmount = budgetAmount;
    limitTypeLabel = '采购总预算';
  } else if (costAnalysis?.budget_numeric && Number(costAnalysis.budget_numeric) > 0) {
    effectiveLimitAmount = Number(costAnalysis.budget_numeric);
    limitTypeLabel = costAnalysis.limit_type === 'max_price_limit' ? '最高投标限价' : (costAnalysis.limit_type === 'budget' ? '采购总预算' : '预算上限');
  } else if (costAnalysis?.budget_limit) {
    const cleaned = String(costAnalysis.budget_limit).replace(/[^\d.]/g, '');
    if (cleaned && Number(cleaned) > 0) {
      effectiveLimitAmount = Number(cleaned);
      limitTypeLabel = '预算限额';
    }
  }

  // 实时计算预算与超额状态
  let isRealTimeExceeded = false;
  let isRealTimeWarning = false;
  let dynamicStatusText = isEquipmentOnly ? '' : normalizeCostText(costAnalysis.budget_status);
  let overrunAmount = 0;
  let usageRatio = 0;

  if (effectiveLimitAmount && effectiveLimitAmount > 0 && realTimeTotalCost > 0) {
    usageRatio = Number(((realTimeTotalCost / effectiveLimitAmount) * 100).toFixed(1));
    if (realTimeTotalCost > effectiveLimitAmount) {
      isRealTimeExceeded = true;
      overrunAmount = Number((realTimeTotalCost - effectiveLimitAmount).toFixed(2));
      dynamicStatusText = `已超出${limitTypeLabel} (使用率 ${usageRatio}%, 超额 ¥${overrunAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })})`;
    } else if (usageRatio >= 90) {
      isRealTimeWarning = true;
      dynamicStatusText = `接近${limitTypeLabel} (使用率 ${usageRatio}%)`;
    } else {
      dynamicStatusText = `在${limitTypeLabel}内可控 (使用率 ${usageRatio}%)`;
    }
  } else if (dynamicStatusText) {
    isRealTimeExceeded = dynamicStatusText.includes('已超出');
    isRealTimeWarning = dynamicStatusText.includes('接近');
  }

  // 导出为 Word 文档 (.docx)
  const handleExportDocx = async () => {
    if (!items || items.length === 0) {
      message.warning('暂无 BOM 测算数据可导出');
      return;
    }
    try {
      setIsExporting(true);
      message.loading({ content: '正在生成 BOM 成本测算 Word 文档...', key: 'bom_export' });
      await exportBomToDocx({
        documentId,
        documentTitle: documentFilename,
        items: filteredTreeData && filteredTreeData.length > 0 ? filteredTreeData : items,
        totalCost: realTimeTotalCost,
        budgetLimit: effectiveLimitAmount ? `¥${effectiveLimitAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : undefined,
        statusText: dynamicStatusText,
        analysisSummary: normalizeCostText(costAnalysis?.analysis_summary)
      });
      message.success({ content: 'BOM 成本测算 Word 文档导出成功！', key: 'bom_export' });
    } catch (err: any) {
      console.error('Export BOM docx error:', err);
      message.error({ content: err?.message || '导出 Word 文档失败', key: 'bom_export' });
    } finally {
      setIsExporting(false);
    }
  };

  // 导出为 Excel 表格 (.xlsx)
  const handleExportXlsx = async () => {
    if (!items || items.length === 0) {
      message.warning('暂无 BOM 测算数据可导出');
      return;
    }
    try {
      setIsExporting(true);
      message.loading({ content: '正在生成 BOM 成本测算 Excel 表格...', key: 'bom_export' });
      await exportBomToXlsx({
        documentId,
        documentTitle: documentFilename,
        items: filteredTreeData && filteredTreeData.length > 0 ? filteredTreeData : items,
        totalCost: realTimeTotalCost,
        budgetLimit: effectiveLimitAmount ? `¥${effectiveLimitAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : undefined,
        statusText: dynamicStatusText,
        analysisSummary: normalizeCostText(costAnalysis?.analysis_summary)
      });
      message.success({ content: 'BOM 成本测算 Excel 表格导出成功！', key: 'bom_export' });
    } catch (err: any) {
      console.error('Export BOM xlsx error:', err);
      message.error({ content: err?.message || '导出 Excel 表格失败', key: 'bom_export' });
    } finally {
      setIsExporting(false);
    }
  };

  // 开启行内编辑模式
  const handleStartEdit = (record: CostItemNode) => {
    if (record.isLockedByParent) {
      message.warning(`该项所属的成套设备「${record.parent_item || '上级父项'}」已启用父项自定义定价，下属内容已全部锁定。如需修改，请先在上方重置父项。`, 4);
      return;
    }
    if (record.isParent) {
      if (record.isLockedByChildren) {
        message.warning(`成套设备「${record.name}」已修改下属子项，当前价格由子项自动汇总。如需直接修改父项，请先点击「重置子项」。`, 4);
        return;
      }
      // 若该母项当前未展开，自动为用户展开下属子项方便查看
      if (!expandedRowKeys.includes(record.key)) {
        setExpandedRowKeys(prev => Array.from(new Set([...prev, record.key])));
      }
    }
    setEditingKey(record.key);
    setEditingIndex(record.originalIndex);
    setEditName(record.name || '');
    setEditBrand(record.matched_brand || record.brand || record.brand_requirements || '');
    setEditModel(record.matched_model || record.model || '');
    setEditManufacturer(record.matched_manufacturer || record.manufacturer || '');
    setEditSpec(record.spec_requirement || '');
    setEditRemark(record.remark || '');
    setEditQty(record.qty !== null && record.qty !== undefined ? Number(record.qty) : 1);
    setEditUnit(record.unit || '');
    setEditPrice(record.ref_price ? Number(record.ref_price) : 0);
  };

  // 取消行内编辑
  const handleCancelEdit = () => {
    setEditingKey(null);
    setEditingIndex(null);
    setEditName('');
    setEditBrand('');
    setEditModel('');
    setEditManufacturer('');
    setEditSpec('');
    setEditRemark('');
  };

  /** 打开表内 BOQ 分组编辑弹窗；筛选结果中的上下文父节点不允许直接改名。 */
  const handleOpenGroupEdit = (record: CostItemNode) => {
    if (record.isInternalFilterContextNode) {
      message.info('当前节点只是筛选结果中的父级路径，请选择实际分组项进行修改。');
      return;
    }
    const groupContext = getBomGroupContext(record);
    const groupPartName = normalizeCostText(record.part_name).trim() || groupContext[0] || '';
    const groupName = getCostInternalGroupDisplayText(record, 'ALL');
    if (!groupName) {
      message.warning('当前标的物没有可编辑的表内分组。');
      return;
    }
    setGroupEditingRecord(record);
    setGroupEditPartName(groupPartName);
    setGroupEditName(groupName);
    setIsGroupEditModalOpen(true);
  };

  /** 关闭表内 BOQ 分组编辑弹窗并清理临时状态。 */
  const handleCancelGroupEdit = () => {
    setIsGroupEditModalOpen(false);
    setGroupEditingRecord(null);
    setGroupEditPartName('');
    setGroupEditName('');
  };

  /** 保存表内 BOQ 主分组和末级分组，并把改动写入最新成本分析快照。 */
  const handleSaveGroupEdit = () => {
    if (!groupEditingRecord) return;
    const nextPartName = groupEditPartName.trim();
    const nextGroupName = groupEditName.trim();
    if (!nextPartName) {
      message.warning('主分组名称不能为空。');
      return;
    }

    const updateResult = updateCostGroupContext(
      items,
      groupEditingRecord,
      nextPartName,
      nextGroupName,
    );
    if (updateResult.updatedCount === 0) {
      message.info('分组名称未发生变化。');
      handleCancelGroupEdit();
      return;
    }

    setItems(updateResult.items);
    handleCancelGroupEdit();
    console.info('[成本表] 已修改表内 BOQ 主分组及末级分组。', {
      oldPartName: normalizeCostText(groupEditingRecord.part_name).trim(),
      newPartName: nextPartName,
      newGroupName: nextGroupName,
      updatedCount: updateResult.updatedCount,
    });
    saveCostAnalysis(updateResult.items);
    const displayName = nextGroupName ? `${nextPartName} / ${nextGroupName}` : nextPartName;
    message.success(`已将表内分组修改为「${displayName}」，同步更新 ${updateResult.updatedCount} 项。`, 4);
  };

  /** 打开表内分组设置弹窗，默认沿用当前筛选项或外部分项作为主分组候选。 */
  const handleOpenGroupAssign = (record: CostItemNode) => {
    if (record.isInternalFilterContextNode) {
      message.info('当前节点只是筛选结果中的父级路径，请选择实际清单项进行设置。');
      return;
    }
    setGroupAssignRecord(record);
    setGroupAssignPartName(
      selectedPart !== 'ALL'
        ? selectedPart
        : normalizeSectionName(record.section_name) || '',
    );
    setGroupAssignName('');
    setIsGroupAssignModalOpen(true);
  };

  /** 关闭表内分组设置弹窗并清理临时状态。 */
  const handleCancelGroupAssign = () => {
    setIsGroupAssignModalOpen(false);
    setGroupAssignRecord(null);
    setGroupAssignPartName('');
    setGroupAssignName('');
  };

  /** 保存新设置的表内分组，并将其写入当前成本分析快照。 */
  const handleSaveGroupAssign = () => {
    if (!groupAssignRecord) return;
    const assignResult = assignCostGroupContext(
      items,
      groupAssignRecord.originalIndex,
      groupAssignPartName,
      groupAssignName,
    );
    if (assignResult.updatedCount === 0) {
      message.warning('请填写有效的主分组名称。末级分组没有下级分类时可以留空。');
      return;
    }

    setItems(assignResult.items);
    handleCancelGroupAssign();
    console.info('[成本表] 已为原无分组节点设置表内 BOQ 分组。', {
      partName: normalizeCostText(groupAssignPartName).trim(),
      groupName: normalizeCostText(groupAssignName).trim(),
      updatedCount: assignResult.updatedCount,
    });
    saveCostAnalysis(assignResult.items);
    message.success(`已设置表内分组，同步更新 ${assignResult.updatedCount} 项。`, 4);
  };

  /** 打开批量设置表内分组弹窗，使用当前已勾选的可操作节点。 */
  const handleOpenBatchGroupAssign = () => {
    const selectedRecords = flattenCostTreeNodes(treeData).filter(
      (record) => selectedNodeKeys.includes(record.key) && !record.isInternalFilterContextNode,
    );
    if (selectedRecords.length === 0) {
      message.warning('请先勾选需要设置表内分组的标的物。');
      return;
    }

    setBatchGroupPartName(
      selectedPart !== 'ALL'
        ? selectedPart
        : normalizeSectionName(selectedRecords[0].section_name) || '',
    );
    setBatchGroupName('');
    setIsBatchGroupAssignModalOpen(true);
  };

  /** 关闭批量设置表内分组弹窗并清理临时状态。 */
  const handleCancelBatchGroupAssign = () => {
    setIsBatchGroupAssignModalOpen(false);
    setBatchGroupPartName('');
    setBatchGroupName('');
  };

  /** 将批量设置的分组同步到已勾选节点及其子树，并统一保存。 */
  const handleSaveBatchGroupAssign = () => {
    const selectedRecords = flattenCostTreeNodes(treeData).filter(
      (record) => selectedNodeKeys.includes(record.key) && !record.isInternalFilterContextNode,
    );
    const assignResult = assignCostGroupContextToNodes(
      items,
      selectedRecords.map((record) => record.originalIndex),
      batchGroupPartName,
      batchGroupName,
    );
    if (assignResult.updatedCount === 0) {
      message.warning('请先选择节点并填写有效的主分组名称；末级分组可以留空。');
      return;
    }

    setItems(assignResult.items);
    setSelectedNodeKeys([]);
    handleCancelBatchGroupAssign();
    console.info('[成本表] 已批量设置表内 BOQ 分组。', {
      selectedCount: selectedRecords.length,
      partName: normalizeCostText(batchGroupPartName).trim(),
      groupName: normalizeCostText(batchGroupName).trim(),
      updatedCount: assignResult.updatedCount,
    });
    saveCostAnalysis(assignResult.items);
    message.success(`已批量设置表内分组，同步更新 ${assignResult.updatedCount} 项。`, 4);
  };

  // 确认修改单行价格、品牌、型号、厂商与数量并落盘
  const handleSaveEdit = (record: CostItemNode) => {
    const updatedItems = [...items];
    const targetIdx = record.originalIndex;
    if (targetIdx < 0 || targetIdx >= updatedItems.length) return;

    const targetItem = { ...updatedItems[targetIdx] };
    const brandTrimmed = editBrand.trim();
    const modelTrimmed = editModel.trim();
    const mfgTrimmed = editManufacturer.trim();

    targetItem.name = editName.trim() || targetItem.name;
    targetItem.matched_brand = brandTrimmed;
    targetItem.brand = brandTrimmed;
    targetItem.matched_model = modelTrimmed;
    targetItem.model = modelTrimmed;
    targetItem.matched_manufacturer = mfgTrimmed;
    targetItem.manufacturer = mfgTrimmed;
    targetItem.spec_requirement = editSpec.trim() || targetItem.spec_requirement;
    targetItem.remark = editRemark.trim();
    targetItem.qty = editQty > 0 ? editQty : 1;
    targetItem.unit = editUnit.trim() ? editUnit.trim() : null;
    targetItem.ref_price = editPrice >= 0 ? editPrice : 0;
    targetItem.subtotal = Number((targetItem.qty * targetItem.ref_price).toFixed(2));

    if (record.isParent) {
      // 修改了父项：标记为父项自定义模式，锁定下属子项
      targetItem.is_parent_modified = true;
      targetItem.pricing_mode = 'parent';
      targetItem.match_quality = '手动修改';
    } else {
      // 修改了子项或独立项
      targetItem.is_child_modified = true;
      targetItem.match_quality = '手动修改';
      // 如果属于某个父项，将所属父项置为子项汇总定价模式
      if (record.parent_item || record.parent_node_id) {
        const parentIdx = record.parent_node_id
          ? items.findIndex(it => it.node_id === record.parent_node_id)
          : items.findIndex(it => it.name === record.parent_item);
        if (parentIdx >= 0 && updatedItems[parentIdx]) {
          updatedItems[parentIdx] = {
            ...updatedItems[parentIdx],
            is_parent_modified: false,
            pricing_mode: 'children'
          };
        }
      }
    }

    updatedItems[targetIdx] = targetItem;
    setItems(updatedItems);
    setEditingKey(null);
    setEditingIndex(null);
    saveCostAnalysis(updatedItems);
  };

  // 重置父项：恢复父项初始基线数据，清除父项自定义覆盖，并解锁下属子项修改与添加权限
  const handleResetParent = (record: CostItemNode) => {
    const updatedItems = [...items];
    const targetIdx = record.originalIndex;
    if (targetIdx < 0 || targetIdx >= updatedItems.length) return;

    const targetItem = { ...updatedItems[targetIdx] };
    targetItem.name = targetItem.raw_name || targetItem.name;
    targetItem.matched_brand = targetItem.raw_brand || '';
    targetItem.brand = targetItem.raw_brand || '';
    targetItem.matched_model = targetItem.raw_model || '';
    targetItem.model = targetItem.raw_model || '';
    targetItem.matched_manufacturer = targetItem.raw_manufacturer || '';
    targetItem.manufacturer = targetItem.raw_manufacturer || '';
    targetItem.spec_requirement = targetItem.raw_spec || targetItem.spec_requirement;
    targetItem.qty = targetItem.raw_qty !== undefined ? targetItem.raw_qty : targetItem.qty;
    targetItem.unit = targetItem.raw_unit || targetItem.unit;
    targetItem.ref_price = targetItem.raw_ref_price !== undefined ? targetItem.raw_ref_price : 0;
    targetItem.subtotal = Number(((targetItem.qty || 1) * targetItem.ref_price).toFixed(2));
    targetItem.match_quality = targetItem.raw_match_quality || '成套汇总';
    targetItem.is_parent_modified = false;
    targetItem.pricing_mode = 'children';

    updatedItems[targetIdx] = targetItem;
    setItems(updatedItems);
    if (editingIndex === targetIdx) {
      handleCancelEdit();
    }
    saveCostAnalysis(updatedItems);
    message.success(`已重置成套设备「${record.name}」，已恢复初始状态并解锁下属子项修改与添加！`, 4);
  };

  // 清空成套设备自身价格，解除对名下所有子项的锁定，进入子项汇总定价模式
  const handleClearParentPrice = (record: CostItemNode) => {
    const updatedItems = [...items];
    const targetIdx = record.originalIndex;
    if (targetIdx < 0 || targetIdx >= updatedItems.length) return;

    const targetItem = { ...updatedItems[targetIdx] };
    targetItem.ref_price = 0;
    targetItem.subtotal = 0;
    targetItem.is_parent_modified = false;
    targetItem.pricing_mode = 'children';
    targetItem.match_quality = '成套汇总';

    updatedItems[targetIdx] = targetItem;
    setItems(updatedItems);
    if (editingIndex === targetIdx) {
      handleCancelEdit();
    }
    saveCostAnalysis(updatedItems);
    message.success(`已清空成套设备「${record.name}」的价格，已解锁名下全部 ${record.childCount || 1} 个子项的修改价格功能！`, 4);
  };

  // 清空成套设备名下所有子项的价格，重新解锁直接修改父项成套总价
  const handleClearChildrenPrices = (record: CostItemNode) => {
    const targetIdx = record.originalIndex;
    if (targetIdx < 0 || targetIdx >= items.length) return;

    const childIndices = getCostResetChildIndices(items, targetIdx);
    if (childIndices.length === 0) return;

    const updatedItems = items.map((item, index) => {
      if (childIndices.includes(index)) {
        return {
          ...item,
          ref_price: 0,
          subtotal: 0,
          is_child_modified: false,
          match_quality: '未匹配',
        };
      }
      if (index === targetIdx) {
        return {
          ...item,
          is_parent_modified: false,
          pricing_mode: 'children',
        };
      }
      return item;
    });

    setItems(updatedItems);
    handleCancelEdit();
    saveCostAnalysis(updatedItems);
    message.success(`已清空名下全部 ${childIndices.length} 个子项的价格，已重新解锁成套设备「${record.name}」直接统价权限！`, 4);
  };

  // 重置子项：恢复原始提取子项的基线数据，保留手动新增项，并解锁父项直接修改
  const handleResetChildren = (record: CostItemNode) => {
    const parentName = record.name;
    const targetIndex = record.originalIndex;
    const resetResult = resetCostChildrenPreservingCustomItems(items, targetIndex);
    if (resetResult.items === items) return;

    setItems(resetResult.items);
    handleCancelEdit();
    saveCostAnalysis(resetResult.items);
    console.info('[BOM] 已重置原始子项并保留手动新增项。', {
      parentName,
      restoredChildCount: resetResult.restoredChildCount,
      preservedCustomCount: resetResult.preservedCustomCount,
    });
    message.success(`已重置成套设备「${record.name}」的原始子项，已保留手动新增项并解锁父项直接修改！`, 4);
  };

  // 重置单项（适用于独立项或单个子项）
  const handleResetSingleItem = (record: CostItemNode) => {
    const updatedItems = [...items];
    const targetIdx = record.originalIndex;
    if (targetIdx < 0 || targetIdx >= updatedItems.length) return;

    const item = { ...updatedItems[targetIdx] };
    item.name = item.raw_name || item.name;
    item.matched_brand = item.raw_brand || '';
    item.brand = item.raw_brand || '';
    item.matched_model = item.raw_model || '';
    item.model = item.raw_model || '';
    item.matched_manufacturer = item.raw_manufacturer || '';
    item.manufacturer = item.raw_manufacturer || '';
    item.spec_requirement = item.raw_spec || item.spec_requirement;
    item.qty = item.raw_qty !== undefined ? item.raw_qty : item.qty;
    item.unit = item.raw_unit || item.unit;
    item.ref_price = item.raw_ref_price !== undefined ? item.raw_ref_price : 0;
    item.subtotal = Number(((item.qty || 1) * item.ref_price).toFixed(2));
    item.match_quality = item.raw_match_quality || (item.ref_price > 0 ? '精准匹配' : '未匹配');
    item.is_child_modified = false;
    item.is_parent_modified = false;

    updatedItems[targetIdx] = item;
    setItems(updatedItems);
    if (editingIndex === targetIdx) {
      handleCancelEdit();
    }
    saveCostAnalysis(updatedItems);
    message.success(`已重置「${record.name}」至初始状态。`, 3);
  };

  /** 根据节点 ID 找到当前树中的节点，供移动和同级新增复用。 */
  const findTreeNodeById = (nodeId: string | null | undefined): CostItemNode | null => {
    if (!nodeId) return null;
    return flattenCostTreeNodes(treeData).find((node) => node.node_id === nodeId) || null;
  };

  /** 将节点移动到新的父节点下，并持久化整棵树。 */
  const handleMoveNodeToParent = (sourceNodeId: string, targetParentId: string | null) => {
    const targetParent = findTreeNodeById(targetParentId);
    if (targetParent?.is_parent_modified || targetParent?.pricing_mode === 'parent') {
      message.warning(`目标父项「${targetParent.name}」已启用自定义统价，请先重置父项后再挂载子项。`, 4);
      return;
    }

    const result = moveCostSubtree(items, sourceNodeId, targetParentId);
    if (!result.moved) {
      const warningText = result.reason === 'descendant_target'
        ? '不能将节点移动到自己或自己的子孙节点下面。'
        : '节点移动失败，请刷新后重试。';
      message.warning(warningText, 4);
      return;
    }

    setItems(result.items);
    // 恢复拖拽开始时的展开状态：目标父项折叠时不因挂载子项被强制展开，已展开时也继续保持展开。
    const dragStartKeys = dragStartExpandedRowKeysRef.current;
    if (dragStartKeys) {
      setExpandedRowKeys((currentKeys) => restoreCostExpandedKeysAfterDrag(
        currentKeys,
        dragStartKeys,
      ));
      console.info('[BOM] 拖拽挂载完成，已恢复拖拽前的展开状态。', {
        sourceNodeId,
        targetParentId,
      });
    }
    setDraggingNodeId(null);
    setDragOverNodeId(null);
    setDragOverPlacement(null);
    saveCostAnalysis(result.items);
    message.success(targetParent ? `已将节点移动到「${targetParent.name}」下。` : '已将节点调整为顶层标的物。', 3);
  };

  /** 脱离当前父项后，提升一级并与原父节点保持同级。 */
  const handleDetachFromParent = (record: CostItemNode) => {
    if (!record.node_id) return;
    // 优先读取当前扁平数据，避免使用表格重渲染前遗留的行对象关系。
    const sourceItem = items.find((item) => normalizeCostText(item.node_id).trim() === record.node_id);
    // record 的父项关系已经过当前树构建阶段校准，优先于可能残留的原始扁平字段。
    const currentParentId = resolveCostDetachAnchorNodeId(items, record, sourceItem);
    if (!currentParentId) return;

    // 以原父项为锚点执行同级插入，避免脱离后的节点被追加到整个表单末尾。
    const result = moveCostSubtreeAsSibling(items, sourceItem?.node_id || record.node_id, currentParentId, 'after');
    if (!result.moved) {
      console.warn('[BOM] 脱离节点失败，源节点或原父项未找到。', {
        sourceNodeId: sourceItem?.node_id || record.node_id,
        currentParentId,
        reason: result.reason,
      });
      message.warning('节点脱离失败，请刷新后重试。', 4);
      return;
    }

    const currentParent = findTreeNodeById(currentParentId);
    setItems(result.items);
    setDraggingNodeId(null);
    setDragOverNodeId(null);
    setDragOverPlacement(null);
    saveCostAnalysis(result.items);
    message.success(
      currentParent
        ? `已将「${record.name}」提升一级，紧跟在「${currentParent.name}」之后。`
        : `已将「${record.name}」提升一级。`,
      3,
    );
  };

  /** 打开父项归属弹窗；空选项表示调整为顶层节点。 */
  const handleOpenMoveParentModal = (record: CostItemNode) => {
    setMovingNode(record);
    setMoveTargetParentId(record.parent_node_id || '');
    setIsMoveParentModalOpen(true);
  };

  const handleConfirmMoveParent = () => {
    if (!movingNode?.node_id) return;
    handleMoveNodeToParent(movingNode.node_id, moveTargetParentId || null);
    setIsMoveParentModalOpen(false);
    setMovingNode(null);
  };

  /** 拖拽事件只绑定到名称区域，避免影响表格内输入框编辑。 */
  const handleDragStart = (event: React.DragEvent<HTMLElement>, record: CostItemNode) => {
    if (!record.node_id || editingKey) return;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', record.node_id);
    dragStartExpandedRowKeysRef.current = [...expandedRowKeys];
    setDraggingNodeId(record.node_id);
  };

  const handleDragOver = (event: React.DragEvent<HTMLElement>, record: CostItemNode) => {
    if (!draggingNodeId || !record.node_id || draggingNodeId === record.node_id) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    setDragOverNodeId(record.node_id);
    const rowRect = event.currentTarget.getBoundingClientRect();
    setDragOverPlacement(resolveCostDropPlacement(event.clientY, rowRect.top, rowRect.height));
  };

  const handleDrop = (event: React.DragEvent<HTMLElement>, record: CostItemNode) => {
    event.preventDefault();
    const sourceNodeId = event.dataTransfer.getData('text/plain') || draggingNodeId;
    const rowRect = event.currentTarget.getBoundingClientRect();
    const dropPlacement = resolveCostDropPlacementAtDrop(
      event.clientY,
      rowRect.top,
      rowRect.height,
      dragOverPlacement,
    );
    if (sourceNodeId && record.node_id && dropPlacement) {
      if (dropPlacement === 'inside') {
        handleMoveNodeToParent(sourceNodeId, record.node_id);
      } else {
        const anchorNode = findTreeNodeById(record.node_id);
        const targetParent = findTreeNodeById(anchorNode?.parent_node_id);
        if (targetParent?.is_parent_modified || targetParent?.pricing_mode === 'parent') {
          message.warning(`目标父项「${targetParent.name}」已启用自定义统价，请先重置父项后再调整顺序。`, 4);
        } else {
          const result = moveCostSubtreeAsSibling(items, sourceNodeId, record.node_id, dropPlacement);
          if (!result.moved) {
            message.warning('节点排序失败，请刷新后重试。', 4);
          } else {
            setItems(result.items);
            const dragStartKeys = dragStartExpandedRowKeysRef.current;
            if (dragStartKeys) {
              setExpandedRowKeys((currentKeys) => restoreCostExpandedKeysAfterDrag(
                currentKeys,
                dragStartKeys,
              ));
            }
            saveCostAnalysis(result.items);
            message.success(
              dropPlacement === 'before'
                ? `已将节点移到「${record.name}」之前。`
                : `已将节点移到「${record.name}」之后。`,
              3,
            );
          }
        }
      }
    }
    setDraggingNodeId(null);
    setDragOverNodeId(null);
    setDragOverPlacement(null);
    dragStartExpandedRowKeysRef.current = null;
  };

  const handleDragEnd = () => {
    setDraggingNodeId(null);
    setDragOverNodeId(null);
    setDragOverPlacement(null);
    dragStartExpandedRowKeysRef.current = null;
  };

  const openAddNodeModal = (
    parentRecord: CostItemNode | null,
    anchorRecord: CostItemNode,
    mode: 'child' | 'sibling',
  ) => {
    if (parentRecord?.is_parent_modified || parentRecord?.pricing_mode === 'parent' || parentRecord?.isLockedByParent) {
      message.warning(`成套设备「${parentRecord.name}」已启用或属于父项统价锁定范围。如需新增或移动子项，请先重置对应父项。`, 4);
      return;
    }
    setAddNodeMode(mode);
    setAddAnchorNode(anchorRecord);
    setTargetParentNode(parentRecord);
    setChildFormName('');
    setChildFormBrand(parentRecord?.brand || parentRecord?.matched_brand || '');
    setChildFormModel('');
    setChildFormManufacturer(parentRecord?.manufacturer || parentRecord?.matched_manufacturer || '');
    setChildFormSpec('');
    setChildFormQty(1);
    setChildFormUnit(resolveCostNewNodeUnit(parentRecord?.unit));
    setChildFormPrice(0);
    setChildFormPerSetQty(1);
    setChildFormRemark('');
    setIsAddChildModalOpen(true);
  };

  // 打开添加子项弹窗
  const handleOpenAddChildModal = (parentRecord: CostItemNode) => {
    openAddNodeModal(parentRecord, parentRecord, 'child');
  };

  // 打开添加同级项弹窗；顶层节点的同级项会继续作为顶层节点创建。
  const handleOpenAddSiblingModal = (record: CostItemNode) => {
    const parentRecord = findTreeNodeById(record.parent_node_id);
    openAddNodeModal(parentRecord, record, 'sibling');
  };

  // 提交保存新增的子项
  const handleSaveNewChildItem = () => {
    if (!addAnchorNode || !childFormName.trim()) {
      message.error(`请输入${addNodeMode === 'sibling' ? '同级' : '子项'}标的物/设备名称`);
      return;
    }

    const brandVal = childFormBrand.trim();
    const modelVal = childFormModel.trim();
    const mfgVal = childFormManufacturer.trim();
    const specVal = childFormSpec.trim();
    const remarkVal = childFormRemark.trim();

    const parentName = targetParentNode?.name || null;
    const parentNodeId = targetParentNode?.node_id || null;
    // 子项继承目标父项分组；顶层同级项继承当前锚点分组，避免在筛选视图中新增后不可见。
    const insertionGroupingContext = resolveCostGroupingForNewNode(
      targetParentNode,
      addAnchorNode,
      'ALL',
      groupingDisplayMode,
    );
    const rootName = targetParentNode
      ? (targetParentNode.root_item || targetParentNode.name)
      : null;
    const targetLevel = targetParentNode ? (targetParentNode.tree_level || 1) + 1 : 1;
    const newChild: any = {
      name: childFormName.trim(),
      spec_requirement: specVal || modelVal || (parentName ? `成套设备「${parentName}」下属分项` : '自定义顶层标的物'),
      qty: childFormQty > 0 ? childFormQty : 1,
      unit: childFormUnit.trim() || '项',
      ref_price: childFormPrice >= 0 ? childFormPrice : 0,
      subtotal: Number(((childFormQty > 0 ? childFormQty : 1) * (childFormPrice >= 0 ? childFormPrice : 0)).toFixed(2)),
      matched_name: childFormName.trim(),
      matched_brand: brandVal || '自定义',
      brand: brandVal || '自定义',
      matched_model: modelVal,
      model: modelVal,
      matched_manufacturer: mfgVal,
      manufacturer: mfgVal,
      match_quality: '手动添加',
      comparison_note: parentName
        ? `成套设备「${parentName}」下手动新增${addNodeMode === 'sibling' ? '同级项' : '子项'}`
        : '用户手动新增顶层标的物',
      remark: remarkVal,
      key_parameters: [],
      brand_requirements: brandVal,
      parent_item: parentName,
      root_item: rootName,
      tree_level: targetLevel,
      per_set_qty: childFormPerSetQty > 0 ? childFormPerSetQty : (childFormQty > 0 ? childFormQty : 1),
      per_set_quantity: childFormPerSetQty > 0 ? childFormPerSetQty : (childFormQty > 0 ? childFormQty : 1),
      section_name: targetParentNode?.section_name || addAnchorNode.section_name || null,
      source_table_index: targetParentNode?.source_table_index ?? addAnchorNode.source_table_index ?? null,
      part_name: insertionGroupingContext.part_name,
      group_path: insertionGroupingContext.group_path,
      grouping_mode: insertionGroupingContext.grouping_mode,
      is_custom_added: true,
      is_child_modified: true,
      raw_ref_price: 0,
      raw_qty: childFormQty > 0 ? childFormQty : 1,
      raw_unit: childFormUnit.trim() || '项',
      raw_name: childFormName.trim(),
      raw_brand: brandVal,
      raw_model: modelVal,
      raw_manufacturer: mfgVal,
      raw_spec: specVal,
      raw_match_quality: '手动添加',
      node_id: createCostNodeId('custom_child'),
      parent_node_id: parentNodeId,
      sort_order: items.filter((item) => item.parent_node_id === parentNodeId).length,
    };

    // 保持扁平数组的前序树顺序：子项插入父项子树末尾，同级项插入锚点子树末尾。
    const insertIdx = getCostSubtreeEndIndex(items, addAnchorNode.originalIndex) + 1;

    const updatedItems = [...items];
    const parentIdx = targetParentNode?.originalIndex ?? -1;
    if (parentIdx >= 0 && parentIdx < updatedItems.length) {
      updatedItems[parentIdx] = {
        ...updatedItems[parentIdx],
        is_parent_modified: false,
        pricing_mode: 'children'
      };
    }
    updatedItems.splice(insertIdx, 0, newChild);

    setItems(updatedItems);
    if (targetParentNode) {
      setExpandedRowKeys(prev => Array.from(new Set([...prev, targetParentNode.key])));
    }
    setIsAddChildModalOpen(false);
    setAddAnchorNode(null);
    setTargetParentNode(null);
    saveCostAnalysis(updatedItems);
    message.success(
      parentName
        ? `已成功为「${parentName}」添加${addNodeMode === 'sibling' ? '同级项' : '子项'}「${childFormName.trim()}」！`
        : `已成功新增顶层标的物「${childFormName.trim()}」！`,
      4,
    );
  };

  // 添加自定义费用项
  const handleAddItem = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;

    const brandVal = newBrand.trim();
    const modelVal = newModel.trim();
    const mfgVal = newManufacturer.trim();
    const specVal = newSpec.trim();
    const remarkVal = newRemark.trim();

    const noteParts: string[] = [];
    if (brandVal) noteParts.push(`品牌: ${brandVal}`);
    if (modelVal) noteParts.push(`型号: ${modelVal}`);
    if (mfgVal) noteParts.push(`厂商: ${mfgVal}`);
    const comparisonNote = noteParts.length > 0 ? noteParts.join(' | ') : '用户在卡片上手动新增的成本费用分项';

    let parentName: string | null = null;
    let parentNodeId: string | null = null;
    let rootName: string | null = null;
    let level = 1;
    let sectionVal = selectedSection !== 'ALL' ? selectedSection : null;
    let parentObj: CostItemNode | undefined;

    if (newParentItem) {
      parentObj = flattenCostTreeNodes(treeData).find(n => n.node_id === newParentItem);
      parentName = parentObj?.name || null;
      parentNodeId = parentObj?.node_id || null;
      rootName = parentObj?.root_item || parentName;
      level = parentObj ? (parentObj.tree_level || 1) + 1 : 2;
      sectionVal = parentObj?.section_name || sectionVal;
    }

    // 新增子项继承父项分组；顶层新增在已筛选分组中时沿用当前分组，确保新增项立即可见。
    const insertionGroupingContext = resolveCostGroupingForNewNode(
      parentObj || null,
      null,
      selectedPart,
      groupingDisplayMode,
    );

    const newItem: any = {
      name: newName.trim(),
      spec_requirement: specVal || modelVal || (parentName ? `成套设备「${parentName}」下属分项` : '自定义费用分项（如人工/售后维保费）'),
      qty: newQty > 0 ? newQty : 1,
      unit: newUnit.trim() || (parentName ? '台' : '项'),
      ref_price: newPrice >= 0 ? newPrice : 0,
      subtotal: Number(((newQty > 0 ? newQty : 1) * (newPrice >= 0 ? newPrice : 0)).toFixed(2)),
      matched_name: newName.trim(),
      matched_brand: brandVal || '自定义',
      brand: brandVal || '自定义',
      matched_model: modelVal,
      model: modelVal,
      matched_manufacturer: mfgVal,
      manufacturer: mfgVal,
      match_quality: '手动添加',
      comparison_note: comparisonNote,
      remark: remarkVal,
      key_parameters: [],
      brand_requirements: brandVal,
      parent_item: parentName,
      root_item: rootName,
      tree_level: level,
      per_set_qty: newQty > 0 ? newQty : 1,
      per_set_quantity: newQty > 0 ? newQty : 1,
      section_name: sectionVal,
      part_name: insertionGroupingContext.part_name,
      group_path: insertionGroupingContext.group_path,
      source_table_index: parentName
        ? (parentObj?.source_table_index ?? null)
        : null,
      grouping_mode: groupingDisplayMode === 'mixed' ? 'none' : groupingDisplayMode,
      is_custom_added: true,
      is_child_modified: Boolean(parentName),
      raw_ref_price: 0,
      raw_qty: newQty > 0 ? newQty : 1,
      raw_unit: newUnit.trim() || (parentName ? '台' : '项'),
      raw_name: newName.trim(),
      raw_brand: brandVal,
      raw_model: modelVal,
      raw_manufacturer: mfgVal,
      raw_spec: specVal,
      raw_match_quality: '手动添加',
      node_id: createCostNodeId(parentName ? 'custom_child' : 'custom_root'),
      parent_node_id: parentNodeId,
      sort_order: parentObj
        ? items.filter((item) => item.parent_node_id === parentNodeId).length
        : items.length
    };

    let updatedItems = [...items];
    if (parentName) {
      // 挂载到父项：寻找该父项及其子项的最后位置插入
      const parentIdx = items.findIndex(it => it.node_id === parentNodeId);
      if (parentIdx >= 0) {
        const insertIdx = getCostSubtreeEndIndex(items, parentIdx) + 1;
        updatedItems[parentIdx] = {
          ...updatedItems[parentIdx],
          is_parent_modified: false,
          pricing_mode: 'children'
        };
        updatedItems.splice(insertIdx, 0, newItem);
      } else {
        updatedItems.push(newItem);
      }
    } else {
      updatedItems.push(newItem);
    }

    setItems(updatedItems);

    setNewName('');
    setNewBrand('');
    setNewModel('');
    setNewManufacturer('');
    setNewSpec('');
    setNewRemark('');
    setNewQty(1);
    setNewUnit('项');
    setNewPrice(0);
    setNewParentItem('');
    setIsAdding(false);

    saveCostAnalysis(updatedItems);
  };

  // 删除某项费用分项
  const handleDeleteItem = (indexToDelete: number) => {
    const deletingIndices = new Set(getCostSubtreeIndices(items, indexToDelete));
    const targetItem = items[indexToDelete];
    const updatedItems = items.filter((_, idx) => !deletingIndices.has(idx));
    setItems(updatedItems);
    if (editingIndex !== null && deletingIndices.has(editingIndex)) {
      setEditingKey(null);
      setEditingIndex(null);
    }
    if (targetItem?.node_id) {
      setExpandedRowKeys((keys) => keys.filter((key) => key !== targetItem.node_id));
    }
    saveCostAnalysis(updatedItems);
    message.success(
      deletingIndices.size > 1
        ? `已删除「${targetItem?.name || '当前节点'}」及其 ${deletingIndices.size - 1} 个子项。`
        : `已删除「${targetItem?.name || '当前节点'}」。`,
      3,
    );
  };

  // 持久化保存到后端
  const saveCostAnalysis = async (currentItems: any[]) => {
    // 记录本次本地编辑的结构，服务端回写相同结构时不折叠当前视图。
    lastLocalItemsFingerprintRef.current = getCostStructureFingerprint(currentItems);
    if (!documentId) return;

    setIsSaving(true);
    setSaveMessage(null);

    try {
      const baseUrl = API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/analysis/${documentId}/cost-analysis`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          items: currentItems.map(item => ({
            node_id: normalizeCostText(item.node_id) || null,
            parent_node_id: normalizeCostText(item.parent_node_id) || null,
            sort_order: item.sort_order ?? 0,
            item_code: normalizeCostText(item.item_code) || null,
            name: normalizeCostText(item.name),
            spec_requirement: normalizeCostText(item.spec_requirement),
            qty: item.qty !== null && item.qty !== undefined ? item.qty : 1,
            unit: normalizeCostText(item.unit) || '项',
            ref_price: item.ref_price || 0,
            matched_name: normalizeCostText(item.matched_name || item.name),
            matched_brand: normalizeCostText(item.matched_brand || item.brand),
            matched_model: normalizeCostText(item.matched_model || item.model),
            matched_manufacturer: normalizeCostText(item.matched_manufacturer || item.manufacturer),
            brand: normalizeCostText(item.brand || item.matched_brand),
            model: normalizeCostText(item.model || item.matched_model),
            manufacturer: normalizeCostText(item.manufacturer || item.matched_manufacturer),
            key_parameters: normalizeCostTextList(item.key_parameters),
            brand_requirements: normalizeCostText(item.brand_requirements || item.brand),
            match_quality: normalizeCostText(item.match_quality) || '手动添加',
            warning: normalizeCostText(item.warning),
            comparison_note: normalizeCostText(item.comparison_note),
            remark: normalizeCostText(item.remark),
            parent_item: normalizeCostText(item.parent_item) || null,
            root_item: normalizeCostText(item.root_item) || null,
            tree_level: item.tree_level || 1,
            per_set_qty: item.per_set_qty || item.per_set_quantity || null,
            per_set_quantity: item.per_set_quantity || item.per_set_qty || null,
            section_name: normalizeSectionName(item.section_name),
            part_name: normalizeCostText(item.part_name) || null,
            group_path: normalizeCostTextList(item.group_path),
            source_table_index: item.source_table_index ?? null,
            grouping_mode: normalizeCostGroupingMode(item.grouping_mode),
            is_parent_modified: Boolean(item.is_parent_modified),
            is_child_modified: Boolean(item.is_child_modified),
            is_custom_added: Boolean(item.is_custom_added),
            pricing_mode: normalizeCostText(item.pricing_mode) || null,
            raw_ref_price: item.raw_ref_price !== undefined ? item.raw_ref_price : null,
            raw_name: normalizeCostText(item.raw_name) || null,
            raw_brand: normalizeCostText(item.raw_brand) || null,
            raw_model: normalizeCostText(item.raw_model) || null,
            raw_manufacturer: normalizeCostText(item.raw_manufacturer) || null,
            raw_spec: normalizeCostText(item.raw_spec) || null,
            raw_qty: item.raw_qty !== undefined ? item.raw_qty : null,
            raw_unit: normalizeCostText(item.raw_unit) || null,
            raw_match_quality: normalizeCostText(item.raw_match_quality) || null
          })),
          analysis_summary: normalizeCostText(costAnalysis.analysis_summary) || '已手动调整 BOM 成本报价项与指导单价。'
        })
      });

      const result = await response.json();
      if (response.ok && result.code === 200) {
        const updatedData = result.data || {};
        const newTotalCost = updatedData.total_cost !== undefined ? Number(updatedData.total_cost) : realTimeTotalCost;
        const formattedTotal = `¥${newTotalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        
        let statusText = '';
        let msgType: 'success' | 'warning' | 'error' = 'success';
        
        if (effectiveLimitAmount && effectiveLimitAmount > 0) {
          const diff = Number((newTotalCost - effectiveLimitAmount).toFixed(2));
          const ratio = Number(((newTotalCost / effectiveLimitAmount) * 100).toFixed(1));
          
          if (newTotalCost > effectiveLimitAmount) {
            msgType = 'error';
            statusText = `已超出${limitTypeLabel}！当前预估总价 ${formattedTotal}，超出限额 ¥${diff.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}（超额 ${(ratio - 100).toFixed(1)}%）`;
            message.error(`🚨 最新报价已保存！当前总价 ${formattedTotal}，已超出${limitTypeLabel} ¥${diff.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}（超额 ${(ratio - 100).toFixed(1)}%，存在废标风险）`, 5);
          } else if (ratio >= 90) {
            msgType = 'warning';
            const remain = (effectiveLimitAmount - newTotalCost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            statusText = `接近${limitTypeLabel}！当前预估总价 ${formattedTotal}，使用率 ${ratio}%（剩余可用额度 ¥${remain}）`;
            message.warning(`⚠️ 最新报价已保存！当前总价 ${formattedTotal}，接近${limitTypeLabel}（使用率 ${ratio}%，剩余额度 ¥${remain}）`, 4);
          } else {
            msgType = 'success';
            const remain = (effectiveLimitAmount - newTotalCost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            statusText = `在${limitTypeLabel}内可控！当前预估总价 ${formattedTotal}，使用率 ${ratio}%（剩余可用额度 ¥${remain}）`;
            message.success(`✓ 最新报价已保存！当前总价 ${formattedTotal}，在${limitTypeLabel}内安全可控`, 3);
          }
        } else {
          statusText = `最新报价已保存落盘！当前预估总成本为 ${formattedTotal}`;
          message.success(`✓ 最新报价已保存！当前预估总成本 ${formattedTotal}`, 3);
        }

        setSaveMessage({
          type: msgType === 'error' ? 'error' : 'success',
          text: statusText
        });

        if (onCostUpdated) {
          onCostUpdated(result.data);
        }
      } else {
        const errText = result.detail || result.message || '保存失败';
        setSaveMessage({ type: 'error', text: errText });
        message.error(`保存失败: ${errText}`);
      }
    } catch (err: any) {
      setSaveMessage({ type: 'error', text: `网络或保存异常: ${err.message}` });
      message.error(`网络异常: ${err.message}`);
    } finally {
      setIsSaving(false);
      setTimeout(() => setSaveMessage(null), 5000);
    }
  };

  const hasItems = items.length > 0;
  const hasCostData = hasItems && !isEquipmentOnly;
  const moveParentOptions = React.useMemo(() => {
    if (!movingNode) return [];
    const forbiddenIds = new Set(
      getCostSubtreeIndices(items, movingNode.originalIndex)
        .map((index) => normalizeCostText(items[index]?.node_id).trim())
        .filter(Boolean),
    );
    return [
      { label: '顶层标的物（无父项）', value: '' },
      ...flattenCostTreeNodes(treeData)
        .filter((node) => node.node_id && !forbiddenIds.has(node.node_id))
        .map((node) => ({
          label: `${'　'.repeat(Math.max(0, (node.tree_level || 1) - 1))}${node.name} (L${node.tree_level || 1})`,
          value: node.node_id as string,
        })),
    ];
  }, [items, movingNode, treeData]);

  // 按当前清单中真实出现的操作按钮数量计算固定列的最低宽度，避免无条件预留 200px。
  const actionColumnMinimumWidth = React.useMemo(
    () => getCostTableActionMinimumWidth(flattenCostTreeNodes(treeData)),
    [treeData],
  );

  /** 应用用户拖拽后的列宽，并阻止列宽小于对应编辑控件的最低可用尺寸。 */
  const handleColumnResize = (columnKey: CostTableColumnKey, nextWidth: number) => {
    const minimumWidth = columnKey === 'action' ? actionColumnMinimumWidth : undefined;
    const normalizedWidth = normalizeCostTableColumnWidth(
      columnKey,
      nextWidth,
      minimumWidth,
    );
    setColumnWidths((previousWidths) => {
      if (previousWidths[columnKey] === normalizedWidth) return previousWidths;
      return { ...previousWidths, [columnKey]: normalizedWidth };
    });
  };

  /** 读取列宽覆盖值，并为每个表头生成统一的拖拽配置。 */
  const getColumnWidth = (columnKey: CostTableColumnKey, defaultWidth: number): number =>
    Math.max(
      columnWidths[columnKey] || defaultWidth,
      columnKey === 'action'
        ? actionColumnMinimumWidth
        : COST_TABLE_COLUMN_MIN_WIDTHS[columnKey] || 80,
    );
  const getResizableHeaderCellProps = (
    columnKey: CostTableColumnKey,
    defaultWidth: number,
  ) => ({
    width: getColumnWidth(columnKey, defaultWidth),
    onResize: (nextWidth: number) => handleColumnResize(columnKey, nextWidth),
  });

  // Ant Design 列配置
  const columns: ColumnsType<CostItemNode> = [
    {
      title: '标的/设备名称 & 标书规格',
      dataIndex: 'name',
      key: 'name',
      // 名称与原文说明需要换行展示，保留可读性但不再占用过宽空间。
      width: getColumnWidth('name', 300),
      onHeaderCell: () => getResizableHeaderCellProps('name', 300),
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const keyParams = Array.isArray(record.key_parameters) ? record.key_parameters : [];
        const isManual = record.match_quality === '手动添加' || record.is_custom_added;
        const isManualEdit = record.match_quality === '手动修改';
        // 生效的父项自定义统价：自身必须是成套父项，且【未被更上层祖先统价锁定】
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent') && !record.isLockedByParent;
        const level = record.tree_level || 1;
        const visibleGroupingMode = inferCostItemGroupingMode(record);
        const internalGroupDisplayText = getCostInternalGroupDisplayText(record, selectedPart);
        // 严格 3 色循环阶梯：4 复用 1(蓝)、5 复用 2(靛)、6 复用 3(天蓝)...
        const colorTier = (((level - 1) % 3) + 1);

        return (
          <div
            className={`py-1.5 rounded-lg transition-colors ${dragOverNodeId === record.node_id ? 'bg-blue-100/70 ring-2 ring-blue-300' : ''} ${dragOverNodeId === record.node_id && dragOverPlacement === 'before' ? 'border-t-4 border-blue-500' : ''} ${dragOverNodeId === record.node_id && dragOverPlacement === 'after' ? 'border-b-4 border-blue-500' : ''} ${draggingNodeId === record.node_id ? 'opacity-50' : ''}`}
            onDragOver={(event) => handleDragOver(event, record)}
            onDrop={(event) => handleDrop(event, record)}
          >
            {/* 多级 BOM 层级与总成标识 */}
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              {!isEditing && (
                <span
                  draggable
                  onDragStart={(event) => handleDragStart(event, record)}
                  onDragEnd={handleDragEnd}
                  className="inline-flex items-center justify-center w-6 h-6 rounded-md border border-slate-300 bg-white text-slate-500 text-sm font-black cursor-grab active:cursor-grabbing select-none hover:border-blue-400 hover:text-blue-600"
                  title="拖拽调整顺序或父子关系"
                  aria-label={`拖拽${record.name}调整顺序或父子关系`}
                >
                  ⋮⋮
                </span>
              )}
              {record.isParent ? (
                isParentCustom ? (
                  <span className="text-xs text-purple-950 bg-purple-100/90 px-2.5 py-1 rounded-xl border border-purple-300 font-bold shadow-2xs inline-flex items-center gap-1.5">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-purple-600 text-white font-mono font-black">L{level}</span>
                    <span>🏷️ {level === 1 ? '成套主标的 (自定义统价)' : `${level}级成套总成 (自定义统价)`} (含 {record.childCount} 项)</span>
                  </span>
                ) : colorTier === 1 ? (
                  <span className="text-xs text-blue-950 bg-blue-100/90 px-2.5 py-1 rounded-xl border border-blue-300 font-bold shadow-2xs inline-flex items-center gap-1.5">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-blue-600 text-white font-mono font-black">L{level}</span>
                    <span>📦 {level === 1 ? '一级成套主标的' : `${level}级成套总成`} (含 {record.childCount} 项)</span>
                  </span>
                ) : colorTier === 2 ? (
                  <span className="text-xs text-indigo-950 bg-indigo-100/90 px-2.5 py-1 rounded-xl border border-indigo-300 font-bold shadow-2xs inline-flex items-center gap-1.5">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-indigo-600 text-white font-mono font-black">L{level}</span>
                    <span>📑 {level}级成套总成 (含 {record.childCount} 项)</span>
                  </span>
                ) : (
                  <span className="text-xs text-sky-950 bg-sky-100/90 px-2.5 py-1 rounded-xl border border-sky-300 font-bold shadow-2xs inline-flex items-center gap-1.5">
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-600 text-white font-mono font-black">L{level}</span>
                    <span>🧩 {level}级部件总成 (含 {record.childCount} 项)</span>
                  </span>
                )
              ) : (
                colorTier === 1 ? (
                  level === 1 ? (
                    <span className="text-[11px] text-slate-700 bg-slate-100 px-2 py-0.5 rounded-lg border border-slate-200 font-bold inline-flex items-center gap-1 shadow-2xs">
                      <span className="text-[10px] px-1 py-0.2 rounded bg-slate-500 text-white font-mono font-bold">L1</span>
                      <span>独立设备主项</span>
                    </span>
                  ) : (
                    <span className="text-[11px] text-blue-900 bg-blue-50 px-2 py-0.5 rounded-lg border border-blue-200 font-bold inline-flex items-center gap-1 shadow-2xs">
                      <span className="text-[10px] px-1 py-0.2 rounded bg-blue-600 text-white font-mono font-bold">L{level}</span>
                      <span>{level}级细分子项</span>
                    </span>
                  )
                ) : colorTier === 2 ? (
                  <span className="text-[11px] text-indigo-900 bg-indigo-50 px-2 py-0.5 rounded-lg border border-indigo-200 font-bold inline-flex items-center gap-1 shadow-2xs">
                    <span className="text-[10px] px-1 py-0.2 rounded bg-indigo-600 text-white font-mono font-bold">L{level}</span>
                    <span>{level}级分项</span>
                  </span>
                ) : (
                  <span className="text-[11px] text-sky-900 bg-sky-50 px-2 py-0.5 rounded-lg border border-sky-200 font-bold inline-flex items-center gap-1 shadow-2xs">
                    <span className="text-[10px] px-1 py-0.2 rounded bg-sky-600 text-white font-mono font-bold">L{level}</span>
                    <span>{level}级元器件</span>
                  </span>
                )
              )}

              {/* 所属母项提示标签 */}
              {!record.isParent && record.parent_item && (
                <span className={`text-[11px] px-2 py-0.5 rounded-md border font-medium inline-flex items-center gap-1 ${
                  colorTier === 1 ? 'text-blue-800 bg-blue-50/90 border-blue-200' :
                  colorTier === 2 ? 'text-indigo-800 bg-indigo-50/90 border-indigo-200' :
                  'text-sky-800 bg-sky-50/90 border-sky-200'
                }`}>
                  <span>↳ 所属:</span>
                  <strong className="font-bold">{record.parent_item}</strong>
                </span>
              )}
            </div>

            {/* 所属分项提示徽章：与表内分类是两个独立维度，必要时同时展示。 */}
            {record.section_name && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[11px] text-cyan-800 bg-cyan-50/90 px-2.5 py-0.5 rounded-md inline-flex items-center gap-1 font-bold border border-cyan-300/80 shadow-2xs">
                  <span>📍 所属分项: <strong className="font-extrabold text-cyan-950">{record.section_name}</strong></span>
                </span>
              </div>
            )}

            {/* 表内 BOQ 分组只作为分类路径展示，不把分类标题误当成 BOM 父项。 */}
            {visibleGroupingMode === 'internal' && internalGroupDisplayText && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[11px] text-violet-800 bg-violet-50/90 px-2.5 py-0.5 rounded-md inline-flex items-center gap-1 font-bold border border-violet-300/80 shadow-2xs">
                  <span>🗂️ <strong className="font-extrabold text-violet-950">
                    {internalGroupDisplayText}
                  </strong></span>
                  {!record.isInternalFilterContextNode && (
                    <Tooltip title="编辑表内分组">
                      <Button
                        type="text"
                        size="small"
                        aria-label={`编辑表内分组${internalGroupDisplayText}`}
                        icon={<EditOutlined className="text-violet-600 hover:text-violet-900" />}
                        onClick={(event) => {
                          event.stopPropagation();
                          handleOpenGroupEdit(record);
                        }}
                        className="!h-5 !w-5 !p-0"
                      />
                    </Tooltip>
                  )}
                </span>
              </div>
            )}

            {/* 原本没有表内分组的节点提供设置入口，保留已有表外分项不变。 */}
            {!hasBomGroupContext(record) && !record.isInternalFilterContextNode && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <Button
                  type="link"
                  size="small"
                  icon={<PlusOutlined />}
                  aria-label={`为${record.name}设置表内分组`}
                  onClick={(event) => {
                    event.stopPropagation();
                    handleOpenGroupAssign(record);
                  }}
                  className="!p-0 !h-5 text-violet-700 hover:text-violet-900 font-bold text-[11px]"
                >
                  设置表内分组
                </Button>
              </div>
            )}

            {/* 设备名称与说明编辑态 */}
            {isEditing ? (
              <div className="space-y-1.5 py-1">
                <div>
                  <label className="text-[10px] font-bold text-slate-500 block mb-0.5">标的/设备名称：</label>
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    size="small"
                    className="font-bold text-sm"
                    placeholder="设备/分项名称"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold text-slate-500 block mb-0.5">内容说明：</label>
                  <Input.TextArea
                    value={editSpec}
                    onChange={(e) => setEditSpec(e.target.value)}
                    size="small"
                    rows={2}
                    className="text-xs"
                    placeholder="内容说明（如规格参数、服务范围或标书要求）"
                  />
                </div>
              </div>
            ) : (
              <div>
                <div className={`flex items-center gap-1.5 mb-1 ${
                  record.isParent && colorTier === 1
                    ? 'text-base font-black text-slate-900' 
                    : record.isParent && colorTier === 2
                      ? 'text-sm font-black text-slate-900'
                      : record.isParent
                        ? 'text-sm font-black text-slate-800'
                        : colorTier === 1 && level > 1
                          ? 'text-sm font-bold text-slate-800'
                          : colorTier === 2 
                            ? 'text-sm font-bold text-slate-800' 
                            : colorTier === 3
                              ? 'text-sm font-semibold text-slate-800'
                              : 'text-sm font-medium text-slate-700'
                }`}>
                  {record.item_code && (
                    <span className={`font-mono text-xs px-1.5 py-0.2 rounded border font-semibold ${
                      colorTier === 1 ? 'bg-blue-50 text-blue-800 border-blue-200' :
                      colorTier === 2 ? 'bg-indigo-50 text-indigo-800 border-indigo-200' :
                      colorTier === 3 ? 'bg-sky-50 text-sky-800 border-sky-200' :
                      'bg-slate-100 text-slate-700 border-slate-200'
                    }`}>
                      #{record.item_code}
                    </span>
                  )}
                  <span>{record.name}</span>
                  {record.isLockedByParent ? (
                    <span className="bg-slate-100 text-slate-500 border border-slate-300 text-[10px] px-1.5 py-0.5 rounded font-bold ml-1" title="父项已启用自定义统价，子项已锁定修改">
                      🔒 父项统价锁定
                    </span>
                  ) : record.is_custom_added ? (
                    <span className="bg-emerald-50 text-emerald-600 border border-emerald-200 text-[10px] px-1.5 py-0.5 rounded font-bold ml-1">
                      ✨ 新增子项
                    </span>
                  ) : (isManual || isManualEdit) ? (
                    <span className="bg-purple-50 text-purple-600 border border-purple-200 text-[10px] px-1.5 py-0.5 rounded font-bold ml-1">
                      {isManual ? '手动新增' : '手动修改'}
                    </span>
                  ) : null}
                </div>

                {/* 标书原文/技术要求 */}
                {record.spec_requirement && (
                  <div className="text-xs text-slate-600 leading-relaxed font-normal p-2.5 rounded-xl border border-slate-200/80 bg-slate-50/70 my-1" title={record.spec_requirement}>
                    <span className="text-[10px] font-bold text-slate-400 block mb-0.5">📄 标书原文/说明：</span>
                    {record.spec_requirement}
                  </div>
                )}
              </div>
            )}

            {/* 关键参数标签 */}
            {keyParams.length > 0 && !isEditing && (
              <div className="flex flex-wrap gap-1 mt-1">
                {keyParams.map((param: string, pIdx: number) => (
                  <span key={pIdx} className="bg-amber-50 text-amber-700 text-[10px] px-1.5 py-0.5 rounded border border-amber-200/60 font-medium">
                    {param}
                  </span>
                ))}
              </div>
            )}

            {/* 指定品牌/产地 */}
            {record.brand_requirements && !isEditing && (
              <div className="text-[11px] text-slate-400 mt-1 italic">
                要求的品牌/产地: {record.brand_requirements}
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: '匹配设备 & 品牌/规格/厂商',
      dataIndex: 'matched_name',
      key: 'matched_name',
      // 匹配编辑区包含品牌、型号、厂家三个输入框，压缩到可用的紧凑宽度。
      width: getColumnWidth('matched_name', 250),
      onHeaderCell: () => getResizableHeaderCellProps('matched_name', 250),
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !record.isRollupPrice && !record.is_parent_modified);
        const isManual = record.match_quality === '手动添加';
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent') && !record.isLockedByParent;

        if (isEditing) {
          return (
            <div className="space-y-1.5 py-1.5 bg-amber-50/70 p-2.5 rounded-xl border border-amber-300/80 shadow-2xs">
              <div className="text-[11px] font-bold text-amber-900 flex items-center gap-1">
                <span>✏️</span>
                <span>投标品牌、型号与厂商编辑：</span>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-bold block mb-0.5">品牌：</label>
                <Input
                  value={editBrand}
                  onChange={(e) => setEditBrand(e.target.value)}
                  placeholder="例如: 华为 / 天合光能 / 自定义"
                  size="small"
                  className="text-xs font-medium"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-bold block mb-0.5">规格/型号：</label>
                <Input
                  value={editModel}
                  onChange={(e) => setEditModel(e.target.value)}
                  placeholder="例如: 635Wp / SUN2000-110KTL"
                  size="small"
                  className="text-xs font-medium"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 font-bold block mb-0.5">生产厂家：</label>
                <Input
                  value={editManufacturer}
                  onChange={(e) => setEditManufacturer(e.target.value)}
                  placeholder="例如: 华为技术有限公司 / 某制造厂"
                  size="small"
                  className="text-xs font-medium"
                />
              </div>
            </div>
          );
        }

        if (isParentCustom) {
          const displayBrand = record.matched_brand || record.brand;
          const displayModel = record.matched_model || record.model;
          const displayMfg = record.matched_manufacturer || record.manufacturer;

          return (
            <div className="space-y-1.5 text-xs py-1">
              <div className="font-bold text-purple-900 flex items-center gap-1.5">
                <span className="text-purple-600 font-bold">🏷️</span>
                <span className="text-sm text-slate-900 font-bold">成套总成 / 用户自定义统价</span>
              </div>
              <div className="text-[11px] bg-purple-50/95 text-purple-950 p-2.5 rounded-xl border border-purple-200/90 leading-relaxed font-medium shadow-2xs">
                <span className="font-bold block mb-0.5 text-purple-800">📋 自定义定价说明：</span>
                已直接自定义成套设备整体价格，下属 <strong className="text-purple-950 font-black">{record.childCount || 0}</strong> 个子项已被锁定。如需修改子项，请点击右侧「重置父项」。
              </div>
              {(displayBrand || displayModel || displayMfg) && (
                <div className="flex flex-wrap gap-1 text-[11px] mt-1">
                  {displayBrand && <span className="bg-purple-50 text-purple-700 px-2 py-0.5 rounded-md font-medium border border-purple-100">品牌: {displayBrand}</span>}
                  {displayModel && <span className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-md font-medium border border-indigo-100">型号: {displayModel}</span>}
                  {displayMfg && <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">厂商: {displayMfg}</span>}
                </div>
              )}
            </div>
          );
        }

        if (record.isLockedByParent && record.isParent) {
          const displayBrand = record.matched_brand || record.brand;
          const displayModel = record.matched_model || record.model;
          const displayMfg = record.matched_manufacturer || record.manufacturer;

          return (
            <div className="space-y-1.5 text-xs py-1">
              <div className="font-bold text-slate-800 flex items-center gap-1.5">
                <span className="text-slate-500 font-bold">🔒</span>
                <span className="text-sm text-slate-900 font-bold">{record.name} (已统入上级成套价)</span>
              </div>
              <div className="text-[11px] bg-slate-50 text-slate-600 p-2.5 rounded-xl border border-slate-200 leading-relaxed font-medium shadow-2xs">
                <span className="font-bold block mb-0.5 text-slate-700">🔒 统价锁定说明：</span>
                上级成套设备已启用统一总价，当前成套分项及下属部件均已纳入上级统价范围，无需单独计价。
              </div>
              {(displayBrand || displayModel || displayMfg) && (
                <div className="flex flex-wrap gap-1 text-[11px] mt-1">
                  {displayBrand && <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">品牌: {displayBrand}</span>}
                  {displayModel && <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">型号: {displayModel}</span>}
                  {displayMfg && <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">厂商: {displayMfg}</span>}
                </div>
              )}
            </div>
          );
        }

        if (record.isRollupPrice) {
          if (record.isPartialRollup) {
            return (
              <div className="space-y-1.5 text-xs py-1">
                <div className="font-bold text-amber-800 flex items-center gap-1.5">
                  <span className="text-amber-500 font-bold">📦</span>
                  <span className="text-sm text-slate-900 font-bold">成套总成 / 子项部分汇总</span>
                </div>
                <div className="text-[11px] bg-amber-50/95 text-amber-900 p-2.5 rounded-xl border border-amber-300/90 leading-relaxed font-medium shadow-2xs">
                  <span className="font-bold block mb-0.5 text-amber-800">⚠️ 部分测算提示：</span>
                  下属共 <strong className="text-amber-950 font-black">{record.childCount || 0}</strong> 个分项中，已汇总 <strong className="text-emerald-700 font-black">{record.rollupChildCount || 0}</strong> 项价格，尚有 <strong className="text-rose-600 font-black">{record.missingChildPriceCount || 0}</strong> 项未定价（暂按 0 元累加），建议展开子项补齐单价。
                </div>
              </div>
            );
          }

          return (
            <div className="space-y-1.5 text-xs py-1">
              <div className="font-bold text-slate-800 flex items-center gap-1.5">
                <span className="text-indigo-600 font-bold">📦</span>
                <span className="text-sm text-slate-900 font-bold">成套总成 / 子项全部汇总</span>
              </div>
              <div className="text-[11px] bg-indigo-50/95 text-indigo-900 p-2 rounded-xl border border-indigo-200/90 leading-relaxed font-medium shadow-2xs">
                <span className="font-bold block mb-0.5 text-indigo-800">📊 成套测算说明：</span>
                标书无整体打包库价，已根据下属全部 <strong className="text-indigo-950 font-black">{record.childCount || 0}</strong> 个分项/元器件单价与工程量自底向上完整汇总测算。
              </div>
            </div>
          );
        }

        if (!isUnmatched || isManual || currentRefPrice > 0) {
          const displayBrand = record.matched_brand || record.brand;
          const displayModel = record.matched_model || record.model;
          const displayMfg = record.matched_manufacturer || record.manufacturer;

          return (
            <div className="space-y-1.5 text-xs py-1">
              <div className="font-bold text-slate-800 flex items-center gap-1.5">
                <span className="text-emerald-500 font-bold">✓</span>
                <span className="text-sm text-slate-900 font-bold">{record.matched_name || record.name}</span>
              </div>
              <div className="flex flex-wrap gap-1 text-[11px]">
                {displayBrand && (
                  <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded-md font-medium border border-blue-100">
                    品牌: {displayBrand}
                  </span>
                )}
                {displayModel && (
                  <span className="bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-md font-medium border border-indigo-100">
                    型号: {displayModel}
                  </span>
                )}
                {displayMfg && (
                  <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">
                    厂商: {displayMfg}
                  </span>
                )}
              </div>
              {record.comparison_note && (() => {
                const note = record.comparison_note;
                const isSpecDiff = note.includes("规格不同") || note.includes("量纲不一") || note.includes("差异") || note.includes("仅参考") || note.includes("不一致") || note.includes("偏离");
                const isBundled = note.includes("包含") || note.includes("打包") || note.includes("不重复") || note.includes("统价");
                
                if (isSpecDiff) {
                  return (
                    <div className="text-[11px] bg-amber-50/95 text-amber-900 p-2 rounded-xl border border-amber-300/90 leading-relaxed font-medium shadow-2xs">
                      <span className="font-bold block mb-0.5 text-amber-800">⚠️ 规格存在差异（仅供参考）：</span>
                      {note}
                    </div>
                  );
                }
                if (isBundled) {
                  return (
                    <div className="text-[11px] bg-blue-50/90 text-blue-900 p-2 rounded-xl border border-blue-200/80 leading-relaxed font-medium shadow-2xs">
                      <span className="font-bold block mb-0.5 text-blue-800">📦 成套打包说明：</span>
                      {note}
                    </div>
                  );
                }
                return (
                  <div className="text-[11px] bg-emerald-50/80 text-emerald-800 p-2 rounded-xl border border-emerald-200/70 leading-relaxed font-medium shadow-2xs">
                    <span className="font-bold block mb-0.5 text-emerald-700">🔍 对标分析说明：</span>
                    {note}
                  </div>
                );
              })()}
            </div>
          );
        }

        return (
          <div className="space-y-1.5 text-xs py-1">
            <div className="text-xs text-rose-600 bg-rose-50/90 px-2.5 py-1.5 rounded-xl border border-rose-200/80 font-semibold flex items-center gap-1.5 shadow-2xs">
              <span className="text-rose-500 font-bold">⚠️</span>
              <span>{record.warning || '未在价格库中找到参考价'}</span>
            </div>
            {record.comparison_note && (
              <div className="text-[11px] bg-slate-50 text-slate-600 p-2 rounded-xl border border-slate-200 leading-relaxed">
                {record.comparison_note}
              </div>
            )}
          </div>
        );
      },
    },
    {
      title: '置信度',
      dataIndex: 'match_quality',
      key: 'match_quality',
      width: getColumnWidth('match_quality', 100),
      onHeaderCell: () => getResizableHeaderCellProps('match_quality', 100),
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const isExact = record.match_quality === '精准匹配';
        const isManual = record.match_quality === '手动添加';
        const isManualEdit = record.match_quality === '手动修改';
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent') && !record.isLockedByParent;
        const isRollup = (record.isRollupPrice || record.match_quality === '成套汇总' || record.match_quality === '子项汇总') && !isParentCustom && !record.isLockedByParent;
        const note = record.comparison_note || '';
        const isSpecDiff = note.includes("规格不同") || note.includes("量纲不一") || note.includes("差异") || note.includes("仅参考") || note.includes("不一致") || note.includes("偏离");
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !isRollup && !isParentCustom);

        if (isEditing) {
          return <Tag color="processing">修改中</Tag>;
        }
        if (record.isLockedByParent) {
          return <Tag color="default" className="text-slate-500 bg-slate-100 border-slate-300 font-medium">已统入父项</Tag>;
        }
        if (isParentCustom) {
          return <Tag color="purple" className="font-bold border-purple-300">父项自定义</Tag>;
        }
        if (isRollup) {
          if (record.isPartialRollup) {
            return (
              <Tag color="warning" className="font-bold border-amber-300">
                部分汇总 (缺{record.missingChildPriceCount || 1}项)
              </Tag>
            );
          }
          return <Tag color="cyan" className="font-bold border-cyan-300">成套汇总</Tag>;
        }
        if (isExact) {
          return <Tag color="success">精准匹配</Tag>;
        }
        if (isManual || isManualEdit) {
          return <Tag color="purple">{isManual ? '手动添加' : '手动修改'}</Tag>;
        }
        if (isSpecDiff && !isUnmatched) {
          return <Tag color="warning">{record.match_quality ? `${record.match_quality} (差异)` : '规格差异'}</Tag>;
        }
        if (!isUnmatched) {
          return <Tag color="blue">{record.match_quality || '库匹配'}</Tag>;
        }
        return <Tag>未匹配</Tag>;
      },
    },
    {
      title: '数量/单位',
      dataIndex: 'qty',
      key: 'qty',
      // 为行内数量和单位输入框预留足够空间，避免单位控件被表格单元格裁剪。
      width: getColumnWidth('qty', quantityColumnWidth),
      onHeaderCell: () => getResizableHeaderCellProps('qty', quantityColumnWidth),
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;

        if (isEditing) {
          return (
            <div className="flex items-center gap-1">
              <InputNumber
                min={0.01}
                step="any"
                controls={false}
                value={editQty}
                onChange={(v) => setEditQty(v || 1)}
                size="small"
                className="quantity-input shrink-0 text-center font-bold"
                style={{ width: editQtyInputWidth }}
              />
              <Input
                value={editUnit}
                onChange={(e) => setEditUnit(e.target.value)}
                placeholder="单位"
                size="small"
                className="shrink-0 text-center"
                style={{ width: editUnitInputWidth }}
              />
            </div>
          );
        }

        const hasQty = record.qty !== null && record.qty !== undefined;
        const hasUnit = !!record.unit;

        if (!hasQty && !hasUnit) {
          return (
            <div className="flex flex-col items-center">
              <span className="text-slate-300 font-medium text-xs">--</span>
            </div>
          );
        }

        const displayUnit = record.unit || '';
        const qtyText = hasQty ? (hasUnit ? `${record.qty} ${displayUnit}` : `${record.qty}`) : displayUnit;

        return (
          <div className="flex flex-col items-center">
            <span className="font-bold text-slate-700 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200/60 inline-block text-xs">
              {qtyText}
            </span>
            {record.per_set_qty && Number(record.per_set_qty) !== Number(record.qty) && (
              <span className="text-[10px] text-slate-400 mt-0.5 text-center font-medium" title={`单套设备定额: ${record.per_set_qty} ${displayUnit}`}>
                (单套 {record.per_set_qty} {displayUnit})
              </span>
            )}
          </div>
        );
      },
    },
    {
      title: '参考单价 (元)',
      dataIndex: 'ref_price',
      key: 'ref_price',
      width: getColumnWidth('ref_price', 125),
      onHeaderCell: () => getResizableHeaderCellProps('ref_price', 125),
      align: 'right',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent') && !record.isLockedByParent;

        if (isEditing) {
          return (
            <div className="flex flex-col items-end">
              <InputNumber
                min={0}
                step="any"
                controls={false}
                prefix="¥"
                value={editPrice}
                onChange={(v) => setEditPrice(v || 0)}
                size="small"
                className="number-input w-28 font-bold"
              />
              {record.isParent && (
                <span className="text-[10px] text-purple-600 mt-0.5 font-bold flex items-center gap-0.5">
                  <span>✏️</span>
                  <span>自定义成套单价</span>
                </span>
              )}
            </div>
          );
        }

        if (record.isLockedByParent) {
          return (
            <div className="flex flex-col items-end">
              <span className="text-slate-400 font-normal text-xs">{currentRefPrice > 0 ? `¥${currentRefPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--'}</span>
              <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 mt-0.5 font-normal">
                已统入父项价
              </span>
            </div>
          );
        }

        if (isParentCustom && currentRefPrice > 0) {
          return (
            <div className="flex flex-col items-end">
              <span className="font-extrabold text-purple-700 text-sm">¥{currentRefPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              <span className="text-[10px] text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded border border-purple-200 mt-0.5 font-bold">
                父项自定义单价
              </span>
            </div>
          );
        }

        if (record.isRollupPrice && currentRefPrice > 0) {
          if (record.isPartialRollup) {
            return (
              <div className="flex flex-col items-end">
                <span className="font-extrabold text-amber-700 text-sm">¥{currentRefPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                <span className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200 mt-0.5 font-bold">
                  部分子项折合
                </span>
              </div>
            );
          }
          return (
            <div className="flex flex-col items-end">
              <span className="font-extrabold text-indigo-700 text-sm">¥{currentRefPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              <span className="text-[10px] text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-200 mt-0.5 font-bold">
                子项折合单价
              </span>
            </div>
          );
        }

        if (currentRefPrice > 0) {
          return <span className="font-bold text-slate-700">¥{currentRefPrice.toLocaleString()}</span>;
        }

        return (
          <div className="flex flex-col items-end">
            <span className="text-slate-400 font-normal text-xs">--</span>
            {record.parent_item && (record.comparison_note?.includes("包含") || record.comparison_note?.includes("打包") || record.comparison_note?.includes("不重复") || record.comparison_note?.includes("统价")) && (
              <span className="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/80 mt-0.5 font-bold">
                已含在成套价
              </span>
            )}
          </div>
        );
      },
    },
    {
      title: '成本小计',
      key: 'subtotal',
      width: getColumnWidth('subtotal', 125),
      onHeaderCell: () => getResizableHeaderCellProps('subtotal', 125),
      align: 'right',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentQty = isEditing ? editQty : (record.qty !== null && record.qty !== undefined ? Number(record.qty) : 1);
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const itemSubtotal = record.subtotal !== undefined ? record.subtotal : currentQty * currentRefPrice;
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent') && !record.isLockedByParent;

        if (record.isLockedByParent) {
          return (
            <div className="flex flex-col items-end">
              <span className="text-slate-400 font-normal text-xs">--</span>
              <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded border border-slate-200 mt-0.5 font-normal">
                已统入父项
              </span>
            </div>
          );
        }

        if (itemSubtotal > 0) {
          if (record.isParent) {
            return (
              <div className="flex flex-col items-end">
                <span className={`font-black text-sm whitespace-nowrap ${
                  isParentCustom ? 'text-purple-800' : (record.isPartialRollup ? 'text-amber-800' : 'text-indigo-800')
                }`}>
                  ¥{itemSubtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
                {isParentCustom ? (
                  <span className="text-[10px] font-bold px-1.5 py-0.2 rounded border bg-purple-50 text-purple-700 border-purple-200">
                    父项统定价总计
                  </span>
                ) : record.isRollupPrice ? (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                    record.isPartialRollup ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-indigo-50/90 text-indigo-600 border-indigo-200'
                  }`}>
                    {record.isPartialRollup ? '阶段小计 (待补全)' : '成套总计'}
                  </span>
                ) : null}
              </div>
            );
          }
          return (
            <span className="font-bold whitespace-nowrap text-blue-600">
              ¥{itemSubtotal.toLocaleString()}
            </span>
          );
        }

        return (
          <span className="text-slate-400 font-normal text-xs">--</span>
        );
      },
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      width: getColumnWidth('remark', 120),
      onHeaderCell: () => getResizableHeaderCellProps('remark', 120),
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;

        if (isEditing) {
          return (
            <Input.TextArea
              value={editRemark}
              onChange={(e) => setEditRemark(e.target.value)}
              size="small"
              rows={3}
              maxLength={500}
              showCount
              placeholder="例如：含套装价、含安装调试"
              className="text-xs"
            />
          );
        }

        return record.remark ? (
          <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap" title={record.remark}>
            {record.remark}
          </div>
        ) : (
          <span className="text-slate-300 text-xs">--</span>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      // 操作列不固定，配合横向滚动让用户可以查看整张 BOM 表的全部列。
      // 按当前清单最多一组操作按钮的实际占用设置宽度，避免产生无效空白。
      width: getColumnWidth('action', actionColumnMinimumWidth),
      onHeaderCell: () => getResizableHeaderCellProps('action', actionColumnMinimumWidth),
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;

        if (isEditing) {
          return (
            <div className="flex flex-nowrap items-center justify-center gap-0.5 whitespace-nowrap">
              <Tooltip title="保存修改">
                <Button
                  type="primary"
                  size="small"
                  icon={<CheckOutlined />}
                  onClick={() => handleSaveEdit(record)}
                  className="bg-emerald-600 hover:bg-emerald-700"
                />
              </Tooltip>
              <Tooltip title="取消编辑">
                <Button
                  size="small"
                  icon={<CloseOutlined />}
                  onClick={handleCancelEdit}
                />
              </Tooltip>
            </div>
          );
        }

        if (record.isParent) {
          const isParentModified = Boolean(record.is_parent_modified || record.pricing_mode === 'parent');
          const hasModifiedChildren = Boolean(record.hasModifiedChildren);
          const isLockedByParent = Boolean(record.isLockedByParent);
          // 名下子项是否有实际价格（由子项自底向上驱动）
          const hasPricedChildren = Boolean(record.hasPricedChildren || (record.subtotal && record.subtotal > 0 && record.isRollupPrice));
          // 父项自身是否有有效独立统价（非子项汇总计算得出）
          const hasParentSelfPrice = Boolean(Number(record.ref_price) > 0 && !record.isRollupPrice);
          const childCount = record.childCount || 1;

          return (
            <div className="flex flex-nowrap items-center justify-center gap-0.5 whitespace-nowrap">
              {/* 添加子项按钮 */}
              {isLockedByParent ? (
                <Tooltip title="所属成套设备已启用父项自定义统价，下属分项已锁定。如需添加子项，请先重置上级父项">
                  <Button
                    type="text"
                    size="small"
                    disabled
                    icon={<PlusCircleOutlined className="text-slate-300 cursor-not-allowed" />}
                  />
                </Tooltip>
              ) : hasParentSelfPrice ? (
                <Tooltip title="当前成套设备已设定统价，子项已锁定。如需添加子项，请先清空父项价格">
                  <Button
                    type="text"
                    size="small"
                    disabled
                    icon={<PlusCircleOutlined className="text-slate-300 cursor-not-allowed" />}
                  />
                </Tooltip>
              ) : (
                <Tooltip title="为此成套设备添加子标的物/分项">
                  <Button
                    type="text"
                    size="small"
                    icon={<PlusCircleOutlined className="text-blue-600 hover:text-blue-800" />}
                    onClick={() => handleOpenAddChildModal(record)}
                  />
                </Tooltip>
              )}

              <Tooltip title="新增同级标的物">
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined className="text-indigo-600 hover:text-indigo-800" />}
                  onClick={() => handleOpenAddSiblingModal(record)}
                />
              </Tooltip>

              <Tooltip title="修改父项归属">
                <Button
                  type="text"
                  size="small"
                  icon={<SwapOutlined className="text-slate-500 hover:text-blue-700" />}
                  onClick={() => handleOpenMoveParentModal(record)}
                />
              </Tooltip>

              {record.parent_node_id && (
                <Tooltip title="脱离当前父项并提升一级">
                  <Popconfirm
                    title={`确定将「${record.name}」脱离当前父项？`}
                    description="该节点及其全部子项将提升一级，与当前父节点保持同层。"
                    onConfirm={() => handleDetachFromParent(record)}
                    okText="确认脱离"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<UpOutlined className="text-amber-600 hover:text-amber-800" />}
                    />
                  </Popconfirm>
                </Tooltip>
              )}

              {/* 编辑父项按钮：若子项已有价格汇总，父项被互斥锁定，禁止直接修改 */}
              {isLockedByParent ? (
                <Tooltip title="所属成套设备已启用父项自定义定价，子项已锁定。如需修改，请先重置上级父项">
                  <Button
                    type="text"
                    size="small"
                    disabled
                    icon={<EditOutlined className="text-slate-300 cursor-not-allowed" />}
                  />
                </Tooltip>
              ) : hasPricedChildren ? (
                <Tooltip title={`当前成套价格由名下全部 ${childCount} 个子项汇总自动计算，禁止直接修改父项。如需直接指定成套统价，请先点击「清空子项价格」`}>
                  <Button
                    type="text"
                    size="small"
                    disabled
                    icon={<EditOutlined className="text-slate-300 cursor-not-allowed" />}
                  />
                </Tooltip>
              ) : (
                <Tooltip title="直接修改成套设备价格（保存后将作为成套统价，并锁定下属全部子项）">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined className={hasParentSelfPrice ? "text-purple-600 hover:text-purple-800" : "text-indigo-500 hover:text-indigo-700"} />}
                    onClick={() => handleStartEdit(record)}
                  />
                </Tooltip>
              )}

              {/* 清空父项价格按钮：成套设备自身有独立价格且未被上级锁定时显示，点击后清空父项价格并解锁所有子项 */}
              {hasParentSelfPrice && !isLockedByParent && (
                <Tooltip title={`清空成套设备价格，解除锁定并解锁名下全部 ${childCount} 个子项的修改价格功能`}>
                  <Popconfirm
                    title={`确定清空成套设备「${record.name}」的价格？`}
                    description={`将清空此父项独立定价，解除对名下全部 ${childCount} 个子项的锁定，允许分别修改子项价格，成套总价将由子项自动汇总得出。`}
                    onConfirm={() => handleClearParentPrice(record)}
                    okText="确定清空并解锁"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<UndoOutlined className="text-purple-600 hover:text-purple-800" />}
                    />
                  </Popconfirm>
                </Tooltip>
              )}

              {/* 清空子项价格按钮：当子项中有价格时显示，点击后清空名下所有子项价格，重新解锁成套设备直接统价 */}
              {hasPricedChildren && !isLockedByParent && (
                <Tooltip title={`清空名下全部 ${childCount} 个子项的价格，重新解锁成套设备直接统价`}>
                  <Popconfirm
                    title={`确定清空「${record.name}」名下全部 ${childCount} 个子项的价格？`}
                    description={`将清空名下全部 ${childCount} 个子项的价格（恢复为未定价），重新解锁成套设备直接修改价格的权限。`}
                    onConfirm={() => handleClearChildrenPrices(record)}
                    okText="确定清空子项"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<ReloadOutlined className="text-amber-600 hover:text-amber-800" />}
                    />
                  </Popconfirm>
                </Tooltip>
              )}

              {/* 删除整套设备 */}
              <Popconfirm
                title="确定移除此成套设备及下属分项？"
                onConfirm={() => handleDeleteItem(record.originalIndex)}
                okText="确定"
                cancelText="取消"
              >
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined className="text-slate-300 hover:text-rose-600" />}
                />
              </Popconfirm>
            </div>
          );
        }

        // 子项或独立项
        const isLockedByParent = Boolean(record.isLockedByParent);
        const isChildModified = Boolean(record.is_child_modified || record.match_quality === '手动修改');

        return (
          <div className="flex flex-nowrap items-center justify-center gap-0.5 whitespace-nowrap">
            {/* 任意节点都可以继续增加下级，支持从叶子节点扩展出多级 BOM。 */}
            <Tooltip title="在此标的物下新增子项">
              <Button
                type="text"
                size="small"
                icon={<PlusCircleOutlined className="text-blue-600 hover:text-blue-800" />}
                onClick={() => handleOpenAddChildModal(record)}
              />
            </Tooltip>
            <Tooltip title="新增同级标的物">
              <Button
                type="text"
                size="small"
                icon={<PlusOutlined className="text-indigo-600 hover:text-indigo-800" />}
                onClick={() => handleOpenAddSiblingModal(record)}
              />
            </Tooltip>
            <Tooltip title="修改父项归属">
              <Button
                type="text"
                size="small"
                icon={<SwapOutlined className="text-slate-500 hover:text-blue-700" />}
                onClick={() => handleOpenMoveParentModal(record)}
              />
            </Tooltip>
            {record.parent_node_id && (
              <Tooltip title="脱离当前父项并提升一级">
                <Popconfirm
                  title={`确定将「${record.name}」脱离当前父项？`}
                  description="该节点及其全部子项将提升一级，与当前父节点保持同层。"
                  onConfirm={() => handleDetachFromParent(record)}
                  okText="确认脱离"
                  cancelText="取消"
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<UpOutlined className="text-amber-600 hover:text-amber-800" />}
                  />
                </Popconfirm>
              </Tooltip>
            )}
            {isLockedByParent ? (
              <Tooltip title="所属成套设备已启用父项直接定价，下属所有子项已锁定。如需修改子项价格，请先在上方成套设备点击「清空父项价格」">
                <Button
                  type="text"
                  size="small"
                  disabled
                  icon={<EditOutlined className="text-slate-300 cursor-not-allowed" />}
                />
              </Tooltip>
            ) : (
              <Tooltip title="修改此项单价与数量">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined className="text-slate-400 hover:text-blue-600" />}
                  onClick={() => handleStartEdit(record)}
                />
              </Tooltip>
            )}

            {/* 单项重置按钮 */}
            {isChildModified && !isLockedByParent && (
              <Tooltip title="重置此项至初始对标状态">
                <Popconfirm
                  title={`确定重置「${record.name}」？`}
                  description="将恢复该项初始基线数据。"
                  onConfirm={() => handleResetSingleItem(record)}
                  okText="确定重置"
                  cancelText="取消"
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<UndoOutlined className="text-purple-600 hover:text-purple-800" />}
                  />
                </Popconfirm>
              </Tooltip>
            )}

            <Popconfirm
              title="确定移除此费用分项？"
              onConfirm={() => handleDeleteItem(record.originalIndex)}
              okText="确定"
              cancelText="取消"
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined className="text-slate-300 hover:text-rose-600" />}
              />
            </Popconfirm>
          </div>
        );
      },
    },
  ];

// 显式同步整张表的总宽度，为横向滚动提供稳定轨道，确保所有列都可查看。
const costTableScrollWidth = getCostTableScrollWidth(
    columns.map((column) => column.width),
    COST_TABLE_SELECTION_COLUMN_WIDTH,
  );

  /** 将表格内部滚动位置同步到顶部滚动条，避免用户必须滚到表格末尾才能横向查看。 */
  const handleHorizontalScrollbarScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const tableContent = tableWrapperRef.current?.querySelector<HTMLElement>('.ant-table-content');
    if (!tableContent || tableContent.scrollLeft === event.currentTarget.scrollLeft) return;
    tableContent.scrollLeft = event.currentTarget.scrollLeft;
  };

  // 表格自身滚动时反向同步顶部滚动条，保证鼠标滚轮、触控板和顶部滚动条位置一致。
  useEffect(() => {
    const tableContent = tableWrapperRef.current?.querySelector<HTMLElement>('.ant-table-content');
    const horizontalScrollbar = tableHorizontalScrollbarRef.current;
    if (!tableContent || !horizontalScrollbar) return undefined;

    const syncHorizontalScrollbar = () => {
      if (horizontalScrollbar.scrollLeft !== tableContent.scrollLeft) {
        horizontalScrollbar.scrollLeft = tableContent.scrollLeft;
      }
    };

    syncHorizontalScrollbar();
    tableContent.addEventListener('scroll', syncHorizontalScrollbar);
    return () => tableContent.removeEventListener('scroll', syncHorizontalScrollbar);
  }, [costTableScrollWidth, hasItems]);

  // 表格多选状态使用稳定行键，筛选或树结构变化时不会依赖数组下标。
  const costRowSelection = {
    columnWidth: COST_TABLE_SELECTION_COLUMN_WIDTH,
    selectedRowKeys: selectedNodeKeys,
    onChange: (nextSelectedKeys: React.Key[]) => setSelectedNodeKeys(nextSelectedKeys),
    getCheckboxProps: (record: CostItemNode) => ({
      disabled: Boolean(record.isInternalFilterContextNode),
    }),
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2563eb',
          borderRadius: 12,
          fontFamily: 'inherit',
        },
        components: {
          Table: {
            headerBg: '#f8fafc',
            headerColor: '#475569',
            headerSplitColor: '#f1f5f9',
            rowHoverBg: '#f8fafc',
            borderColor: '#f1f5f9',
          },
        },
      }}
    >
      <div className={`bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md col-span-2 relative ${isBusy ? 'opacity-70 pointer-events-none' : ''}`}>
        {isBusy && (
          <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/50 backdrop-blur-[2px] rounded-3xl gap-2">
            <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            <span className="text-xs font-bold text-blue-600">
              {isExtractingEquipment ? '正在重新提取设备清单...' : '正在重新匹配 BOM 清单并计算成本...'}
            </span>
          </div>
        )}

        {/* 顶部标题与摘要栏 */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-xl font-extrabold text-slate-800 flex items-center flex-wrap gap-2 mb-1">
              <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
              {isEquipmentOnly ? 'BOM 设备清单（待匹配）' : '智能 BOM 成本测算与对标匹配'}
              {onReextractEquipment && (
                <button
                  onClick={(e) => { e.stopPropagation(); onReextractEquipment(); }}
                  disabled={isBusy || isExtractingEquipment}
                  className="inline-flex items-center gap-1.5 px-2 py-1 ml-1 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="重新提取设备清单"
                  title="重新读取原文并提取设备清单，完成后等待手动进行价格匹配"
                >
                  <FileSearchOutlined className={isExtractingEquipment ? 'animate-spin text-blue-600' : ''} />
                  <span>{isExtractingEquipment ? '正在提取设备清单...' : '重新提取设备清单'}</span>
                </button>
              )}
              {onReextract && (
                <button 
                  onClick={(e) => { e.stopPropagation(); onReextract(); }}
                  disabled={isBusy || isRetrying}
                  className="inline-flex items-center gap-1.5 px-2 py-1 ml-1 text-xs font-semibold text-slate-500 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="重新匹配 BOM 清单"
                  title="重新匹配 BOM 清单，并重新计算参考单价与成本"
                >
                  <ReloadOutlined className={`text-sm ${isRetrying ? 'animate-spin text-blue-600' : ''}`} />
                  <span>{isRetrying ? '正在重新匹配 BOM 清单...' : '重新匹配 BOM 清单'}</span>
                </button>
              )}
              {hasCostData && (
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: 'docx',
                        icon: <FileWordOutlined className="text-blue-600" />,
                        label: '导出为 Word 文档 (.docx)',
                        onClick: handleExportDocx,
                      },
                      {
                        key: 'xlsx',
                        icon: <FileExcelOutlined className="text-emerald-600" />,
                        label: '导出为 Excel 表格 (.xlsx)',
                        onClick: handleExportXlsx,
                      },
                    ],
                  }}
                  trigger={['click']}
                  disabled={isBusy || isExporting}
                >
                  <button
                    type="button"
                    disabled={isBusy || isExporting}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 ml-1 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 border border-slate-300/80 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                    title="导出当前 BOM 清单（支持 Word 与 Excel 格式，表尾包含大小写总价）"
                    aria-label="导出表格"
                  >
                    <DownloadOutlined className="text-slate-600" />
                    <span>{isExporting ? '正在导出...' : '导出表格'}</span>
                    <DownOutlined className="text-[10px] text-slate-400" />
                  </button>
                </Dropdown>
              )}
            </h3>
            <p className="text-sm text-slate-500 font-medium">
              {isEquipmentOnly
                ? `已提取清单 ${items.length} 项，尚未进行价格匹配`
                : hasCostData
                  ? `全库匹配 ${items.length} 项（点击 ✏️ 可随时修改参考单价与数量）`
                  : "自动提取标书货物需求明细，结合价格库测算成本与风险..."}
            </p>
          </div>

          <div className="flex items-center gap-3">
            {dynamicStatusText && dynamicStatusText !== '预算未设置' && (
              <div className={`px-4 py-2 rounded-2xl text-xs font-bold border transition-all ${
                isRealTimeExceeded 
                  ? 'bg-rose-50 text-rose-600 border-rose-300 shadow-sm animate-pulse' 
                  : isRealTimeWarning 
                    ? 'bg-amber-50 text-amber-600 border-amber-300' 
                    : 'bg-emerald-50 text-emerald-600 border-emerald-300'
              }`}>
                {isRealTimeExceeded && '🚨 '}
                {isRealTimeWarning && '⚠️ '}
                {!isRealTimeExceeded && !isRealTimeWarning && '✓ '}
                {dynamicStatusText}
              </div>
            )}

            {/* 实时预估总成本卡片 */}
            <div className={`text-right p-3.5 px-5 rounded-2xl border shadow-inner transition-all ${
              isRealTimeExceeded 
                ? 'bg-rose-50/70 border-rose-200 shadow-rose-100' 
                : isRealTimeWarning 
                  ? 'bg-amber-50/70 border-amber-200' 
                  : 'bg-slate-50 border-slate-100'
            }`}>
              <div className="text-xs font-bold text-slate-500 mb-0.5 tracking-wider uppercase">预估总成本 (实时)</div>
              <div className={`text-2xl font-black ${
                hasCostData 
                  ? (isRealTimeExceeded ? 'text-rose-600' : (isRealTimeWarning ? 'text-amber-600' : 'text-blue-600')) 
                  : 'text-slate-300'
              }`}>
                {hasCostData ? `¥${realTimeTotalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '暂未测算'}
              </div>
              {effectiveLimitAmount ? (
                <div className="text-xs text-slate-500 font-medium mt-0.5">
                  基准{limitTypeLabel}: <span className="font-bold text-slate-700">¥{effectiveLimitAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  {maxPriceLimitAmount && budgetAmount && maxPriceLimitAmount !== budgetAmount && (
                    <span className="text-[10px] text-slate-400 block">
                      (采购总预算: ¥{budgetAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })})
                    </span>
                  )}
                </div>
              ) : (normalizeCostText(costAnalysis.budget_limit) && (
                <div className="text-xs text-slate-400 font-medium mt-0.5">
                  预算限额: {normalizeCostText(costAnalysis.budget_limit)}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 强视觉熔断警报横幅（当实时总价超出最高限价/预算时立即触发） */}
        {isRealTimeExceeded && (
          <div className="mb-5 p-4 bg-rose-50/90 rounded-2xl border-2 border-rose-200 text-rose-800 flex items-start gap-3 shadow-sm animate-pulse">
            <span className="text-2xl p-1 bg-rose-100 rounded-xl">🚨</span>
            <div className="flex-1">
              <div className="font-extrabold text-sm text-rose-900 flex items-center gap-2">
                <span>【强视觉熔断警报】当前预估总成本已超出{limitTypeLabel}！</span>
                <span className="bg-rose-600 text-white text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">废标风险红线</span>
              </div>
              <div className="text-xs text-rose-700 mt-1 leading-relaxed">
                当前实时测算总价为 <span className="font-bold underline font-mono">¥{realTimeTotalCost.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>，已超出基准{limitTypeLabel}（<span className="font-mono font-bold">¥{effectiveLimitAmount?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>）共 <span className="font-extrabold text-rose-900 font-mono">¥{overrunAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>（超出幅度 {(usageRatio - 100).toFixed(1)}%）。根据招投标法，若以当前价格起草投标书，将直接触发废标风险，请及时在下方表格中调整指导单价或数量。
              </div>
            </div>
          </div>
        )}

        {/* 专家评估总结 */}
        {normalizeCostText(costAnalysis.analysis_summary) && (
          <div className="mb-4 p-3.5 bg-blue-50/60 rounded-2xl border border-blue-100 text-xs text-slate-700 leading-relaxed font-medium flex items-start gap-2">
            <span className="text-blue-500 text-sm">💡</span>
            <div>
              <span className="font-bold text-blue-900 mr-1">专家评估推导:</span>
              {normalizeCostText(costAnalysis.analysis_summary)}
            </div>
          </div>
        )}

        {/* 提示消息浮层 */}
        {saveMessage && (
          <div className={`mb-4 p-3.5 rounded-2xl text-xs font-bold transition-all shadow-sm flex items-center justify-between gap-3 ${
            saveMessage.type === 'success' 
              ? 'bg-emerald-50 text-emerald-800 border-2 border-emerald-200 shadow-emerald-50' 
              : 'bg-rose-50 text-rose-800 border-2 border-rose-200 shadow-rose-50 animate-pulse'
          }`}>
            <div className="flex items-center gap-2">
              <span className="text-base">{saveMessage.type === 'success' ? '✓' : '🚨'}</span>
              <span>{saveMessage.text}</span>
            </div>
            <span className="text-[10px] text-slate-400 font-normal shrink-0">已自动落盘</span>
          </div>
        )}

        {/* 顶部父子树形折叠控制与多区域快速筛选工具栏 */}
        {hasItems && (
          <div className="flex flex-col gap-2.5 mb-3 px-1">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600 font-medium">
                <span className="bg-slate-100 text-slate-700 px-2.5 py-1 rounded-xl font-bold border border-slate-200/60 shadow-2xs flex items-center gap-1.5">
                  <span>📋</span> BOM 清单共 <strong className="text-blue-700">{items.length}</strong> 项
                </span>
                {parentCount > 0 && (
                  <span className="text-slate-500 hidden sm:inline">
                    （含 <strong className="text-blue-700 font-bold">{parentCount}</strong> 套成套设备总成，共 <strong className="text-blue-700 font-bold">{childCountTotal}</strong> 个内部子部件）
                  </span>
                )}

                {selectedNodeKeys.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 ml-2 pl-2 border-l border-amber-200">
                    <span className="text-amber-800 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-xl font-bold">
                      已选 {selectedNodeKeys.length} 项
                    </span>
                    <Button
                      type="primary"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={handleOpenBatchGroupAssign}
                      className="rounded-xl font-bold text-xs bg-violet-600 hover:bg-violet-700"
                    >
                      批量设置表内分组
                    </Button>
                    <Button
                      size="small"
                      onClick={() => setSelectedNodeKeys([])}
                      className="rounded-xl font-bold text-xs"
                    >
                      清除选择
                    </Button>
                  </div>
                )}

                {/* 多区域/多分标段快速筛选工具栏 (当且仅当存在至少2个及以上不同分部时才展示) */}
                {(groupingDisplayMode === 'external' || groupingDisplayMode === 'mixed') && availableSections.length > 1 && (
                  <div className="flex flex-wrap items-center gap-1.5 ml-2 pl-2 border-l border-slate-200">
                    <button
                      type="button"
                      onClick={() => setSelectedSection('ALL')}
                      className={`px-2.5 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                        selectedSection === 'ALL'
                          ? 'bg-blue-600 text-white border-blue-600 shadow-2xs'
                          : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                      }`}
                    >
                      全部分项 ({items.length})
                    </button>
                    {availableSections.map(sec => {
                      const secCount = items.filter(it => normalizeSectionName(it.section_name) === sec).length;
                      const isSelected = selectedSection === sec;
                      return (
                        <button
                          key={sec}
                          type="button"
                          onClick={() => setSelectedSection(sec)}
                          className={`px-2.5 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer border flex items-center gap-1 ${
                            isSelected
                              ? 'bg-cyan-600 text-white border-cyan-600 shadow-2xs'
                              : 'bg-cyan-50 text-cyan-800 border-cyan-200 hover:bg-cyan-100'
                          }`}
                        >
                          <span>📍</span>
                          <span>{sec}</span>
                          <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ml-0.5 ${isSelected ? 'bg-cyan-700 text-white' : 'bg-cyan-200/90 text-cyan-950'}`}>
                            {secCount}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* 表内 BOQ 分组筛选：名称和数量全部来自解析结果，不依赖固定业务词表。 */}
                {(groupingDisplayMode === 'internal' || groupingDisplayMode === 'mixed') && availableParts.length > 1 && (
                  <div className="flex flex-wrap items-center gap-1.5 ml-2 pl-2 border-l border-violet-200">
                    <button
                      type="button"
                      onClick={() => setSelectedPart('ALL')}
                      className={`px-2.5 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                        selectedPart === 'ALL'
                          ? 'bg-violet-600 text-white border-violet-600 shadow-2xs'
                          : 'bg-violet-50 text-violet-700 border-violet-200 hover:bg-violet-100'
                      }`}
                    >
                      全部表内分组 ({items.length})
                    </button>
                    {availableParts.map((part) => {
                      const partCount = items.filter(
                        (item) => normalizeCostText(item?.part_name).trim() === part,
                      ).length;
                      const isSelected = selectedPart === part;
                      return (
                        <button
                          key={part}
                          type="button"
                          onClick={() => setSelectedPart(part)}
                          className={`px-2.5 py-1 rounded-xl text-xs font-bold transition-all cursor-pointer border flex items-center gap-1 ${
                            isSelected
                              ? 'bg-violet-600 text-white border-violet-600 shadow-2xs'
                              : 'bg-violet-50 text-violet-800 border-violet-200 hover:bg-violet-100'
                          }`}
                        >
                          <span>🗂️</span>
                          <span>{part}</span>
                          <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ml-0.5 ${isSelected ? 'bg-violet-700 text-white' : 'bg-violet-200/90 text-violet-950'}`}>
                            {partCount}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {parentCount > 0 && (
                <div className="flex items-center gap-2">
                  <Button
                    size="small"
                    onClick={toggleExpandAll}
                    icon={isAllExpanded ? <UpOutlined /> : <DownOutlined />}
                    className={`rounded-xl font-bold text-xs transition-all shadow-2xs cursor-pointer border ${
                      isAllExpanded
                        ? 'bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200'
                        : 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 hover:border-blue-300'
                    }`}
                    title={isAllExpanded ? '点击一键折叠所有成套设备' : '点击一键展开所有成套设备'}
                  >
                    <span>{isAllExpanded ? `全部折叠 (${parentCount}套)` : `全部展开 (${parentCount}套)`}</span>
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Ant Design BOM 成本核算树形表格 */}
        <div
          ref={tableWrapperRef}
          className="cost-table-ant rounded-2xl border border-slate-200 bg-white shadow-sm overflow-visible"
        >
          <style>{`
            .cost-table-ant .ant-table-thead > tr > th {
              background: #f8fafc !important;
              font-weight: 800 !important;
              color: #475569 !important;
              border-bottom: 2px solid #cbd5e1 !important;
              font-size: 12px !important;
              text-transform: uppercase !important;
              letter-spacing: 0.05em !important;
              text-align: center !important;
              vertical-align: middle !important;
            }

            /* 覆盖 Ant Design 对数字列的默认对齐，让所有表头标题统一居中。 */
            .cost-table-ant .ant-table-thead > tr > th .ant-table-column-title {
              text-align: center !important;
            }

            /* 收紧表头和单元格内边距，避免默认留白叠加后遮挡后面的价格列。 */
            .cost-table-ant .ant-table-thead > tr > th,
            .cost-table-ant .ant-table-tbody > tr > td {
              padding-left: 8px !important;
              padding-right: 8px !important;
              border-right: 1px solid #dbe3ee !important;
              background-clip: padding-box;
            }
            /* 表头右侧提供可发现的拖拽热区，鼠标移入时显示列宽调整提示。 */
            .cost-table-ant .cost-table-resize-handle {
              position: absolute;
              top: 0;
              right: 0;
              z-index: 4;
              width: 6px;
              height: 100%;
              cursor: col-resize;
              touch-action: none;
              background: transparent;
              transition: background-color 120ms ease;
            }
            .cost-table-ant .cost-table-resize-handle:hover,
            .cost-table-ant .cost-table-resize-handle.is-resizing {
              background: rgba(37, 99, 235, 0.35);
            }
            /* 按列配置约束表格布局，长文本在单元格内换行而不把整张表撑宽。 */
            .cost-table-ant .ant-table table {
              table-layout: fixed !important;
            }

            /* 顶部横向滚动条吸顶显示，长表格无需滚到底部即可查看隐藏列。 */
            .cost-table-ant .cost-table-horizontal-scrollbar {
              position: sticky;
              top: ${COST_TABLE_GLOBAL_HEADER_HEIGHT}px;
              z-index: 21;
              overflow-x: auto;
              overflow-y: hidden;
              height: ${COST_TABLE_HORIZONTAL_SCROLLBAR_HEIGHT}px;
              margin: 0 8px 4px;
              border: 1px solid #e2e8f0;
              border-radius: 9999px;
              background: #f8fafc;
              scrollbar-width: thin;
              scrollbar-color: #94a3b8 #f1f5f9;
            }
            .cost-table-ant .cost-table-horizontal-scrollbar > div {
              height: 1px;
            }
            .cost-table-ant .cost-table-horizontal-scrollbar::-webkit-scrollbar {
              height: 8px;
            }
            .cost-table-ant .cost-table-horizontal-scrollbar::-webkit-scrollbar-track {
              background: #f1f5f9;
              border-radius: 9999px;
            }
            .cost-table-ant .cost-table-horizontal-scrollbar::-webkit-scrollbar-thumb {
              background: #94a3b8;
              border-radius: 9999px;
            }
            .cost-table-ant .cost-table-horizontal-scrollbar::-webkit-scrollbar-thumb:hover {
              background: #64748b;
            }

            /* Ant Design 吸顶表头位于顶部横向滚动条下方，并与页面主导航栏保持层级关系。 */
            .cost-table-ant .ant-table-sticky-holder {
              z-index: 20 !important;
              box-shadow: 0 1px 0 rgba(203, 213, 225, 0.9), 0 4px 10px rgba(148, 163, 184, 0.08);
            }

            /* 隐藏 Ant Design 表格底部原生横向滚动条，避免页面底部出现重复滚动条。 */
            .cost-table-ant .ant-table-content,
            .cost-table-ant .ant-table-body {
              scrollbar-width: none;
              -ms-overflow-style: none;
            }
            .cost-table-ant .ant-table-content::-webkit-scrollbar,
            .cost-table-ant .ant-table-body::-webkit-scrollbar {
              width: 0;
              height: 0;
              display: none;
            }
            /* sticky 模式会额外生成底部悬浮滚动条，横向操作统一由顶部滚动条承接。 */
            .cost-table-ant .ant-table-sticky-scroll {
              display: none !important;
            }

            /* Level 1 & Level 4: 成套主标的物母项行 (Royal Blue 商务科技蓝) */
            .cost-table-ant tr.cost-level-1-parent > td {
              background-color: #f0f7ff !important;
              border-top: 2px solid #bfdbfe !important;
              border-bottom: 2px solid #bfdbfe !important;
            }
            .cost-table-ant tr.cost-level-1-parent:hover > td {
              background-color: #e0f2fe !important;
            }
            .cost-table-ant tr.cost-level-1-parent > td:first-child {
              border-left: 5px solid #2563eb !important;
            }

            /* Level 1: 独立设备行 (Clean Slate 纯白/浅灰底) */
            .cost-table-ant tr.cost-level-1-standalone > td {
              background-color: #ffffff !important;
              border-bottom: 1px solid #f1f5f9 !important;
            }
            .cost-table-ant tr.cost-level-1-standalone:hover > td {
              background-color: #f8fafc !important;
            }
            .cost-table-ant tr.cost-level-1-standalone > td:first-child {
              border-left: 5px solid #64748b !important;
            }

            /* Level 4: 四级子部件行 (复用 Level 1 科技蓝指示条) */
            .cost-table-ant tr.cost-level-1-child > td {
              background-color: #f8fcff !important;
              border-bottom: 1px dashed #bfdbfe !important;
            }
            .cost-table-ant tr.cost-level-1-child:hover > td {
              background-color: #eff6ff !important;
            }
            .cost-table-ant tr.cost-level-1-child > td:first-child {
              border-left: 5px solid #3b82f6 !important;
            }

            /* Level 2 & Level 5: 二级总成母项 (Deep Indigo 沉稳靛蓝) */
            .cost-table-ant tr.cost-level-2-parent > td {
              background-color: #f5f7ff !important;
              border-top: 1.5px solid #c7d2fe !important;
              border-bottom: 1.5px solid #c7d2fe !important;
            }
            .cost-table-ant tr.cost-level-2-parent:hover > td {
              background-color: #eef2ff !important;
            }
            .cost-table-ant tr.cost-level-2-parent > td:first-child {
              border-left: 5px solid #4f46e5 !important;
            }

            /* Level 2 & Level 5: 二级/五级子分项部件 (Deep Indigo 沉稳靛蓝) */
            .cost-table-ant tr.cost-level-2-child > td {
              background-color: #fafbff !important;
              border-bottom: 1px dashed #e0e7ff !important;
            }
            .cost-table-ant tr.cost-level-2-child:hover > td {
              background-color: #eef2ff !important;
            }
            .cost-table-ant tr.cost-level-2-child > td:first-child {
              border-left: 5px solid #6366f1 !important;
            }

            /* Level 3 & Level 6: 三级总成母项 (Sky Cyan 冰川天蓝) */
            .cost-table-ant tr.cost-level-3-parent > td {
              background-color: #f0f9ff !important;
              border-top: 1.5px solid #bae6fd !important;
              border-bottom: 1.5px solid #bae6fd !important;
            }
            .cost-table-ant tr.cost-level-3-parent:hover > td {
              background-color: #e0f2fe !important;
            }
            .cost-table-ant tr.cost-level-3-parent > td:first-child {
              border-left: 5px solid #0284c7 !important;
            }

            /* Level 3 & Level 6: 三级/六级元器件子项 (Sky Cyan 冰川天蓝) */
            .cost-table-ant tr.cost-level-3-child > td {
              background-color: #f8fcff !important;
              border-bottom: 1px dashed #e0f2fe !important;
            }
            .cost-table-ant tr.cost-level-3-child:hover > td {
              background-color: #f0f9ff !important;
            }
            .cost-table-ant tr.cost-level-3-child > td:first-child {
              border-left: 5px solid #0284c7 !important;
            }

            /* 修改中的行高亮 (Yellow 暖金高亮) */
            .cost-table-ant tr.cost-editing-row > td {
              background-color: #fefce8 !important;
              border-top: 2px solid #eab308 !important;
              border-bottom: 2px solid #eab308 !important;
            }
          `}</style>
          {hasItems && (
            <>
              <div
                ref={tableHorizontalScrollbarRef}
                className="cost-table-horizontal-scrollbar"
                aria-label="横向滚动查看 BOM 隐藏列"
                onScroll={handleHorizontalScrollbarScroll}
              >
                <div style={{ width: `${costTableScrollWidth}px` }} />
              </div>
            </>
          )}
          {hasItems ? (
            <Table<CostItemNode>
              columns={columns}
              dataSource={filteredTreeData}
              rowSelection={costRowSelection}
              pagination={false}
              // 使用自定义表头承接拖拽事件，让用户按当前清单内容调整各列宽度。
              components={{
                header: {
                  cell: ResizableHeaderCell,
                },
              }}
              // 使用当前列宽总和驱动整张表横向滚动，确保所有列都可被查看。
              scroll={{ x: costTableScrollWidth }}
              // 吸顶表头位于全局导航栏和顶部横向滚动条之后。
              sticky={{ offsetHeader: COST_TABLE_STICKY_HEADER_TOP }}
              expandable={{
                expandedRowKeys,
                onExpandedRowsChange: (newKeys) => setExpandedRowKeys(newKeys),
                indentSize: 20,
                expandIcon: ({ expanded, onExpand, record }) => {
                  if (!record.children || record.children.length === 0) {
                    return null;
                  }
                  const lvl = record.tree_level || 1;
                  const colorTier = (((lvl - 1) % 3) + 1);
                  const btnColorClasses = {
                    1: expanded ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700 shadow-blue-200' : 'bg-white text-blue-700 border-blue-300 hover:bg-blue-50',
                    2: expanded ? 'bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700 shadow-indigo-200' : 'bg-white text-indigo-700 border-indigo-300 hover:bg-indigo-50',
                    3: expanded ? 'bg-sky-600 text-white border-sky-600 hover:bg-sky-700 shadow-sky-200' : 'bg-white text-sky-700 border-sky-300 hover:bg-sky-50',
                  }[colorTier] || (expanded ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-blue-700 border-blue-300');

                  return (
                    <button
                      type="button"
                      onClick={(e) => onExpand(record, e)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-xs font-bold transition-all shadow-2xs cursor-pointer mr-2.5 border ${btnColorClasses}`}
                      title={expanded ? '点击折叠下属子部件' : '点击展开下属子部件'}
                    >
                      <span className={`transform transition-transform text-[10px] ${expanded ? '' : '-rotate-90'}`}>▼</span>
                      <span>{expanded ? `折叠子项 (${record.children.length})` : `展开子项 (${record.children.length})`}</span>
                    </button>
                  );
                }
              }}
              rowClassName={(record) => {
                if (record.key === editingKey) return 'cost-editing-row';
                const lvl = record.tree_level || 1;
                const colorTier = (((lvl - 1) % 3) + 1);
                if (record.isParent) {
                  return `cost-level-${colorTier}-parent`;
                }
                if (record.parent_item || lvl > 1) {
                  return `cost-level-${colorTier}-child`;
                }
                return 'cost-level-1-standalone';
              }}
              size="middle"
            />
          ) : equipmentList.length > 0 ? (
            <div className="p-4">
              <div className="text-xs text-slate-500 font-bold mb-2">已从标书提取到如下设备，等待对接价格库测算：</div>
              <Table
                dataSource={equipmentList.map((item, idx) => ({ ...item, key: `eq_${idx}` }))}
                pagination={false}
                size="small"
                columns={[
                  {
                    title: '设备名称',
                    dataIndex: 'item_name',
                    key: 'item_name',
                    render: (name: string) => (
                      <span className="font-bold text-slate-800">
                        {name || '未知设备'}
                      </span>
                    )
                  },
                  {
                    title: '规格要求',
                    dataIndex: 'specifications',
                    key: 'specifications',
                    render: (specs, record: any) => {
                      const text = [specs, ...(record.key_parameters || [])].filter(Boolean).join('；');
                      return <span className="text-slate-500 text-xs">{text || '--'}</span>;
                    }
                  },
                  {
                    title: '数量',
                    dataIndex: 'quantity',
                    key: 'quantity',
                    width: 100,
                    render: (qty, record: any) => (
                      <span className="font-bold text-slate-700">{qty ? `${qty} ${record.unit || ''}` : (record.unit || '--')}</span>
                    )
                  },
                  {
                    title: '测算状态',
                    key: 'status',
                    width: 120,
                    render: () => <Tag color="default">等待核算</Tag>
                  }
                ]}
              />
            </div>
          ) : (
            <div className="py-12">
              <Empty description="未从文档中提取到核心设备清单" />
            </div>
          )}
        </div>

        {/* 底部新增费用项交互栏 */}
        <div className="mt-4 flex flex-col gap-3">
          {!isAdding ? (
            <div className="flex items-center justify-between">
              <Button
                type="dashed"
                icon={<PlusOutlined />}
                onClick={() => setIsAdding(true)}
                className="rounded-2xl font-bold text-xs text-blue-600 border-blue-200 bg-blue-50/50 hover:bg-blue-100"
              >
                新增费用项 (如人工费/售后服务费)
              </Button>

              {isSaving && (
                <span className="text-xs text-blue-600 font-bold animate-pulse flex items-center gap-1.5">
                  <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  正在同步保存数据...
                </span>
              )}
            </div>
          ) : (
            <form onSubmit={handleAddItem} className="bg-slate-50/90 p-5 rounded-2xl border border-blue-200/80 shadow-sm space-y-4 transition-all">
              <div className="flex items-center justify-between border-b border-slate-200/60 pb-2">
                <span className="text-xs font-extrabold text-blue-900 flex items-center gap-1.5">
                  <span>🛠️</span> 新增自定义成本分项
                </span>
                <button
                  type="button"
                  onClick={() => setIsAdding(false)}
                  className="text-xs text-slate-400 hover:text-slate-600 font-bold cursor-pointer"
                >
                  ✕ 取消
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-6 gap-3 text-xs">
                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">费用项/设备名称 *</label>
                  <input
                    type="text"
                    required
                    placeholder="例如: 现场施工人工费 / 光伏组件"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">品牌</label>
                  <input
                    type="text"
                    placeholder="例如: 华为 / 天合光能 / 自定义"
                    value={newBrand}
                    onChange={(e) => setNewBrand(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">规格/型号</label>
                  <input
                    type="text"
                    placeholder="例如: 635Wp / SUN2000-110KTL"
                    value={newModel}
                    onChange={(e) => setNewModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-3">
                  <label className="block text-slate-500 font-bold mb-1">生产厂家</label>
                  <input
                    type="text"
                    placeholder="例如: 华为技术有限公司 / 某制造厂"
                    value={newManufacturer}
                    onChange={(e) => setNewManufacturer(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-3">
                  <label className="block text-slate-500 font-bold mb-1">所属成套设备 (可选，默认独立设备)</label>
                  <Select
                    allowClear
                    placeholder="选择挂载的成套设备 (留空则为独立主项)"
                    value={newParentItem || undefined}
                    onChange={(val) => setNewParentItem(val || '')}
                    className="w-full"
                    options={flattenCostTreeNodes(treeData).map(n => ({
                      label: `${n.name} (L${n.tree_level || 1})`,
                      value: n.node_id
                    }))}
                  />
                </div>

                <div className="md:col-span-6">
                  <label className="block text-slate-500 font-bold mb-1">内容说明</label>
                  <input
                    type="text"
                    placeholder="例如: 包含硬件安调、维保测试及工时补贴"
                    value={newSpec}
                    onChange={(e) => setNewSpec(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-6">
                  <label className="block text-slate-500 font-bold mb-1">备注</label>
                  <textarea
                    rows={2}
                    maxLength={500}
                    placeholder="例如：含套装价、含安装调试、暂不计价"
                    value={newRemark}
                    onChange={(e) => setNewRemark(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium resize-y"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">数量</label>
                  <input
                    type="number"
                    min="0.01"
                    step="any"
                    value={newQty}
                    onChange={(e) => setNewQty(parseFloat(e.target.value) || 1)}
                    className="quantity-input w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">单位</label>
                  <input
                    type="text"
                    placeholder="项 / 块 / 台 / 年"
                    value={newUnit}
                    onChange={(e) => setNewUnit(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="block text-slate-500 font-bold mb-1">参考单价 (元) *</label>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    required
                    placeholder="例如: 35000"
                  value={newPrice}
                  onChange={(e) => setNewPrice(parseFloat(e.target.value) || 0)}
                  className="number-input w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
                  <p className="mt-1 text-[11px] text-slate-400">
                    填写 0 元时，下一次批量重匹配会尝试从价格库匹配；填写正价后保留人工定价。
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-1">
                <Button
                  onClick={() => setIsAdding(false)}
                  className="rounded-xl font-bold text-xs"
                >
                  取消
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  className="rounded-xl font-bold text-xs bg-blue-600 hover:bg-blue-700"
                >
                  确认添加并保存
                </Button>
              </div>
            </form>
          )}
        </div>

        {/* 为指定成套设备添加子项弹窗 Modal */}
        <Modal
          title={
            <div className="flex items-center gap-2 text-slate-800 font-extrabold pb-2 border-b border-slate-100">
              <span className="text-blue-600 text-lg">➕</span>
              <span>
                {addNodeMode === 'sibling'
                  ? `新增${targetParentNode ? `「${targetParentNode.name}」下的` : '顶层'}同级标的物 / 分项`
                  : `为「${targetParentNode?.name || '当前标的物'}」添加子标的物 / 分项`}
              </span>
            </div>
          }
          open={isAddChildModalOpen}
          onOk={handleSaveNewChildItem}
          onCancel={() => setIsAddChildModalOpen(false)}
          okText="确认添加并自动汇总"
          cancelText="取消"
          width={650}
          destroyOnHidden
          okButtonProps={{ className: 'bg-blue-600 hover:bg-blue-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-2 space-y-3.5 text-xs">
            <div className="bg-blue-50/80 p-2.5 rounded-xl border border-blue-200/80 text-blue-900 leading-relaxed font-medium">
              💡 <strong>说明：</strong>
              {targetParentNode
                ? <>新增项将挂载至「<strong>{targetParentNode.name}</strong>」下，保存后自动触发父子成本汇总。</>
                : <>新增项将作为顶层标的物保存，并自动参与总成本汇总。</>}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="md:col-span-2">
                <label className="block text-slate-600 font-bold mb-1">标的物 / 子项设备名称 *</label>
                <Input
                  required
                  placeholder="例如: 智能微断开关 / 防雷浪涌保护器 / 传感器"
                  value={childFormName}
                  onChange={(e) => setChildFormName(e.target.value)}
                  className="font-bold text-sm"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">品牌</label>
                <Input
                  placeholder="例如: 施耐德 / 正泰 / 华为 / 自定义"
                  value={childFormBrand}
                  onChange={(e) => setChildFormBrand(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">规格 / 型号</label>
                <Input
                  placeholder="例如: iC65N 2P C16A / SPD-40kA"
                  value={childFormModel}
                  onChange={(e) => setChildFormModel(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">生产厂家</label>
                <Input
                  placeholder="例如: 施耐德电气(中国)有限公司"
                  value={childFormManufacturer}
                  onChange={(e) => setChildFormManufacturer(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">单套定额数量 (每套成套设备所需数量)</label>
                <InputNumber
                  min={0.01}
                  step="any"
                  controls={false}
                  value={childFormPerSetQty}
                  onChange={(v) => {
                    const pQty = v || 1;
                    setChildFormPerSetQty(pQty);
                    if (targetParentNode?.qty) {
                      setChildFormQty(Number((pQty * (targetParentNode.qty || 1)).toFixed(2)));
                    }
                  }}
                  className="quantity-input w-full font-bold"
                />
              </div>

              <div className="md:col-span-2">
                <label className="block text-slate-600 font-bold mb-1">规格参数 / 内容要求</label>
                <Input.TextArea
                  rows={2}
                  placeholder="技术要求或规格参数说明"
                  value={childFormSpec}
                  onChange={(e) => setChildFormSpec(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">总工程量 (数量)</label>
                <InputNumber
                  min={0.01}
                  step="any"
                  controls={false}
                  value={childFormQty}
                  onChange={(v) => setChildFormQty(v || 1)}
                  className="quantity-input w-full font-bold"
                />
              </div>

              <div>
                <label className="block text-slate-600 font-bold mb-1">单位</label>
                <Input
                  placeholder="台 / 个 / 套 / 块"
                  value={childFormUnit}
                  onChange={(e) => setChildFormUnit(e.target.value)}
                />
              </div>

              <div className="md:col-span-2">
                <label className="block text-slate-600 font-bold mb-1">参考指导单价 (元) *</label>
                <InputNumber
                  min={0}
                  step="any"
                  controls={false}
                  prefix="¥"
                  placeholder="0.00"
                  value={childFormPrice}
                  onChange={(v) => setChildFormPrice(v || 0)}
                  className="number-input w-full font-bold text-base text-blue-700"
                />
                <p className="mt-1 text-[11px] text-slate-400">
                  填写 0 元时，下一次批量重匹配会尝试从价格库匹配；填写正价后保留人工定价。
                </p>
              </div>

              <div className="md:col-span-2">
                <label className="block text-slate-600 font-bold mb-1">备注说明</label>
                <Input
                  placeholder="例如: 随箱成套配置、含安装附件"
                  value={childFormRemark}
                  onChange={(e) => setChildFormRemark(e.target.value)}
                />
              </div>
            </div>
          </div>
        </Modal>

        {/* 修改父项归属弹窗：支持直接选择顶层或任意合法父节点。 */}
        <Modal
          title="修改父项归属"
          open={isMoveParentModalOpen}
          onOk={handleConfirmMoveParent}
          onCancel={() => {
            setIsMoveParentModalOpen(false);
            setMovingNode(null);
          }}
          okText="确认移动并保存"
          cancelText="取消"
          width={520}
          destroyOnHidden
          okButtonProps={{ className: 'bg-blue-600 hover:bg-blue-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-3 space-y-3 text-xs">
            <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded-xl p-3 leading-relaxed">
              节点「<strong>{movingNode?.name}</strong>」及其全部下级将一起移动；不能选择自身或自己的下级作为父项。
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">新的父项</label>
              <Select
                className="w-full"
                value={moveTargetParentId}
                onChange={(value) => setMoveTargetParentId(value || '')}
                options={moveParentOptions}
                showSearch
                optionFilterProp="label"
                filterOption={(input, option) => filterCostParentOption(input, option)}
                placeholder="输入名称或层级关键字搜索"
              />
            </div>
          </div>
        </Modal>

        {/* 编辑表内 BOQ 分组弹窗：修改后同步同一路径下的所有清单项。 */}
        <Modal
          title="编辑表内分组"
          open={isGroupEditModalOpen}
          onOk={handleSaveGroupEdit}
          onCancel={handleCancelGroupEdit}
          okText="确认修改并保存"
          cancelText="取消"
          width={520}
          destroyOnHidden
          okButtonProps={{ className: 'bg-violet-600 hover:bg-violet-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-3 space-y-3 text-xs">
            <div className="bg-violet-50 border border-violet-200 text-violet-900 rounded-xl p-3 leading-relaxed">
              修改后将同步更新当前分组路径下的所有清单项；末级分组留空时，仅保留主分组这一层，避免同一分组被拆散。
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">新的主分组名称 *</label>
              <Input
                autoFocus
                value={groupEditPartName}
                maxLength={100}
                onChange={(event) => setGroupEditPartName(event.target.value)}
                placeholder="例如：建筑工程、乙供设备及材料"
              />
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">新的末级分组名称（可选）</label>
              <Input
                value={groupEditName}
                maxLength={100}
                onChange={(event) => setGroupEditName(event.target.value)}
                placeholder="例如：电缆桥架支架；没有下级分类可留空"
                onPressEnter={handleSaveGroupEdit}
              />
            </div>
          </div>
        </Modal>

        {/* 为原本无表内分组的节点设置主分组和末级分组。 */}
        <Modal
          title="设置表内分组"
          open={isGroupAssignModalOpen}
          onOk={handleSaveGroupAssign}
          onCancel={handleCancelGroupAssign}
          okText="确认设置并保存"
          cancelText="取消"
          width={520}
          destroyOnHidden
          okButtonProps={{ className: 'bg-violet-600 hover:bg-violet-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-3 space-y-3 text-xs">
            <div className="bg-violet-50 border border-violet-200 text-violet-900 rounded-xl p-3 leading-relaxed">
              节点「<strong>{groupAssignRecord?.name}</strong>」及其全部下级将设置为新的表内分组；没有末级分类时可留空，已有的表外分项归属不会被删除。
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">表内主分组名称 *</label>
              <Input
                value={groupAssignPartName}
                maxLength={100}
                onChange={(event) => setGroupAssignPartName(event.target.value)}
                placeholder="例如：建筑工程、乙供设备及材料"
              />
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">表内末级分组名称（可选）</label>
              <Input
                autoFocus
                value={groupAssignName}
                maxLength={100}
                onChange={(event) => setGroupAssignName(event.target.value)}
                placeholder="例如：电缆桥架支架；没有下级分类可留空"
                onPressEnter={handleSaveGroupAssign}
              />
            </div>
          </div>
        </Modal>

        {/* 批量设置表内分组弹窗：多选节点时一次性同步其子树。 */}
        <Modal
          title={`批量设置表内分组（已选 ${selectedNodeKeys.length} 项）`}
          open={isBatchGroupAssignModalOpen}
          onOk={handleSaveBatchGroupAssign}
          onCancel={handleCancelBatchGroupAssign}
          okText="确认批量设置并保存"
          cancelText="取消"
          width={520}
          destroyOnHidden
          okButtonProps={{ className: 'bg-violet-600 hover:bg-violet-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-3 space-y-3 text-xs">
            <div className="bg-violet-50 border border-violet-200 text-violet-900 rounded-xl p-3 leading-relaxed">
              已勾选的节点及其全部下级会统一设置为同一表内分组；已有的表外分项归属不会被删除。没有末级分类时可以留空。
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">表内主分组名称 *</label>
              <Input
                value={batchGroupPartName}
                maxLength={100}
                onChange={(event) => setBatchGroupPartName(event.target.value)}
                placeholder="例如：建筑工程、乙供设备及材料"
              />
            </div>
            <div>
              <label className="block text-slate-600 font-bold mb-1">表内末级分组名称（可选）</label>
              <Input
                autoFocus
                value={batchGroupName}
                maxLength={100}
                onChange={(event) => setBatchGroupName(event.target.value)}
                placeholder="没有下级分类可留空"
                onPressEnter={handleSaveBatchGroupAssign}
              />
            </div>
          </div>
        </Modal>
      </div>
    </ConfigProvider>
  );
}
