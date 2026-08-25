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
  UpOutlined
} from '@ant-design/icons';
import { apiFetch, API_BASE_URL } from '../utils/api';

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
}

interface CostTableProps {
  documentId?: string;
  equipmentList?: any[];
  financial?: any;
  costAnalysis?: any;
  onReextract?: () => void;
  onReextractEquipment?: () => void;
  onCostUpdated?: (updatedData: any) => void;
  isRetrying?: boolean;
  isExtractingEquipment?: boolean;
}

/**
 * 分部/工程大类规范化函数 (Section Normalization)
 * 忠实保留标书提取的原始 section_name，去除多余空白，杜绝任何硬编码与人为破坏性截断。
 */
export function normalizeSectionName(rawSec: string | null | undefined): string | null {
  if (!rawSec || typeof rawSec !== 'string') return null;
  const s = rawSec.trim();
  return s || null;
}

export function CostTable({
  documentId,
  equipmentList = [],
  financial = {},
  costAnalysis = {},
  onReextract,
  onReextractEquipment,
  onCostUpdated,
  isRetrying = false,
  isExtractingEquipment = false
}: CostTableProps) {
  const [items, setItems] = useState<any[]>(costAnalysis?.items || []);
  const [isAdding, setIsAdding] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
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

  // 新增自定义费用分项表单 State
  const [newName, setNewName] = useState('');
  const [newBrand, setNewBrand] = useState('');
  const [newModel, setNewModel] = useState('');
  const [newManufacturer, setNewManufacturer] = useState('');
  const [newSpec, setNewSpec] = useState('');
  const [newRemark, setNewRemark] = useState('');
  const [newQty, setNewQty] = useState<number>(1);
  const [newUnit, setNewUnit] = useState('项');
  const [newPrice, setNewPrice] = useState<number>(0);
  const isBusy = isRetrying || isExtractingEquipment;

  // 当外部传入的 costAnalysis 发生重测算变化时更新本地 items
  useEffect(() => {
    if (costAnalysis && costAnalysis.items) {
      setItems(costAnalysis.items);
    }
  }, [costAnalysis]);

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
  }, [items]);

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
      };
      return node;
    });

    // 2. 就近向上回溯挂载算法（Backward Scope Matching）
    // 纯通用树构建算法：解决同名子节点挂载冲突，支持任意 N 级嵌套树结构
    const rootNodes: CostItemNode[] = [];
    let totalChildren = 0;

    for (let i = 0; i < allNodes.length; i++) {
      const node = allNodes[i];
      const parentName = node.parent_item;

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
          // 向前未找到则作为根节点
          rootNodes.push(node);
        }
      } else {
        rootNodes.push(node);
      }
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
        const directChildCount = node.children.length;
        const missingCount = Math.max(0, directChildCount - childrenWithPriceCount);

        if (isSelfEditing && editPrice > 0) {
          // 用户当前正直接编辑该母项单价
          const safeQty = node.qty && node.qty > 0 ? Number(node.qty) : 1;
          node.subtotal = Number((safeQty * editPrice).toFixed(2));
          node.ref_price = editPrice;
          node.isRollupPrice = false;
          node.isPartialRollup = false;
        } else if (childrenSubtotalSum > 0) {
          // 子项有金额 -> 始终无条件由子项自底向上汇总实时驱动！
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
  let dynamicStatusText = costAnalysis.budget_status || '';
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

  // 开启行内编辑模式
  const handleStartEdit = (record: CostItemNode) => {
    if (record.isParent) {
      // 若该母项当前未展开，自动为用户展开下属子项方便修改
      if (!expandedRowKeys.includes(record.key)) {
        setExpandedRowKeys(prev => Array.from(new Set([...prev, record.key])));
      }
      message.info(`成套设备「${record.name}」价格由下属 ${record.childCount || 0} 个子项自动汇总计算，单价已锁定，请在下方子项修改价格。`, 4);
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

    // 若非成套母项，才允许直接更新自身单价与小计；成套母项的价格始终强制由下属子项求和驱动
    if (!record.isParent) {
      targetItem.ref_price = editPrice >= 0 ? editPrice : 0;
      targetItem.subtotal = targetItem.qty * targetItem.ref_price;

      if (targetItem.ref_price > 0 && (targetItem.match_quality === '未匹配' || !targetItem.match_quality)) {
        targetItem.match_quality = '手动修改';
      }
    }

    updatedItems[targetIdx] = targetItem;
    setItems(updatedItems);
    setEditingKey(null);
    setEditingIndex(null);
    saveCostAnalysis(updatedItems);
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

    const newItem = {
      name: newName.trim(),
      spec_requirement: specVal || modelVal || '自定义费用分项（如人工/售后维保费）',
      qty: newQty > 0 ? newQty : 1,
      unit: newUnit.trim() || '项',
      ref_price: newPrice >= 0 ? newPrice : 0,
      subtotal: (newQty > 0 ? newQty : 1) * (newPrice >= 0 ? newPrice : 0),
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
      section_name: selectedSection !== 'ALL' ? selectedSection : null
    };

    const updatedItems = [...items, newItem];
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
            item_code: item.item_code || null,
            name: item.name,
            spec_requirement: item.spec_requirement || '',
            qty: item.qty !== null && item.qty !== undefined ? item.qty : 1,
            unit: item.unit || null,
            ref_price: item.ref_price || 0,
            matched_name: item.matched_name || item.name,
            matched_brand: item.matched_brand || item.brand || '',
            matched_model: item.matched_model || item.model || '',
            matched_manufacturer: item.matched_manufacturer || item.manufacturer || '',
            brand: item.brand || item.matched_brand || '',
            model: item.model || item.matched_model || '',
            manufacturer: item.manufacturer || item.matched_manufacturer || '',
            key_parameters: item.key_parameters || [],
            brand_requirements: item.brand_requirements || item.brand || '',
            match_quality: item.match_quality || '手动添加',
            warning: item.warning || '',
            comparison_note: item.comparison_note || '',
            remark: item.remark || '',
            parent_item: item.parent_item || null,
            root_item: item.root_item || null,
            tree_level: item.tree_level || 1,
            per_set_qty: item.per_set_qty || item.per_set_quantity || null,
            per_set_quantity: item.per_set_quantity || item.per_set_qty || null,
            section_name: item.section_name || null
          })),
          analysis_summary: costAnalysis.analysis_summary || '已手动调整 BOM 成本报价项与指导单价。'
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

  const hasCostData = items.length > 0;

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
        const isManual = record.match_quality === '手动添加';
        const isManualEdit = record.match_quality === '手动修改';
        const level = record.tree_level || 1;
        // 严格 3 色循环阶梯：4 复用 1(蓝)、5 复用 2(靛)、6 复用 3(天蓝)...
        const colorTier = (((level - 1) % 3) + 1);

        return (
          <div className="py-1.5">
            {/* 多级 BOM 层级与总成标识 */}
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              {record.isParent ? (
                colorTier === 1 ? (
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

            {/* 所属区域/标段提示徽章 (仅在存在多个不同分部时显示，单清单项目不显示以避免视觉冗余) */}
            {availableSections.length > 1 && record.section_name && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[11px] text-cyan-800 bg-cyan-50/90 px-2.5 py-0.5 rounded-md inline-flex items-center gap-1 font-bold border border-cyan-300/80 shadow-2xs">
                  <span>📍 所属区域: <strong className="font-extrabold text-cyan-950">{record.section_name}</strong></span>
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
                  {(isManual || isManualEdit) && (
                    <span className="bg-purple-50 text-purple-600 border border-purple-200 text-[10px] px-1.5 py-0.5 rounded font-bold ml-1">
                      {isManual ? '手动新增' : '手动修改'}
                    </span>
                  )}
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
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !record.isRollupPrice);
        const isManual = record.match_quality === '手动添加';

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
        const isRollup = record.isRollupPrice || record.match_quality === '成套汇总' || record.match_quality === '子项汇总';
        const note = record.comparison_note || '';
        const isSpecDiff = note.includes("规格不同") || note.includes("量纲不一") || note.includes("差异") || note.includes("仅参考") || note.includes("不一致") || note.includes("偏离");
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const isUnmatched = currentRefPrice <= 0 || (record.match_quality === '未匹配' && !isRollup);

        if (isEditing) {
          return <Tag color="processing">修改中</Tag>;
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

        if (isEditing) {
          if (record.isParent) {
            return (
              <div className="flex flex-col items-end">
                <Tooltip title="成套主标的物价格由下属子项自动汇总计算，禁止手动修改单价，请在下方修改子项">
                  <InputNumber
                    disabled
                    prefix="¥"
                    value={record.ref_price ? Number(record.ref_price) : 0}
                    size="small"
                    className="w-28 font-bold bg-slate-100/80 cursor-not-allowed text-indigo-700"
                  />
                </Tooltip>
                <span className="text-[10px] text-slate-400 mt-0.5 font-medium flex items-center gap-0.5">
                  <span>🔒</span>
                  <span>子项汇总锁定</span>
                </span>
              </div>
            );
          }

          return (
            <InputNumber
              min={0}
              step="any"
              prefix="¥"
              value={editPrice}
              onChange={(v) => setEditPrice(v || 0)}
              size="small"
              className="w-28 font-bold"
            />
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
      width: 150,
      align: 'right',
      render: (_: any, record: CostItemNode) => {
        const isEditing = editingKey === record.key;
        const currentQty = isEditing ? editQty : (record.qty !== null && record.qty !== undefined ? Number(record.qty) : 1);
        const currentRefPrice = isEditing ? editPrice : (record.ref_price ? Number(record.ref_price) : 0);
        const itemSubtotal = record.subtotal !== undefined ? record.subtotal : currentQty * currentRefPrice;

        if (itemSubtotal > 0) {
          if (record.isParent) {
            return (
              <div className="flex flex-col items-end">
                <span className={`font-black text-sm whitespace-nowrap ${record.isPartialRollup ? 'text-amber-800' : 'text-indigo-800'}`}>
                  ¥{itemSubtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
                {record.isRollupPrice && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                    record.isPartialRollup ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-indigo-50/90 text-indigo-600 border-indigo-200'
                  }`}>
                    {record.isPartialRollup ? '阶段小计 (待补全)' : '成套总计'}
                  </span>
                )}
              </div>
            );
          }
          return (
            <span className="font-bold text-blue-600 whitespace-nowrap">
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
      width: 210,
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
      width: 90,
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

        return (
          <div className="flex items-center justify-center gap-1">
            <Tooltip title={record.isParent ? `成套设备价格由下属 ${record.childCount || 0} 个子项自动汇总（单价锁定，点击可修改名称/数量）` : '修改单价与数量'}>
              <Button
                type="text"
                size="small"
                icon={<EditOutlined className={record.isParent ? 'text-indigo-400 hover:text-indigo-600' : 'text-slate-400 hover:text-blue-600'} />}
                onClick={() => handleStartEdit(record)}
              />
            </Tooltip>
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
              {isExtractingEquipment ? '正在重新提取设备清单并计算成本...' : '正在重新对接价格库并计算成本...'}
            </span>
          </div>
        )}

        {/* 顶部标题与摘要栏 */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-xl font-extrabold text-slate-800 flex items-center gap-2 mb-1">
              <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
              智能 BOM 成本测算与对标匹配
              {onReextractEquipment && (
                <button
                  onClick={(e) => { e.stopPropagation(); onReextractEquipment(); }}
                  disabled={isBusy}
                  className="inline-flex items-center gap-1.5 px-2 py-1 ml-1 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-md transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="重新提取设备清单"
                  title="重新读取原文并提取设备清单，完成后自动重新核算成本"
                >
                  <FileSearchOutlined />
                  <span>重新提取设备清单</span>
                </button>
              )}
              {onReextract && (
                <button 
                  onClick={(e) => { e.stopPropagation(); onReextract(); }}
                  disabled={isBusy}
                  className="p-1.5 ml-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors cursor-pointer"
                  title="重新对接价格库并测算成本"
                >
                  <ReloadOutlined className="text-sm" />
                </button>
              )}
            </h3>
            <p className="text-sm text-slate-500 font-medium">
              {hasCostData 
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
              ) : (costAnalysis.budget_limit && (
                <div className="text-xs text-slate-400 font-medium mt-0.5">
                  预算限额: {costAnalysis.budget_limit}
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
        {costAnalysis.analysis_summary && (
          <div className="mb-4 p-3.5 bg-blue-50/60 rounded-2xl border border-blue-100 text-xs text-slate-700 leading-relaxed font-medium flex items-start gap-2">
            <span className="text-blue-500 text-sm">💡</span>
            <div>
              <span className="font-bold text-blue-900 mr-1">专家评估推导:</span>
              {costAnalysis.analysis_summary}
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
        {hasCostData && (
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
                      全部区域 ({items.length})
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
          {hasCostData ? (
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
      </div>
    </ConfigProvider>
  );
}
