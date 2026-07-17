import React from 'react';

interface CostTableProps {
  equipmentList?: any[];
}

export function CostTable({ equipmentList = [] }: CostTableProps) {
  return (
    <div className="bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md col-span-2">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-xl font-extrabold text-slate-800 flex items-center gap-2 mb-1">
            <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
            智能 BOM 成本测算
          </h3>
          <p className="text-sm text-slate-500 font-medium">自动提取的标书设备清单，成本系统接入中...</p>
        </div>
        <div className="text-right bg-slate-50 p-4 rounded-2xl border border-slate-100 shadow-inner">
          <div className="text-xs font-bold text-slate-500 mb-1 tracking-wider uppercase">预估总成本 (RMB)</div>
          <div className="text-2xl font-black text-slate-300">
            暂未测算
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-100">
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">标的/设备名称</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">规格参数/技术要求</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">数量/单位</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">品牌要求</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs text-right">成本测算</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {equipmentList.length > 0 ? (
              equipmentList.map((item, idx) => {
                const itemName = item.item_name || '未知设备';
                const isCore = item.is_core || itemName.includes('*');
                
                // Combine specifications and key parameters for tech reqs
                const specsText = [
                  item.specifications,
                  ...(item.key_parameters || [])
                ].filter(Boolean).join('；');

                return (
                  <tr key={idx} className="hover:bg-blue-50/30 transition-colors group">
                    <td className="p-4">
                      <div className="font-bold text-slate-800 flex items-center gap-1.5">
                        {isCore && <span className="text-rose-500 text-xs" title="关键设备/核心产品">★</span>}
                        {itemName}
                      </div>
                    </td>
                    <td className="p-4 text-slate-500 text-xs font-medium leading-relaxed max-w-[300px]">
                      <div className="line-clamp-2 group-hover:line-clamp-none transition-all duration-300">
                        {specsText || '--'}
                      </div>
                    </td>
                    <td className="p-4">
                      <span className="font-bold text-slate-700 bg-slate-50 px-2 py-1 rounded-md border border-slate-100">
                        {item.quantity ?? '--'} {item.unit || ''}
                      </span>
                    </td>
                    <td className="p-4 text-xs font-medium text-slate-500">
                      {item.brand_requirements || '--'}
                    </td>
                    <td className="p-4 font-bold text-slate-300 text-right">开发中</td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={5} className="p-12 text-center text-slate-400 font-medium">
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
