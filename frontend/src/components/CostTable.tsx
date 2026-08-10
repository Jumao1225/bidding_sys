import React, { useState, useEffect } from 'react';
import { apiFetch, API_BASE_URL } from '../utils/api';

interface CostTableProps {
  documentId?: string;
  equipmentList?: any[];
  costAnalysis?: any;
  onReextract?: () => void;
  onCostUpdated?: (updatedData: any) => void;
  isRetrying?: boolean;
}

export function CostTable({
  documentId,
  equipmentList = [],
  costAnalysis = {},
  onReextract,
  onCostUpdated,
  isRetrying = false
}: CostTableProps) {
  const [items, setItems] = useState<any[]>(costAnalysis?.items || []);
  const [isAdding, setIsAdding] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 行行内编辑 State
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editQty, setEditQty] = useState<number>(1);
  const [editUnit, setEditUnit] = useState('台');
  const [editPrice, setEditPrice] = useState<number>(0);

  // 新增费用分项表单 State
  const [newName, setNewName] = useState('');
  const [newSpec, setNewSpec] = useState('');
  const [newQty, setNewQty] = useState<number>(1);
  const [newUnit, setNewUnit] = useState('项');
  const [newPrice, setNewPrice] = useState<number>(0);

  // 当外部传入的 costAnalysis 发生重测算变化时更新本地 items
  useEffect(() => {
    if (costAnalysis && costAnalysis.items) {
      setItems(costAnalysis.items);
    }
  }, [costAnalysis]);

  // 实时联动计算预估总成本
  const realTimeTotalCost = items.reduce((sum, item, idx) => {
    if (editingIndex === idx) {
      return sum + (editQty || 1) * (editPrice || 0);
    }
    const q = item.qty !== null && item.qty !== undefined ? Number(item.qty) : 1;
    const p = item.ref_price ? Number(item.ref_price) : 0;
    return sum + q * p;
  }, 0);

  const budgetStatus = costAnalysis.budget_status || '';
  const isBudgetExceeded = budgetStatus.includes('已超出');
  const isBudgetWarning = budgetStatus.includes('接近');

  // 开启行内编辑模式
  const handleStartEdit = (index: number, item: any) => {
    setEditingIndex(index);
    setEditName(item.name || '');
    setEditQty(item.qty !== null && item.qty !== undefined ? Number(item.qty) : 1);
    setEditUnit(item.unit || '台');
    setEditPrice(item.ref_price ? Number(item.ref_price) : 0);
  };

  // 确认修改单行价格与数量
  const handleSaveEdit = (index: number) => {
    const updatedItems = [...items];
    const targetItem = { ...updatedItems[index] };

    targetItem.name = editName.trim() || targetItem.name;
    targetItem.qty = editQty > 0 ? editQty : 1;
    targetItem.unit = editUnit.trim() || '台';
    targetItem.ref_price = editPrice >= 0 ? editPrice : 0;
    targetItem.subtotal = targetItem.qty * targetItem.ref_price;

    // 若原先未匹配但现在手工填了正单价，更新置信度标识
    if (targetItem.ref_price > 0 && (targetItem.match_quality === '未匹配' || !targetItem.match_quality)) {
      targetItem.match_quality = '手动修改';
    }

    updatedItems[index] = targetItem;
    setItems(updatedItems);
    setEditingIndex(null);

    // 自动保存落盘
    saveCostAnalysis(updatedItems);
  };

  // 添加自定义费用项
  const handleAddItem = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;

    const newItem = {
      name: newName.trim(),
      spec_requirement: newSpec.trim() || '自定义费用分项（如人工/售后维保费）',
      qty: newQty > 0 ? newQty : 1,
      unit: newUnit.trim() || '项',
      ref_price: newPrice >= 0 ? newPrice : 0,
      subtotal: (newQty > 0 ? newQty : 1) * (newPrice >= 0 ? newPrice : 0),
      matched_name: newName.trim(),
      matched_brand: '自定义',
      match_quality: '手动添加',
      comparison_note: '用户在卡片上手动新增的成本费用分项',
      key_parameters: [],
      brand_requirements: ''
    };

    const updatedItems = [...items, newItem];
    setItems(updatedItems);

    // 重置表单
    setNewName('');
    setNewSpec('');
    setNewQty(1);
    setNewUnit('项');
    setNewPrice(0);
    setIsAdding(false);

    // 自动触发持久化保存
    saveCostAnalysis(updatedItems);
  };

  // 删除某项费用分项
  const handleDeleteItem = (indexToDelete: number) => {
    const updatedItems = items.filter((_, idx) => idx !== indexToDelete);
    setItems(updatedItems);
    if (editingIndex === indexToDelete) {
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
            name: item.name,
            spec_requirement: item.spec_requirement || '',
            qty: item.qty,
            unit: item.unit || '项',
            ref_price: item.ref_price || 0,
            matched_name: item.matched_name || item.name,
            matched_brand: item.matched_brand || '',
            matched_model: item.matched_model || '',
            matched_manufacturer: item.matched_manufacturer || '',
            key_parameters: item.key_parameters || [],
            brand_requirements: item.brand_requirements || '',
            match_quality: item.match_quality || '手动添加',
            warning: item.warning || '',
            comparison_note: item.comparison_note || ''
          })),
          analysis_summary: costAnalysis.analysis_summary || '已手动调整 BOM 成本报价项与指导单价。'
        })
      });

      const result = await response.json();
      if (response.ok && result.code === 200) {
        setSaveMessage({ type: 'success', text: '最新报价与单价修改已实时保存落盘！' });
        if (onCostUpdated) {
          onCostUpdated(result.data);
        }
      } else {
        setSaveMessage({ type: 'error', text: result.detail || result.message || '保存失败' });
      }
    } catch (err: any) {
      setSaveMessage({ type: 'error', text: `网络或保存异常: ${err.message}` });
    } finally {
      setIsSaving(false);
      setTimeout(() => setSaveMessage(null), 3000);
    }
  };

  const hasCostData = items.length > 0;

  return (
    <div className={`bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md col-span-2 relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/50 backdrop-blur-[2px] rounded-3xl gap-2">
          <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <span className="text-xs font-bold text-blue-600">正在重新对接价格库并计算成本...</span>
        </div>
      )}

      {/* 顶部标题与摘要栏 */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h3 className="text-xl font-extrabold text-slate-800 flex items-center gap-2 mb-1">
            <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
            智能 BOM 成本测算与匹配
            {onReextract && (
              <button 
                onClick={(e) => { e.stopPropagation(); onReextract(); }}
                className="p-1.5 ml-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-md transition-colors"
                title="重新对接价格库并测算成本"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
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
          {budgetStatus && budgetStatus !== '预算未设置' && (
            <div className={`px-4 py-2 rounded-2xl text-xs font-bold border ${
              isBudgetExceeded 
                ? 'bg-rose-50 text-rose-600 border-rose-200' 
                : isBudgetWarning 
                  ? 'bg-amber-50 text-amber-600 border-amber-200' 
                  : 'bg-emerald-50 text-emerald-600 border-emerald-200'
            }`}>
              {isBudgetExceeded && '🚨 '}
              {isBudgetWarning && '⚠️ '}
              {!isBudgetExceeded && !isBudgetWarning && '✓ '}
              {budgetStatus}
            </div>
          )}

          {/* 实时预估总成本卡片 */}
          <div className="text-right bg-slate-50 p-3.5 px-5 rounded-2xl border border-slate-100 shadow-inner">
            <div className="text-xs font-bold text-slate-500 mb-0.5 tracking-wider uppercase">预估总成本 (实时)</div>
            <div className={`text-2xl font-black ${hasCostData ? 'text-blue-600' : 'text-slate-300'}`}>
              {hasCostData ? `¥${realTimeTotalCost.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '暂未测算'}
            </div>
            {costAnalysis.budget_limit && (
              <div className="text-xs text-slate-400 font-medium">
                预算限额: {costAnalysis.budget_limit}
              </div>
            )}
          </div>
        </div>
      </div>

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
        <div className={`mb-4 p-3 rounded-xl text-xs font-bold transition-all ${
          saveMessage.type === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'
        }`}>
          {saveMessage.type === 'success' ? '✓ ' : '⚠️ '}
          {saveMessage.text}
        </div>
      )}

      {/* BOM 成本核算表格 */}
      <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-100 text-slate-600 text-xs uppercase tracking-wider">
              <th className="p-4 font-bold">标的/设备名称 & 标书规格</th>
              <th className="p-4 font-bold">匹配设备 & 品牌/规格/厂商</th>
              <th className="p-4 font-bold whitespace-nowrap">置信度</th>
              <th className="p-4 font-bold whitespace-nowrap">数量/单位</th>
              <th className="p-4 font-bold whitespace-nowrap">参考单价 (元)</th>
              <th className="p-4 font-bold whitespace-nowrap text-right">成本小计</th>
              <th className="p-4 font-bold whitespace-nowrap text-center">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {hasCostData ? (
              items.map((item: any, idx: number) => {
                const isEditingThis = editingIndex === idx;
                const isUnmatched = item.ref_price <= 0 || item.match_quality === '未匹配';
                const isExact = item.match_quality === '精准匹配';
                const isManual = item.match_quality === '手动添加';
                const isManualEdit = item.match_quality === '手动修改';
                const keyParams = Array.isArray(item.key_parameters) ? item.key_parameters : [];
                const isCore = (item.name && item.name.includes('*')) || keyParams.length > 0;
                const currentQty = isEditingThis ? editQty : (item.qty !== null && item.qty !== undefined ? Number(item.qty) : 1);
                const currentRefPrice = isEditingThis ? editPrice : (item.ref_price ? Number(item.ref_price) : 0);
                const itemSubtotal = currentQty * currentRefPrice;

                return (
                  <tr key={idx} className={`transition-colors group ${isEditingThis ? 'bg-amber-50/40' : 'hover:bg-slate-50/80'}`}>
                    {/* 名称与规格单元格 */}
                    <td className="p-4 max-w-md">
                      {isEditingThis && isManual ? (
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="w-full px-2 py-1 rounded border border-blue-300 text-sm font-bold bg-white focus:outline-none"
                        />
                      ) : (
                        <div className="font-bold text-slate-800 flex items-center gap-1.5 mb-1">
                          {isCore && <span className="text-rose-500 text-xs font-black" title="核心标的/关键设备">★</span>}
                          <span className="text-sm">{item.name}</span>
                          {(isManual || isManualEdit) && (
                            <span className="bg-purple-50 text-purple-600 border border-purple-200 text-[10px] px-1.5 py-0.5 rounded font-bold ml-1">
                              {isManual ? '手动新增' : '手动修改'}
                            </span>
                          )}
                        </div>
                      )}
                      {item.spec_requirement && (
                        <div className="text-xs text-slate-600 leading-relaxed font-normal bg-slate-50/80 p-2 rounded-xl border border-slate-100/80 my-1.5" title={item.spec_requirement}>
                          <span className="text-[10px] font-bold text-slate-400 block mb-0.5">📄 标书原文/说明：</span>
                          {item.spec_requirement}
                        </div>
                      )}
                      {keyParams.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {keyParams.map((param: string, pIdx: number) => (
                            <span key={pIdx} className="bg-amber-50 text-amber-700 text-[10px] px-1.5 py-0.5 rounded border border-amber-200/60 font-medium">
                              ★ {param}
                            </span>
                          ))}
                        </div>
                      )}
                      {item.brand_requirements && (
                        <div className="text-[11px] text-slate-400 mt-1 italic">
                          要求的品牌/产地: {item.brand_requirements}
                        </div>
                      )}
                    </td>

                    {/* 匹配设备单元格 */}
                    <td className="p-4 max-w-md">
                      {!isUnmatched || isManual || currentRefPrice > 0 ? (
                        <div className="space-y-2 text-xs">
                          <div className="font-bold text-slate-800 flex items-center gap-1.5">
                            <span className="text-emerald-500">✓</span>
                            <span className="text-sm">{item.matched_name || item.name}</span>
                          </div>
                          <div className="flex flex-wrap gap-1 text-[11px]">
                            {item.matched_brand && (
                              <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded-md font-medium border border-blue-100">
                                品牌: {item.matched_brand}
                              </span>
                            )}
                            {item.matched_model && (
                              <span className="bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-md font-medium border border-indigo-100">
                                型号: {item.matched_model}
                              </span>
                            )}
                            {item.matched_manufacturer && (
                              <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md font-medium">
                                厂商: {item.matched_manufacturer}
                              </span>
                            )}
                          </div>
                          {item.comparison_note && (
                            <div className="text-[11px] bg-emerald-50/70 text-emerald-800 p-2 rounded-xl border border-emerald-100/80 leading-relaxed font-medium">
                              <span className="font-bold block mb-0.5 text-emerald-700">🔍 对标分析说明：</span>
                              {item.comparison_note}
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-xs text-rose-500 bg-rose-50 px-2.5 py-2 rounded-xl border border-rose-100 font-medium">
                          ⚠️ {item.warning || '未在价格库中找到参考价'}
                        </div>
                      )}
                    </td>

                    {/* 置信度 */}
                    <td className="p-4 whitespace-nowrap">
                      <span className={`text-xs px-2 py-1 rounded-md font-bold ${
                        isExact 
                          ? 'bg-emerald-100 text-emerald-700' 
                          : (isManual || isManualEdit)
                            ? 'bg-purple-100 text-purple-700'
                            : !isUnmatched 
                              ? 'bg-amber-100 text-amber-700' 
                              : 'bg-slate-100 text-slate-400'
                      }`}>
                        {isEditingThis ? '修改中' : (item.match_quality || '未匹配')}
                      </span>
                    </td>

                    {/* 数量/单位 */}
                    <td className="p-4 whitespace-nowrap">
                      {isEditingThis ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="number"
                            min="0.01"
                            step="any"
                            value={editQty}
                            onChange={(e) => setEditQty(parseFloat(e.target.value) || 1)}
                            className="w-16 px-2 py-1 border border-blue-300 rounded text-xs font-bold text-center bg-white focus:outline-none"
                          />
                          <input
                            type="text"
                            value={editUnit}
                            onChange={(e) => setEditUnit(e.target.value)}
                            className="w-12 px-1 py-1 border border-blue-300 rounded text-xs text-center bg-white focus:outline-none"
                          />
                        </div>
                      ) : (
                        <span className="font-bold text-slate-700 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200/60">
                          {`${currentQty} ${item.unit || '项'}`}
                        </span>
                      )}
                    </td>

                    {/* 参考单价 */}
                    <td className="p-4 font-medium text-slate-600 whitespace-nowrap">
                      {isEditingThis ? (
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-slate-400">¥</span>
                          <input
                            type="number"
                            min="0"
                            step="any"
                            value={editPrice}
                            onChange={(e) => setEditPrice(parseFloat(e.target.value) || 0)}
                            className="w-24 px-2 py-1 border border-blue-300 rounded text-xs font-bold text-right bg-white focus:outline-none"
                          />
                        </div>
                      ) : (
                        <span>
                          {currentRefPrice > 0 ? `¥${currentRefPrice.toLocaleString()}` : '--'}
                        </span>
                      )}
                    </td>

                    {/* 成本小计 */}
                    <td className="p-4 font-bold text-blue-600 text-right whitespace-nowrap">
                      {itemSubtotal > 0 ? `¥${itemSubtotal.toLocaleString()}` : '--'}
                    </td>

                    {/* 操作列：编辑与删除 */}
                    <td className="p-4 text-center whitespace-nowrap">
                      {isEditingThis ? (
                        <div className="flex items-center justify-center gap-1">
                          <button
                            onClick={() => handleSaveEdit(idx)}
                            className="px-2 py-1 bg-emerald-600 text-white rounded-md text-xs font-bold hover:bg-emerald-700 transition-colors shadow-sm"
                            title="确认保存此行的修改"
                          >
                            ✓
                          </button>
                          <button
                            onClick={() => setEditingIndex(null)}
                            className="px-2 py-1 bg-slate-200 text-slate-600 rounded-md text-xs font-bold hover:bg-slate-300 transition-colors"
                            title="取消编辑"
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center justify-center gap-1">
                          <button
                            onClick={() => handleStartEdit(idx, item)}
                            className="text-slate-400 hover:text-blue-600 transition-colors p-1 rounded-lg hover:bg-blue-50"
                            title="修改价格与数量"
                          >
                            ✏️
                          </button>
                          <button
                            onClick={() => handleDeleteItem(idx)}
                            className="text-slate-300 hover:text-rose-600 transition-colors p-1 rounded-lg hover:bg-rose-50"
                            title="移除此费用项"
                          >
                            🗑️
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })
            ) : equipmentList.length > 0 ? (
              equipmentList.map((item, idx) => {
                const itemName = item.item_name || '未知设备';
                const isCore = item.is_core || itemName.includes('*');
                const specsText = [
                  item.specifications,
                  ...(item.key_parameters || [])
                ].filter(Boolean).join('；');

                return (
                  <tr key={idx} className="hover:bg-slate-50/80 transition-colors group">
                    <td className="p-4">
                      <div className="font-bold text-slate-800 flex items-center gap-1.5">
                        {isCore && <span className="text-rose-500 text-xs" title="核心设备">★</span>}
                        {itemName}
                      </div>
                    </td>
                    <td className="p-4 text-slate-500 text-xs font-medium max-w-[300px]">
                      <div className="line-clamp-2">
                        {specsText || '--'}
                      </div>
                    </td>
                    <td className="p-4 text-xs font-medium text-slate-400">
                      等待核算
                    </td>
                    <td className="p-4">
                      <span className="font-bold text-slate-700 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200/60 text-xs">
                        {item.quantity !== null && item.quantity !== undefined 
                          ? `${item.quantity} ${item.unit || ''}` 
                          : (item.unit ? item.unit : '--')}
                      </span>
                    </td>
                    <td className="p-4 text-xs font-medium text-slate-400">
                      待匹配
                    </td>
                    <td className="p-4 font-bold text-slate-300 text-right">暂无</td>
                    <td className="p-4 text-center">--</td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={7} className="p-12 text-center text-slate-400 font-medium">
                  <div className="flex flex-col items-center gap-2">
                    <span className="text-3xl">📭</span>
                    <span>未从文档中提取到核心设备清单</span>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 底部新增费用项交互栏 */}
      <div className="mt-4 flex flex-col gap-3">
        {!isAdding ? (
          <div className="flex items-center justify-between">
            <button
              onClick={() => setIsAdding(true)}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-2xl text-xs font-bold transition-all border border-blue-200/60 shadow-sm"
            >
              <span>➕ 新增费用项 (如人工费/售后服务费)</span>
            </button>

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
                className="text-xs text-slate-400 hover:text-slate-600 font-bold"
              >
                ✕ 取消
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
              <div className="md:col-span-2">
                <label className="block text-slate-500 font-bold mb-1">费用项名称 *</label>
                <input
                  type="text"
                  required
                  placeholder="例如: 现场施工人工费 / 3年售后运维费"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                />
              </div>

              <div>
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

              <div>
                <label className="block text-slate-500 font-bold mb-1">单位</label>
                <input
                  type="text"
                  placeholder="项 / 人天 / 年"
                  value={newUnit}
                  onChange={(e) => setNewUnit(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white font-medium"
                />
              </div>

              <div className="md:col-span-2">
                <label className="block text-slate-500 font-bold mb-1">规格/服务内容说明</label>
                <input
                  type="text"
                  placeholder="例如: 包含硬件安调、维保测试及工时补贴"
                  value={newSpec}
                  onChange={(e) => setNewSpec(e.target.value)}
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
              <button
                type="button"
                onClick={() => setIsAdding(false)}
                className="px-4 py-2 rounded-xl border border-slate-300 text-slate-600 font-bold text-xs hover:bg-slate-100 transition-colors"
              >
                取消
              </button>
              <button
                type="submit"
                className="px-5 py-2 rounded-xl bg-blue-600 text-white font-bold text-xs hover:bg-blue-700 transition-colors shadow-sm"
              >
                确认添加并保存
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
