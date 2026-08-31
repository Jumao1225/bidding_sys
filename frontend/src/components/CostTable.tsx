import React, { useState, useEffect } from 'react';
import { 
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
  Select,
  message
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
  UndoOutlined
} from '@ant-design/icons';
import { apiFetch, API_BASE_URL } from '../utils/api';
import { exportBomToDocx, exportBomToXlsx } from '../utils/bomExporter';

/**
 * 树形节点物料数据接口
 */
interface CostItemNode {
  key: string;
  originalIndex: number;
  id?: string;
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
  section_name?: string | null;
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

/**
 * 将接口或历史数据中的结构化值安全转换为可展示文本。
 * 兼容 {type, input} 等旧版结构化输出，避免 React 直接渲染对象。
 */
export function normalizeCostText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
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
    'remark', 'parent_item', 'root_item', 'section_name', 'brand', 'model',
    'manufacturer', 'pricing_mode', 'raw_brand', 'raw_model', 'raw_manufacturer',
    'raw_spec', 'raw_unit', 'raw_name', 'raw_match_quality'
  ];
  textFields.forEach((field) => {
    if (field in normalized && normalized[field] !== null && normalized[field] !== undefined) {
      normalized[field] = normalizeCostText(normalized[field]);
    }
  });
  normalized.key_parameters = normalizeCostTextList(normalized.key_parameters);

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
  return value.map(normalizeCostItem).filter((item) => Boolean(item.name));
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
  const [items, setItems] = useState<any[]>(() => {
    const costItems = normalizeCostItems(costAnalysis?.items);
    return !isEquipmentOnly && costItems.length > 0 ? costItems : normalizeCostItems(equipmentList);
  });
  const [isAdding, setIsAdding] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [selectedSection, setSelectedSection] = useState<string>('ALL');

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

  // 新增子项专用 Modal 弹窗 State
  const [isAddChildModalOpen, setIsAddChildModalOpen] = useState(false);
  const [targetParentNode, setTargetParentNode] = useState<CostItemNode | null>(null);
  const [childFormName, setChildFormName] = useState('');
  const [childFormBrand, setChildFormBrand] = useState('');
  const [childFormModel, setChildFormModel] = useState('');
  const [childFormManufacturer, setChildFormManufacturer] = useState('');
  const [childFormSpec, setChildFormSpec] = useState('');
  const [childFormQty, setChildFormQty] = useState<number>(1);
  const [childFormUnit, setChildFormUnit] = useState('台');
  const [childFormPrice, setChildFormPrice] = useState<number>(0);
  const [childFormPerSetQty, setChildFormPerSetQty] = useState<number>(1);
  const [childFormRemark, setChildFormRemark] = useState('');

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
  const isBusy = isRetrying || isExtractingEquipment;

  // 成本模式优先展示测算结果；仅清单模式必须直接展示最新工程提取树。
  useEffect(() => {
    const costItems = normalizeCostItems(costAnalysis?.items);
    setItems(!isEquipmentOnly && costItems.length > 0 ? costItems : normalizeCostItems(equipmentList));
  }, [costAnalysis, equipmentList, isEquipmentOnly]);

  // 提取数据中实际包含的所有分标段/分区域名称（忠实保持标书原始出现的自然先后顺序）
  const availableSections = React.useMemo(() => {
    const list: string[] = [];
    const set = new Set<string>();
    let hasUnassigned = false;

    (items || []).forEach(it => {
      const normalized = normalizeSectionName(it?.section_name);
      if (normalized) {
        if (!set.has(normalized)) {
          set.add(normalized);
          list.push(normalized);
        }
      } else {
        hasUnassigned = true;
      }
    });
    
    // 若存在其他明确区域，同时又存在未指定区域的独立项，追加通用分项分类
    if (set.size > 0 && hasUnassigned) {
      list.push('通用及其他分项');
    }

    // 忠实保留标书章节原本的自然出现先后顺序 (Natural Order)
    return list;
  }, [items, equipmentList]);

  // 当 items 或 availableSections 变更时，自动校准悬空的 selectedSection 状态
  useEffect(() => {
    if (selectedSection !== 'ALL' && availableSections.length > 0 && !availableSections.includes(selectedSection)) {
      setSelectedSection('ALL');
    }
  }, [availableSections, selectedSection]);

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
      const nodeKey = item.id ? `item_${item.id}` : `node_${idx}_${nodeName}`;
      
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
      return sameRoot && sameSection;
    };

    let recoveredHierarchyCount = 0;

    // 2. 就近向上回溯挂载算法（Backward Scope Matching）
    // 纯通用树构建算法：解决同名子节点挂载冲突，支持任意 N 级嵌套树结构
    const rootNodes: CostItemNode[] = [];
    let totalChildren = 0;

    for (let i = 0; i < allNodes.length; i++) {
      const node = allNodes[i];
      let parentName = node.parent_item;

      if (parentName) {
        // 倒序向上查找最近的直接父节点
        let foundParent: CostItemNode | null = null;
        for (let j = i - 1; j >= 0; j--) {
          const prev = allNodes[j];
          const prevName = String(prev.name || '').trim();

          // 名称匹配：精确匹配，或候选父节点全称包含子项指定的父项名称（如 "4(九) 铁附件、电缆防火封堵" 包含 "铁附件、电缆防火封堵"）
          // 严禁 parentName.includes(prevName)，防止短名称同级兄弟项（如 "铁附件"）误匹配复合名称父项（如 "铁附件、电缆防火封堵"）
          const nameMatches = prevName === parentName || prevName.includes(parentName);
          const nodeRoot = node.root_item ? String(node.root_item).trim() : '';
          const prevRoot = prev.root_item ? String(prev.root_item).trim() : '';
          const rootMatches = !nodeRoot || !prevRoot || nodeRoot === prevRoot || nodeRoot === prevName || prevName.includes(nodeRoot);
          const sectionMatches = !node.section_name || !prev.section_name || node.section_name === prev.section_name || node.section_name === '通用及其他分项';
          
          if (nameMatches && rootMatches && sectionMatches && prev !== node) {
            foundParent = prev;
            break;
          }
        }

        if (foundParent) {
          // 子节点若缺失分部，自动向上继承父节点分部
          if ((!node.section_name || node.section_name === '通用及其他分项') && foundParent.section_name && foundParent.section_name !== '通用及其他分项') {
            node.section_name = foundParent.section_name;
          }
          foundParent.children = foundParent.children || [];
          foundParent.children.push(node);
          totalChildren += 1;
        } else {
          // parent_item 文本无法命中时，回退到模型已经明确给出的层级证据。
          const currentLevel = Number(node.tree_level) || 1;
          if (currentLevel > 1) {
            const levelParent = allNodes
              .slice(0, i)
              .reverse()
              .find((prev) => Number(prev.tree_level) === currentLevel - 1 && isSameHierarchyScope(node, prev));
            if (levelParent) {
              node.parent_item = levelParent.name;
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
          const levelParent = allNodes
            .slice(0, i)
            .reverse()
            .find((prev) => Number(prev.tree_level) === currentLevel - 1 && isSameHierarchyScope(node, prev));
          if (levelParent) {
            node.parent_item = levelParent.name;
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

    // 3.5 标记父子互斥状态与锁（isLockedByParent, hasModifiedChildren, isLockedByChildren）
    const markMutualExclusion = (node: CostItemNode, parentModified: boolean) => {
      const isSelfParentModified = Boolean(node.is_parent_modified || node.pricing_mode === 'parent');
      node.isLockedByParent = parentModified;

      if (node.children && node.children.length > 0) {
        let anyChildModified = false;
        node.children.forEach(child => {
          markMutualExclusion(child, parentModified || isSelfParentModified);
          if (child.is_child_modified || child.is_custom_added || child.hasModifiedChildren || (child.match_quality === '手动修改' && !child.is_parent_modified)) {
            anyChildModified = true;
          }
        });
        node.hasModifiedChildren = anyChildModified;
        // 若下属子项被修改/添加，则父项直接修改被锁定（由子项自底向上汇总驱动）
        node.isLockedByChildren = anyChildModified;
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
        const isParentModified = Boolean(node.is_parent_modified || node.pricing_mode === 'parent');
        const directChildCount = node.children.length;
        const missingCount = Math.max(0, directChildCount - childrenWithPriceCount);

        if (isSelfEditing) {
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
        } else if (node.ref_price > 0 && node.match_quality !== '未匹配' && node.match_quality !== '成套汇总') {
          // 子项无金额，母项自身有打包统价
          const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
          node.subtotal = Number((safeQty * (node.ref_price || 0)).toFixed(2));
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        } else {
          node.subtotal = 0;
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        }

        return node.subtotal || 0;
      } else {
        // 叶子节点
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

  // 根据选中的分标段/分区域进行视图筛选（纯数据驱动）
  const filteredTreeData = React.useMemo(() => {
    if (selectedSection === 'ALL' || !availableSections.includes(selectedSection)) {
      return treeData;
    }
    return treeData.filter(node => {
      if (node.section_name === selectedSection) return true;
      if (node.children && node.children.some(c => c.section_name === selectedSection)) return true;
      return false;
    });
  }, [treeData, selectedSection, availableSections]);

  // 受控展开行 Keys
  const [expandedRowKeys, setExpandedRowKeys] = useState<readonly React.Key[]>([]);

  // 首次加载或切换到新的清单数据时，默认展开一级成套主标的，
  // 让父子关系直接可见；用户手动折叠后不再被此逻辑强制展开。
  const autoExpandedDataSignatureRef = React.useRef('');
  useEffect(() => {
    // 将展示模式纳入签名，避免从成本结果切换到原始清单时因根节点相同而跳过展开。
    const dataSignature = `${isEquipmentOnly ? 'equipment' : 'cost'}:${treeData.map(node => String(node.key)).join('|')}`;
    if (!dataSignature || dataSignature === autoExpandedDataSignatureRef.current) {
      return;
    }

    autoExpandedDataSignatureRef.current = dataSignature;
    const parentKeysToExpand = isEquipmentOnly
      ? allParentKeys
      : treeData
        .filter(node => Boolean(node.children && node.children.length > 0))
        .map(node => node.key);
    if (parentKeysToExpand.length > 0) {
      setExpandedRowKeys(parentKeysToExpand);
    }
  }, [treeData, allParentKeys, isEquipmentOnly]);

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
    if (record.isParent) {
      if (record.isLockedByChildren) {
        message.warning(`成套设备「${record.name}」已修改下属子项，当前价格由子项自动汇总。如需直接修改父项，请先点击「重置子项」。`, 4);
        return;
      }
      // 若该母项当前未展开，自动为用户展开下属子项方便查看
      if (!expandedRowKeys.includes(record.key)) {
        setExpandedRowKeys(prev => Array.from(new Set([...prev, record.key])));
      }
    } else {
      if (record.isLockedByParent) {
        message.warning(`该子项所属的成套设备「${record.parent_item || '父项'}」已启用父项自定义定价，子项已锁定。如需修改子项，请先点击「重置父项」。`, 4);
        return;
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
      if (record.parent_item) {
        const parentIdx = items.findIndex(it => it.name === record.parent_item || (it.children && it.name === record.parent_item));
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

  // 重置子项：恢复该成套设备下全部子项初始对标基线数据（清除新增子项并恢复修改项），并解锁父项直接修改
  const handleResetChildren = (record: CostItemNode) => {
    const parentName = record.name;
    const updatedItems: any[] = [];

    items.forEach((item, idx) => {
      const isChildOfThisParent = item.parent_item === parentName || item.root_item === parentName;
      if (isChildOfThisParent) {
        // 如果是手动添加的子项，则直接移除
        if (item.is_custom_added) {
          return;
        }
        // 恢复原始子项属性
        const restoredItem = { ...item };
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
        restoredItem.match_quality = restoredItem.raw_match_quality || (restoredItem.ref_price > 0 ? '精准匹配' : '未匹配');
        restoredItem.is_child_modified = false;
        updatedItems.push(restoredItem);
      } else {
        if (idx === record.originalIndex) {
          const restoredParent = { ...item };
          restoredParent.is_parent_modified = false;
          restoredParent.pricing_mode = 'children';
          updatedItems.push(restoredParent);
        } else {
          updatedItems.push(item);
        }
      }
    });

    setItems(updatedItems);
    handleCancelEdit();
    saveCostAnalysis(updatedItems);
    message.success(`已重置成套设备「${record.name}」的全部子项，已恢复初始对标状态并解锁父项直接修改！`, 4);
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

  // 打开添加子项弹窗
  const handleOpenAddChildModal = (parentRecord: CostItemNode) => {
    if (parentRecord.is_parent_modified) {
      message.warning(`成套设备「${parentRecord.name}」已启用父项自定义定价。如需添加子项，请先重置父项。`, 4);
      return;
    }
    setTargetParentNode(parentRecord);
    setChildFormName('');
    setChildFormBrand(parentRecord.brand || parentRecord.matched_brand || '');
    setChildFormModel('');
    setChildFormManufacturer(parentRecord.manufacturer || parentRecord.matched_manufacturer || '');
    setChildFormSpec('');
    setChildFormQty(1);
    setChildFormUnit(parentRecord.unit === '面' || parentRecord.unit === '台' ? '台' : '件');
    setChildFormPrice(0);
    setChildFormPerSetQty(1);
    setChildFormRemark('');
    setIsAddChildModalOpen(true);
  };

  // 提交保存新增的子项
  const handleSaveNewChildItem = () => {
    if (!targetParentNode || !childFormName.trim()) {
      message.error('请输入子项标的物/设备名称');
      return;
    }

    const brandVal = childFormBrand.trim();
    const modelVal = childFormModel.trim();
    const mfgVal = childFormManufacturer.trim();
    const specVal = childFormSpec.trim();
    const remarkVal = childFormRemark.trim();

    const newChild: any = {
      name: childFormName.trim(),
      spec_requirement: specVal || modelVal || `成套设备「${targetParentNode.name}」下属分项`,
      qty: childFormQty > 0 ? childFormQty : 1,
      unit: childFormUnit.trim() || '台',
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
      comparison_note: `成套设备「${targetParentNode.name}」下手动新增子项`,
      remark: remarkVal,
      key_parameters: [],
      brand_requirements: brandVal,
      parent_item: targetParentNode.name,
      root_item: targetParentNode.root_item || targetParentNode.name,
      tree_level: (targetParentNode.tree_level || 1) + 1,
      per_set_qty: childFormPerSetQty > 0 ? childFormPerSetQty : (childFormQty > 0 ? childFormQty : 1),
      per_set_quantity: childFormPerSetQty > 0 ? childFormPerSetQty : (childFormQty > 0 ? childFormQty : 1),
      section_name: targetParentNode.section_name || null,
      is_custom_added: true,
      is_child_modified: true,
      raw_ref_price: 0,
      raw_qty: childFormQty > 0 ? childFormQty : 1,
      raw_unit: childFormUnit.trim() || '台',
      raw_name: childFormName.trim(),
      raw_brand: brandVal,
      raw_model: modelVal,
      raw_manufacturer: mfgVal,
      raw_spec: specVal,
      raw_match_quality: '手动添加'
    };

    // 寻找插入位置：在该父项及其所有已有子项的最后位置插入
    let insertIdx = targetParentNode.originalIndex + 1;
    for (let i = targetParentNode.originalIndex + 1; i < items.length; i++) {
      if (items[i].parent_item === targetParentNode.name || items[i].root_item === targetParentNode.name) {
        insertIdx = i + 1;
      } else {
        break;
      }
    }

    const updatedItems = [...items];
    const parentIdx = targetParentNode.originalIndex;
    if (parentIdx >= 0 && parentIdx < updatedItems.length) {
      updatedItems[parentIdx] = {
        ...updatedItems[parentIdx],
        is_parent_modified: false,
        pricing_mode: 'children'
      };
    }
    updatedItems.splice(insertIdx, 0, newChild);

    setItems(updatedItems);
    setExpandedRowKeys(prev => Array.from(new Set([...prev, targetParentNode.key])));
    setIsAddChildModalOpen(false);
    saveCostAnalysis(updatedItems);
    message.success(`已成功为「${targetParentNode.name}」添加子项「${childFormName.trim()}」！`, 4);
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
    let rootName: string | null = null;
    let level = 1;
    let sectionVal = selectedSection !== 'ALL' ? selectedSection : null;

    if (newParentItem) {
      const parentObj = treeData.find(n => n.name === newParentItem);
      parentName = newParentItem;
      rootName = parentObj?.root_item || newParentItem;
      level = parentObj ? (parentObj.tree_level || 1) + 1 : 2;
      sectionVal = parentObj?.section_name || sectionVal;
    }

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
      raw_match_quality: '手动添加'
    };

    let updatedItems = [...items];
    if (parentName) {
      // 挂载到父项：寻找该父项及其子项的最后位置插入
      const parentIdx = items.findIndex(it => it.name === parentName);
      if (parentIdx >= 0) {
        let insertIdx = parentIdx + 1;
        for (let i = parentIdx + 1; i < items.length; i++) {
          if (items[i].parent_item === parentName || items[i].root_item === parentName) {
            insertIdx = i + 1;
          } else {
            break;
          }
        }
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
    const updatedItems = items.filter((_, idx) => idx !== indexToDelete);
    setItems(updatedItems);
    if (editingIndex === indexToDelete) {
      setEditingKey(null);
      setEditingIndex(null);
    }
    saveCostAnalysis(updatedItems);
  };

  // 持久化保存到后端
  const saveCostAnalysis = async (currentItems: any[]) => {
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

  // Ant Design 列配置
  const columns: ColumnsType<CostItemNode> = [
    {
      title: '标的/设备名称 & 标书规格',
      dataIndex: 'name',
      key: 'name',
      width: 400,
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const keyParams = Array.isArray(record.key_parameters) ? record.key_parameters : [];
        const isManual = record.match_quality === '手动添加' || record.is_custom_added;
        const isManualEdit = record.match_quality === '手动修改' || record.is_child_modified;
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent');
        const level = record.tree_level || 1;
        // 严格 3 色循环阶梯：4 复用 1(蓝)、5 复用 2(靛)、6 复用 3(天蓝)...
        const colorTier = (((level - 1) % 3) + 1);

        return (
          <div className="py-1.5">
            {/* 多级 BOM 层级与总成标识 */}
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
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

            {/* 所属分项提示徽章：只要后端提供了语义分项就显示，不依赖分项数量。 */}
            {record.section_name && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[11px] text-cyan-800 bg-cyan-50/90 px-2.5 py-0.5 rounded-md inline-flex items-center gap-1 font-bold border border-cyan-300/80 shadow-2xs">
                  <span>📍 所属分项: <strong className="font-extrabold text-cyan-950">{record.section_name}</strong></span>
                </span>
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
      width: 320,
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !record.isRollupPrice && !record.is_parent_modified);
        const isManual = record.match_quality === '手动添加';
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent');

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
      width: 130,
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const isExact = record.match_quality === '精准匹配';
        const isManual = record.match_quality === '手动添加';
        const isManualEdit = record.match_quality === '手动修改';
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent');
        const isRollup = (record.isRollupPrice || record.match_quality === '成套汇总' || record.match_quality === '子项汇总') && !isParentCustom;
        const note = record.comparison_note || '';
        const isSpecDiff = note.includes("规格不同") || note.includes("量纲不一") || note.includes("差异") || note.includes("仅参考") || note.includes("不一致") || note.includes("偏离");
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !isRollup && !isParentCustom);

        if (isEditing) {
          return <Tag color="processing">修改中</Tag>;
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
      width: 140,
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;

        if (isEditing) {
          return (
            <div className="flex items-center gap-1">
              <InputNumber
                min={0.01}
                step="any"
                value={editQty}
                onChange={(v) => setEditQty(v || 1)}
                size="small"
                className="w-16 text-center font-bold"
              />
              <Input
                value={editUnit}
                onChange={(e) => setEditUnit(e.target.value)}
                placeholder="单位"
                size="small"
                className="w-12 text-center"
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
      width: 150,
      align: 'right',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent');

        if (isEditing) {
          return (
            <div className="flex flex-col items-end">
              <InputNumber
                min={0}
                step="any"
                prefix="¥"
                value={editPrice}
                onChange={(v) => setEditPrice(v || 0)}
                size="small"
                className="w-28 font-bold"
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

        if (record.isLockedByParent) {
          return (
            <div className="flex flex-col items-end">
              <span className="text-slate-400 font-normal text-xs">{currentRefPrice > 0 ? `¥${currentRefPrice.toLocaleString()}` : '--'}</span>
              <span className="text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 mt-0.5 font-normal">
                已统入父项价
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
      width: 150,
      align: 'right',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentQty = isEditing ? editQty : (record.qty !== null && record.qty !== undefined ? Number(record.qty) : 1);
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const itemSubtotal = record.subtotal !== undefined ? record.subtotal : currentQty * currentRefPrice;
        const isParentCustom = record.isParent && (record.is_parent_modified || record.pricing_mode === 'parent');

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
            <span className={`font-bold whitespace-nowrap ${record.isLockedByParent ? 'text-slate-400' : 'text-blue-600'}`}>
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
      width: 180,
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
      width: 130,
      align: 'center',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;

        if (isEditing) {
          return (
            <div className="flex items-center justify-center gap-1">
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

          return (
            <div className="flex items-center justify-center gap-1">
              {/* 添加子项按钮 */}
              {isParentModified ? (
                <Tooltip title="父项已启用自定义定价，子项已锁定。如需添加子项，请先重置父项">
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

              {/* 编辑父项按钮 */}
              {hasModifiedChildren ? (
                <Tooltip title="下属子项已修改，成套价格由子项自动汇总。如需直接修改父项，请先点击「重置子项」">
                  <Button
                    type="text"
                    size="small"
                    disabled
                    icon={<EditOutlined className="text-slate-300 cursor-not-allowed" />}
                  />
                </Tooltip>
              ) : (
                <Tooltip title={isParentModified ? "修改成套设备价格与属性" : "直接修改成套设备价格（保存后将锁定子项）"}>
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined className={isParentModified ? "text-purple-600 hover:text-purple-800" : "text-indigo-500 hover:text-indigo-700"} />}
                    onClick={() => handleStartEdit(record)}
                  />
                </Tooltip>
              )}

              {/* 重置父项按钮（仅在父项已修改时显示） */}
              {isParentModified && (
                <Tooltip title="重置父项自定义修改，恢复初始对标价格并解锁子项">
                  <Popconfirm
                    title="确定重置父项？"
                    description="将恢复父项初始数据，并解锁下属子项修改与添加权限。"
                    onConfirm={() => handleResetParent(record)}
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

              {/* 重置子项按钮（仅在子项被修改时显示） */}
              {hasModifiedChildren && (
                <Tooltip title="重置全部子项，恢复初始状态并解锁父项直接修改">
                  <Popconfirm
                    title="确定重置所有子项？"
                    description="将恢复该成套设备下全部子项初始对标清单与价格，并解锁父项直接修改。"
                    onConfirm={() => handleResetChildren(record)}
                    okText="确定重置"
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
          <div className="flex items-center justify-center gap-1">
            {isLockedByParent ? (
              <Tooltip title="所属成套设备已启用父项自定义定价，子项已锁定。如需修改子项，请先在上方重置父项">
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
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 px-2 py-1 ml-1 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="重新提取设备清单"
                  title="重新读取原文并提取设备清单，完成后等待手动进行价格匹配"
                >
                  <FileSearchOutlined />
                  <span>重新提取设备清单</span>
                </button>
              )}
              {onReextract && (
                <button 
                  onClick={(e) => { e.stopPropagation(); onReextract(); }}
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 px-2 py-1 ml-1 text-xs font-semibold text-slate-500 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="重新匹配 BOM 清单"
                  title="重新匹配 BOM 清单，并重新计算参考单价与成本"
                >
                  <ReloadOutlined className="text-sm" />
                  <span>重新匹配 BOM 清单</span>
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

                {/* 多区域/多分标段快速筛选工具栏 (当且仅当存在至少2个及以上不同分部时才展示) */}
                {availableSections.length > 1 && (
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
        <div className="cost-table-ant rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <style>{`
            .cost-table-ant .ant-table-thead > tr > th {
              background: #f8fafc !important;
              font-weight: 800 !important;
              color: #475569 !important;
              border-bottom: 2px solid #cbd5e1 !important;
              font-size: 12px !important;
              text-transform: uppercase !important;
              letter-spacing: 0.05em !important;
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
          {hasItems ? (
            <Table<CostItemNode>
              columns={columns}
              dataSource={filteredTreeData}
              pagination={false}
              scroll={{ x: 1100 }}
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
                    options={treeData.filter(n => n.isParent || n.tree_level === 1).map(n => ({
                      label: `${n.name} (L${n.tree_level || 1})`,
                      value: n.name
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
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
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
                    className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                  />
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
              <span>为成套设备「{targetParentNode?.name}」添加子标的物 / 分项</span>
            </div>
          }
          open={isAddChildModalOpen}
          onOk={handleSaveNewChildItem}
          onCancel={() => setIsAddChildModalOpen(false)}
          okText="确认添加并自动汇总"
          cancelText="取消"
          width={650}
          destroyOnClose
          okButtonProps={{ className: 'bg-blue-600 hover:bg-blue-700 font-bold rounded-xl' }}
          cancelButtonProps={{ className: 'rounded-xl font-bold' }}
        >
          <div className="py-2 space-y-3.5 text-xs">
            <div className="bg-blue-50/80 p-2.5 rounded-xl border border-blue-200/80 text-blue-900 leading-relaxed font-medium">
              💡 <strong>说明：</strong>新增的子项将自动挂载至「<strong>{targetParentNode?.name}</strong>」下，保存后将自动触发成套设备价格自底向上汇总重新计算。
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
                  value={childFormPerSetQty}
                  onChange={(v) => {
                    const pQty = v || 1;
                    setChildFormPerSetQty(pQty);
                    if (targetParentNode?.qty) {
                      setChildFormQty(Number((pQty * (targetParentNode.qty || 1)).toFixed(2)));
                    }
                  }}
                  className="w-full font-bold"
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
                  value={childFormQty}
                  onChange={(v) => setChildFormQty(v || 1)}
                  className="w-full font-bold"
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
                  prefix="¥"
                  placeholder="0.00"
                  value={childFormPrice}
                  onChange={(v) => setChildFormPrice(v || 0)}
                  className="w-full font-bold text-base text-blue-700"
                />
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
      </div>
    </ConfigProvider>
  );
}
