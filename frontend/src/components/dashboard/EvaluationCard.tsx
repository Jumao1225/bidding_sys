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
  onReextract?: () => void;
  isRetrying?: boolean;
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#ec4899', '#06b6d4'];

export function EvaluationCard({ evaluation = {}, onReextract, isRetrying = false }: EvaluationProps) {
  const evaluation_method = evaluation.evaluation_method || '综合评分法';
  const total_score = evaluation.total_score || 100;
  const weight_distribution = evaluation.weight_distribution || {};
  const score_tree = evaluation.score_tree || [];
  const hard_service_requirements = evaluation.hard_service_requirements || {};

  const data = Object.entries(weight_distribution).map(([name, value]) => ({
    name,
    value: Number(value) || 0
  })).filter(item => item.value > 0);

  const chartData = data.length > 0 ? data : [{ name: '暂无数据', value: 100 }];
  const hasValidWeights = data.length > 0;

  return (
    <div className={`bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-purple-100 flex flex-col group hover:shadow-md transition-all h-[420px] relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-white/40 backdrop-blur-[1px] rounded-3xl">
          <svg className="animate-spin h-8 w-8 text-purple-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      )}
      <div className="flex items-center justify-between mb-4 shrink-0 border-b border-purple-100/60 pb-3">
        <div className="flex items-center gap-3 flex-1">
          <span className="p-2 bg-purple-100 text-purple-600 rounded-xl font-bold shadow-sm">⚖️</span>
          <div>
            <h3 className="text-slate-800 font-bold tracking-wide text-base">评标办法、打分细则与售后约束</h3>
            <p className="text-xs text-slate-400">评分权重树状拆解与售后违约风险监控</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {total_score && (
            <span className="px-3 py-1 bg-purple-100 text-purple-700 text-xs font-extrabold rounded-full border border-purple-200">
              总分: {total_score}分
            </span>
          )}
          {evaluation_method && (
            <span className="px-3 py-1 bg-purple-50 text-purple-700 text-xs font-bold rounded-full border border-purple-200">
              {evaluation_method}
            </span>
          )}
          {onReextract && (
            <button 
              onClick={(e) => { e.stopPropagation(); onReextract(); }}
              className="p-1.5 text-slate-400 hover:text-purple-500 hover:bg-purple-50 rounded-md transition-colors"
              title="重新提取该部分"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
            </button>
          )}
        </div>
      </div>
      
      {/* 3 列响应式平铺矩阵 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mt-1 flex-1 overflow-hidden">
        
        {/* 左侧 (3/12): 权重分布饼图 */}
        <div className="lg:col-span-3 flex flex-col items-center justify-between bg-slate-50/50 p-3 rounded-2xl border border-slate-100 h-full overflow-hidden">
          <div className="w-full h-[180px] flex items-center justify-center relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={75}
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
                    formatter={(value: any, name: string) => [`${value}分`, name]}
                  />
                )}
              </PieChart>
            </ResponsiveContainer>
            
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              {hasValidWeights ? (
                <>
                  <span className="text-xl font-black text-slate-700">{chartData.length}</span>
                  <span className="text-[10px] text-slate-400 font-bold uppercase">大类维度</span>
                </>
              ) : (
                <span className="text-xs text-slate-400 font-bold">暂无数据</span>
              )}
            </div>
          </div>
          
          {/* 图例列表 */}
          <div className="w-full pt-2 border-t border-slate-200/60 overflow-y-auto max-h-[120px] custom-scrollbar">
            <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
              {chartData.map((entry, index) => (
                <div key={`legend-${index}`} className="flex items-center gap-1.5 text-xs">
                  <div 
                    className="w-2.5 h-2.5 rounded-full shrink-0" 
                    style={{ backgroundColor: hasValidWeights ? COLORS[index % COLORS.length] : '#cbd5e1' }}
                  ></div>
                  <span className="text-slate-600 font-medium truncate">{entry.name}</span>
                  {hasValidWeights && <span className="text-slate-400 font-bold ml-auto">{entry.value}分</span>}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 中间 (5/12): 评分细则结构化树 */}
        <div className="lg:col-span-5 flex flex-col h-full overflow-hidden bg-purple-50/20 p-3 rounded-2xl border border-purple-100/50">
          <div className="flex items-center justify-between mb-2 pb-1 border-b border-purple-100">
            <h4 className="text-xs font-bold text-purple-900 uppercase tracking-wider flex items-center gap-1">
              <span>📋</span> 评分细则要点拆解 ({score_tree.length}项)
            </h4>
            <span className="text-[11px] text-purple-600 font-bold">最高分占比</span>
          </div>
          
          <div className="overflow-y-auto custom-scrollbar pr-1 space-y-2 flex-1 pb-2">
            {score_tree.length > 0 ? (
              score_tree.map((item, idx) => (
                <div key={`score-${idx}`} className="bg-white p-2.5 rounded-xl border border-purple-100/80 shadow-xs hover:border-purple-200 transition-colors">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-[10px] font-bold rounded-md shrink-0">
                      {item.category || '通用'}
                    </span>
                    <span className="text-xs font-bold text-slate-800 truncate flex-1">{item.title}</span>
                    {item.max_score && (
                      <span className="text-xs font-extrabold text-purple-600 shrink-0 bg-purple-50 px-2 py-0.5 rounded-full border border-purple-200">
                        {item.max_score}分
                      </span>
                    )}
                  </div>
                  {item.scoring_criteria && (
                    <p className="text-[11px] text-slate-500 leading-normal line-clamp-2">{item.scoring_criteria}</p>
                  )}
                  {item.rules_summary && item.rules_summary.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {item.rules_summary.map((rule: string, rIdx: number) => (
                        <span key={rIdx} className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">
                          {rule}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div className="text-xs text-slate-400 h-full flex items-center justify-center italic bg-white/50 rounded-xl">
                未查找到具体打分细则树，请查看左侧大类权重
              </div>
            )}
          </div>
        </div>

        {/* 右侧 (4/12): 售后服务与硬性约束 */}
        <div className="lg:col-span-4 flex flex-col h-full overflow-hidden bg-rose-50/20 p-3 rounded-2xl border border-rose-100/50">
          <div className="flex items-center justify-between mb-2 pb-1 border-b border-rose-100">
            <h4 className="text-xs font-bold text-rose-900 uppercase tracking-wider flex items-center gap-1">
              <span>📌</span> 售后服务与违约约束
            </h4>
            <span className="text-[11px] text-rose-600 font-bold">红线条款</span>
          </div>
          
          <div className="overflow-y-auto custom-scrollbar pr-1 space-y-2 flex-1 pb-2">
            {Object.keys(hard_service_requirements).length > 0 ? (
              Object.entries(hard_service_requirements).map(([key, desc], idx) => (
                <div key={idx} className="text-xs text-rose-800 bg-white p-2.5 rounded-xl border border-rose-100 shadow-xs">
                  <div className="font-bold mb-1 flex items-center justify-between">
                    <span className="text-slate-800 font-bold flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span> {key}
                    </span>
                  </div>
                  <div className="text-slate-600 leading-normal text-[11px] font-medium">
                    {Array.isArray(desc) ? (
                      <ul className="list-disc pl-3 space-y-0.5">
                        {desc.map((item, i) => <li key={i}>{item}</li>)}
                      </ul>
                    ) : desc}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-xs text-slate-400 h-full flex items-center justify-center italic bg-white/50 rounded-xl">
                未识别到明显售后违约红线
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
