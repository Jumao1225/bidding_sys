import React from 'react';

interface CostTableProps {
  equipment?: Record<string, any>;
}

export function CostTable({ equipment = {} }: CostTableProps) {
  const equipmentEntries = Object.entries(equipment);


  return (
    <div className="bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h3 className="text-xl font-extrabold text-slate-800 flex items-center gap-2">
            <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
            智能 BOM 成本测算
          </h3>
          <p className="text-sm text-slate-500 mt-1 font-medium">自动提取的标书设备清单，成本系统接入中...</p>
        </div>
        <div className="text-right bg-slate-50 p-4 rounded-2xl border border-slate-100">
          <div className="text-sm font-bold text-slate-500 mb-1">预估总成本 (RMB)</div>
          <div className="text-2xl font-black text-slate-400">
            暂未测算
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-slate-50/80 border-b border-slate-100">
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">标的/设备名称</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">规格参数/要求</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">单价参考</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">成本小计</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {equipmentEntries.length > 0 ? (
              equipmentEntries.map(([name, desc], idx) => (
                <tr key={idx} className="hover:bg-blue-50/30 transition-colors group">
                  <td className="p-4 font-bold text-slate-800">{name}</td>
                  <td className="p-4 text-slate-500 text-xs font-medium leading-relaxed max-w-[200px] truncate group-hover:text-clip group-hover:whitespace-normal transition-all">
                    {typeof desc === 'object' ? JSON.stringify(desc) : String(desc)}
                  </td>
                  <td className="p-4 font-medium text-slate-400">系统开发中...</td>
                  <td className="p-4 font-bold text-slate-300">--</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={4} className="p-8 text-center text-slate-400 font-medium">
                  未从文档中提取到核心设备清单
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
