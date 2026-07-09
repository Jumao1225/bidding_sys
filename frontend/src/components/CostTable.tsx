import React from 'react';

const mockData = [
  { id: 1, name: '高性能服务器', spec: '2U机架式, 64核, 256G内存', qty: 10, unit: '台', refPrice: 45000, risk: '交付周期长' },
  { id: 2, name: '企业级存储', spec: '可用容量>50TB, NVMe', qty: 2, unit: '套', refPrice: 120000, risk: '无' },
  { id: 3, name: '核心交换机', spec: '48口万兆', qty: 4, unit: '台', refPrice: 28000, risk: '无' },
];

export function CostTable() {
  const totalCost = mockData.reduce((acc, curr) => acc + (curr.qty * curr.refPrice), 0);

  return (
    <div className="bg-white/80 backdrop-blur-xl p-8 rounded-3xl shadow-sm border border-slate-200/60 transition-all hover:shadow-md">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h3 className="text-xl font-extrabold text-slate-800 flex items-center gap-2">
            <span className="p-1.5 bg-blue-100 text-blue-600 rounded-lg text-sm">💰</span>
            智能 BOM 成本测算
          </h3>
          <p className="text-sm text-slate-500 mt-1 font-medium">已自动匹配市场参考库，底价仅供竞价决策</p>
        </div>
        <div className="text-right bg-slate-50 p-4 rounded-2xl border border-slate-100">
          <div className="text-sm font-bold text-slate-500 mb-1">预估总成本 (RMB)</div>
          <div className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">
            ¥ {totalCost.toLocaleString()}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-100 bg-white">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="bg-slate-50/80 border-b border-slate-100">
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">标的名称</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">规格参数</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">采购数量</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">单价参考</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs">成本小计</th>
              <th className="p-4 font-bold text-slate-600 uppercase tracking-wider text-xs text-center">供应链风险</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {mockData.map((item) => (
              <tr key={item.id} className="hover:bg-blue-50/30 transition-colors group">
                <td className="p-4 font-bold text-slate-800">{item.name}</td>
                <td className="p-4 text-slate-500 text-xs font-medium leading-relaxed max-w-[200px] truncate group-hover:text-clip group-hover:whitespace-normal transition-all">{item.spec}</td>
                <td className="p-4 font-semibold text-slate-700">
                  <span className="bg-slate-100 px-2 py-1 rounded-md">{item.qty} {item.unit}</span>
                </td>
                <td className="p-4 font-medium text-slate-600">¥{item.refPrice.toLocaleString()}</td>
                <td className="p-4 font-bold text-blue-600">¥{(item.qty * item.refPrice).toLocaleString()}</td>
                <td className="p-4 text-center">
                  {item.risk !== '无' ? (
                    <span className="inline-flex items-center gap-1 px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold border border-amber-200 shadow-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span>
                      {item.risk}
                    </span>
                  ) : (
                    <span className="inline-flex px-3 py-1 text-slate-400 text-xs font-medium bg-slate-50 rounded-full">正常</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
