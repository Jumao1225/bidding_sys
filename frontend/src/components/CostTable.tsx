import React from 'react';

interface CostTableProps {
  equipmentList?: any[];
  costAnalysis?: any;
  onReextract?: () => void;
  isRetrying?: boolean;
}

export function CostTable({ equipmentList = [], costAnalysis = {}, onReextract, isRetrying = false }: CostTableProps) {
  const hasCostData = costAnalysis && costAnalysis.items && costAnalysis.items.length > 0;
  const budgetStatus = costAnalysis.budget_status || '';
  const isBudgetExceeded = budgetStatus.includes('已超出');
  const isBudgetWarning = budgetStatus.includes('接近');

  return (
    <div className={`bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md col-span-2 relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-white/50 backdrop-blur-[2px] rounded-3xl gap-2">
          <svg className="animate-spin h-8 w-8 text-blue-600" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <span className="text-xs font-bold text-blue-600">正在重新对接价格库并计算成本...</span>
        </div>
      )}
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
              ? `基于企业全维度价格库自动计算底价（全库共匹配 ${costAnalysis.items.length} 项，其中 ${costAnalysis.unmatched_count || 0} 项缺价）` 
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

          <div className="text-right bg-slate-50 p-3.5 px-5 rounded-2xl border border-slate-100 shadow-inner">
            <div className="text-xs font-bold text-slate-500 mb-0.5 tracking-wider uppercase">预估总成本</div>
            <div className={`text-2xl font-black ${hasCostData ? 'text-blue-600' : 'text-slate-300'}`}>
              {hasCostData ? `¥${(costAnalysis.total_cost || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '暂未测算'}
            </div>
            {costAnalysis.budget_limit && (
              <div className="text-xs text-slate-400 font-medium">
                预算限额: {costAnalysis.budget_limit}
              </div>
            )}
          </div>
        </div>
      </div>

      {costAnalysis.analysis_summary && (
        <div className="mb-4 p-3.5 bg-blue-50/60 rounded-2xl border border-blue-100 text-xs text-slate-700 leading-relaxed font-medium flex items-start gap-2">
          <span className="text-blue-500 text-sm">💡</span>
          <div>
            <span className="font-bold text-blue-900 mr-1">专家评估推导:</span>
            {costAnalysis.analysis_summary}
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white shadow-sm">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-100 text-slate-600 text-xs uppercase tracking-wider">
              <th className="p-4 font-bold">标的/设备名称 & 标书规格</th>
              <th className="p-4 font-bold">匹配设备 & 品牌/规格/厂商</th>
              <th className="p-4 font-bold whitespace-nowrap">置信度</th>
              <th className="p-4 font-bold whitespace-nowrap">数量/单位</th>
              <th className="p-4 font-bold whitespace-nowrap">参考单价</th>
              <th className="p-4 font-bold whitespace-nowrap text-right">成本小计</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {hasCostData ? (
              costAnalysis.items.map((item: any, idx: number) => {
                const isUnmatched = item.ref_price <= 0 || item.match_quality === '未匹配';
                const isExact = item.match_quality === '精准匹配';
                const keyParams = Array.isArray(item.key_parameters) ? item.key_parameters : [];
                const isCore = (item.name && item.name.includes('*')) || keyParams.length > 0;

                return (
                  <tr key={idx} className="hover:bg-slate-50/80 transition-colors group">
                    <td className="p-4 max-w-md">
                      <div className="font-bold text-slate-800 flex items-center gap-1.5 mb-1">
                        {isCore && <span className="text-rose-500 text-xs font-black" title="核心标的/关键设备">★</span>}
                        <span className="text-sm">{item.name}</span>
                      </div>
                      {item.spec_requirement && (
                        <div className="text-xs text-slate-600 leading-relaxed font-normal bg-slate-50/80 p-2 rounded-xl border border-slate-100/80 my-1.5" title={item.spec_requirement}>
                          <span className="text-[10px] font-bold text-slate-400 block mb-0.5">📄 标书原文要求：</span>
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
                    <td className="p-4 max-w-md">
                      {!isUnmatched ? (
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
                              <span className="font-bold block mb-0.5 text-emerald-700">🔍 自有设备对标分析：</span>
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
                    <td className="p-4 whitespace-nowrap">
                      <span className={`text-xs px-2 py-1 rounded-md font-bold ${
                        isExact 
                          ? 'bg-emerald-100 text-emerald-700' 
                          : !isUnmatched 
                            ? 'bg-amber-100 text-amber-700' 
                            : 'bg-slate-100 text-slate-400'
                      }`}>
                        {item.match_quality || '未匹配'}
                      </span>
                    </td>
                    <td className="p-4 whitespace-nowrap">
                      <span className="font-bold text-slate-700 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200/60">
                        {item.qty !== null && item.qty !== undefined 
                          ? `${item.qty} ${item.unit || ''}` 
                          : (item.unit ? item.unit : '--')}
                      </span>
                    </td>
                    <td className="p-4 font-medium text-slate-600 whitespace-nowrap">
                      {item.ref_price > 0 ? `¥${item.ref_price.toLocaleString()}` : '--'}
                    </td>
                    <td className="p-4 font-bold text-blue-600 text-right whitespace-nowrap">
                      {item.subtotal > 0 ? `¥${item.subtotal.toLocaleString()}` : '--'}
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
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={6} className="p-12 text-center text-slate-400 font-medium">
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
    </div>
  );
}
