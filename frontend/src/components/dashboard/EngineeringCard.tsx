import React from 'react';

interface EngineeringProps {
  painPoints?: string[];
  equipment?: string[];
}

export function EngineeringCard({ painPoints = [], equipment = [] }: EngineeringProps) {
  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-amber-100 flex flex-col group hover:shadow-md transition-all">
      <div className="flex items-center gap-3 mb-4">
        <span className="p-2 bg-amber-100 text-amber-600 rounded-lg">🏗️</span>
        <h3 className="text-slate-700 font-bold tracking-wide">施工痛点与核心设备</h3>
      </div>
      
      <div className="space-y-4">
        <div>
          <h4 className="text-sm font-semibold text-slate-500 mb-2">高危施工工况 (AI 自动扫雷)</h4>
          {painPoints.length > 0 ? (
            <ul className="space-y-2">
              {painPoints.map((point, idx) => (
                <li key={idx} className="flex gap-2 text-sm text-slate-700 bg-rose-50/50 p-2 rounded-lg border border-rose-100/50">
                  <span className="text-rose-500 mt-0.5">⚠️</span>
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-emerald-600 bg-emerald-50 p-2 rounded-lg border border-emerald-100">
              ✅ 未扫描到特殊的高危施工痛点
            </div>
          )}
        </div>

        <div>
          <h4 className="text-sm font-semibold text-slate-500 mb-2">核心要求设备</h4>
          <div className="flex flex-wrap gap-2">
            {equipment.length > 0 ? (
              equipment.map((item, idx) => (
                <span key={idx} className="px-3 py-1 bg-slate-100 text-slate-600 rounded-full text-xs font-medium border border-slate-200">
                  {item}
                </span>
              ))
            ) : (
              <span className="text-sm text-slate-400">未提取到核心设备限制</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
