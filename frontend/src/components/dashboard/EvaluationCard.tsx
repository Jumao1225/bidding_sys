import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';

interface EvaluationProps {
  weights?: {
    price: number;
    tech: number;
    business: number;
  };
  penalties?: string[];
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b']; // Blue, Emerald, Amber

export function EvaluationCard({ weights = { price: 50, tech: 30, business: 20 }, penalties = [] }: EvaluationProps) {
  const data = [
    { name: '商务报价分', value: weights.price },
    { name: '技术方案分', value: weights.tech },
    { name: '企业资质/业绩分', value: weights.business },
  ];

  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-purple-100 flex flex-col group hover:shadow-md transition-all col-span-2 md:col-span-1">
      <div className="flex items-center gap-3 mb-4">
        <span className="p-2 bg-purple-100 text-purple-600 rounded-lg">⚖️</span>
        <h3 className="text-slate-700 font-bold tracking-wide">评标权重与违约罚则</h3>
      </div>
      
      <div className="flex flex-col md:flex-row gap-6 mt-4">
        {/* 左侧：打分权重饼图 */}
        <div className="w-full md:w-1/2 h-[200px] flex items-center justify-center relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={75}
                paddingAngle={5}
                dataKey="value"
                stroke="none"
              >
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                formatter={(value: any) => [`${value}%`, '权重']}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* 饼图中心文字 */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-2xl font-black text-slate-800">{weights.price}%</span>
            <span className="text-[10px] text-slate-500 font-semibold">报价权重</span>
          </div>
        </div>

        {/* 右侧：违约与废标红线 */}
        <div className="w-full md:w-1/2 space-y-4">
          <h4 className="text-sm font-semibold text-slate-500 mb-2 border-b border-slate-100 pb-2">关键违约/废标条款</h4>
          {penalties.length > 0 ? (
            <ul className="space-y-3 h-[150px] overflow-y-auto custom-scrollbar pr-2">
              {penalties.map((penalty, idx) => (
                <li key={idx} className="text-xs text-rose-700 bg-rose-50 p-3 rounded-xl border border-rose-100 leading-relaxed font-medium">
                  {penalty}
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-xs text-slate-400 h-full flex items-center justify-center italic">
              当前文档未识别到明显的违约红线条款。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
