import React from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

interface EvaluationProps {
  evaluation?: {
    evaluation_method?: string | null;
    total_score?: number | null;
    weight_distribution?: Record<string, number>;
    score_tree?: any[];
    hard_service_requirements?: Record<string, string>;
  };
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#ec4899', '#06b6d4'];

export function EvaluationCard({ evaluation = {} }: EvaluationProps) {
  const evaluation_method = evaluation.evaluation_method;
  const weight_distribution = evaluation.weight_distribution || {};
  const hard_service_requirements = evaluation.hard_service_requirements || {};

  const data = Object.entries(weight_distribution).map(([name, value]) => ({
    name,
    value: Number(value) || 0
  })).filter(item => item.value > 0);

  // Fallback data if backend didn't extract correctly
  const chartData = data.length > 0 ? data : [{ name: '暂无数据', value: 100 }];
  const hasValidWeights = data.length > 0;

  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-purple-100 flex flex-col group hover:shadow-md transition-all h-[400px]">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="p-2 bg-purple-100 text-purple-600 rounded-lg">⚖️</span>
          <h3 className="text-slate-700 font-bold tracking-wide">评标权重与售后红线</h3>
        </div>
        {evaluation_method && (
          <span className="px-3 py-1 bg-purple-50 text-purple-700 text-xs font-bold rounded-full border border-purple-200">
            {evaluation_method}
          </span>
        )}
      </div>
      
      <div className="flex flex-col md:flex-row gap-6 mt-2 flex-1 overflow-hidden">
        <div className="w-full md:w-[55%] flex flex-col items-center">
          <div className="w-full h-[200px] flex items-center justify-center relative bg-slate-50/50 rounded-t-2xl border-x border-t border-slate-100">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={80}
                  paddingAngle={4}
                  dataKey="value"
                  stroke="none"
                >
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={hasValidWeights ? COLORS[index % COLORS.length] : '#cbd5e1'} />
                  ))}
                </Pie>
                {hasValidWeights && (
                  <Tooltip 
                    contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)', fontSize: '12px', fontWeight: 'bold' }}
                    formatter={(value: any, name: string) => [`${value}`, name]}
                  />
                )}
              </PieChart>
            </ResponsiveContainer>
            
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              {hasValidWeights ? (
                <>
                  <span className="text-2xl font-black text-slate-700">{chartData.length}</span>
                  <span className="text-[10px] text-slate-400 font-bold uppercase">考核项</span>
                </>
              ) : (
                <span className="text-xs text-slate-400 font-bold">暂无</span>
              )}
            </div>
          </div>
          
          {/* Custom Legend */}
          <div className="w-full bg-slate-50/50 border-x border-b border-slate-100 rounded-b-2xl p-4 pt-2">
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-2">
              {chartData.map((entry, index) => (
                <div key={`legend-${index}`} className="flex items-center gap-1.5">
                  <div 
                    className="w-2.5 h-2.5 rounded-full" 
                    style={{ backgroundColor: hasValidWeights ? COLORS[index % COLORS.length] : '#cbd5e1' }}
                  ></div>
                  <span className="text-xs text-slate-600 font-bold">{entry.name}</span>
                  {hasValidWeights && <span className="text-xs text-slate-400">({entry.value})</span>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧：售后与硬性服务条款 */}
        <div className="w-full md:w-[45%] flex flex-col h-full overflow-hidden">
          <h4 className="text-xs font-bold text-slate-400 mb-3 border-b border-slate-100 pb-2 uppercase tracking-wider">售后及硬性服务红线</h4>
          
          <div className="overflow-y-auto custom-scrollbar pr-2 space-y-3 flex-1 pb-4">
            {Object.keys(hard_service_requirements).length > 0 ? (
              Object.entries(hard_service_requirements).map(([key, desc], idx) => (
                <div key={idx} className="text-xs text-rose-700 bg-rose-50 p-3 rounded-xl border border-rose-100/50 shadow-sm">
                  <div className="font-bold mb-1 flex items-center gap-1"><span className="text-rose-500">📌</span> {key}</div>
                  <div className="text-slate-600 leading-relaxed font-medium">
                    {Array.isArray(desc) ? (
                      <ul className="list-disc pl-4 space-y-1">
                        {desc.map((item, i) => <li key={i}>{item}</li>)}
                      </ul>
                    ) : desc}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-xs text-slate-400 h-full flex items-center justify-center italic bg-slate-50 rounded-xl border border-slate-100">
                未识别到明显售后违约红线
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
