import React from 'react';

interface FinancialProps {
  financial?: {
    budget?: { amount: number; currency: string; amount_in_words?: string } | null;
    max_price_limit?: { amount: number; currency: string; amount_in_words?: string } | null;
    sub_package_budgets?: any[];
    unit_price_limits?: Record<string, number>;
    provisional_sum?: { amount: number; currency: string; amount_in_words?: string } | null;
    contract_price_type?: string | null;
    tax_rate_requirement?: string | null;
    bid_bond?: any;
    performance_bond?: any;
    warranty_bond?: any;
    advance_payment_ratio?: number | null;
    payment_milestones?: any[];
  };
  onReextract?: () => void;
  isRetrying?: boolean;
}

export function FinancialCard({ financial = {}, onReextract, isRetrying = false }: FinancialProps) {
  const budget = financial.budget;
  const max_price_limit = financial.max_price_limit;
  const unit_price_limits = financial.unit_price_limits || {};
  const provisional_sum = financial.provisional_sum;
  const contract_price_type = financial.contract_price_type;
  const tax_rate_requirement = financial.tax_rate_requirement;
  const bid_bond = financial.bid_bond;
  const performance_bond = financial.performance_bond;
  const warranty_bond = financial.warranty_bond;
  const advance_payment_ratio = financial.advance_payment_ratio;
  const payment_milestones = financial.payment_milestones || [];

  const formatMoney = (amount?: number) => {
    if (amount === undefined || amount === null) return '--';
    // 招投标业务对金额精度要求极高，废除“万”单位的四舍五入，统一精确到“元”
    return `${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}元`;
  };

  const hasBonds = bid_bond || performance_bond || warranty_bond;

  return (
    <div className={`bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-amber-100 flex flex-col group hover:shadow-md transition-all h-[400px] overflow-hidden relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-white/40 backdrop-blur-[1px] rounded-3xl">
          <svg className="animate-spin h-8 w-8 text-amber-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      )}
      <div className="flex items-center gap-3 mb-6 shrink-0">
        <span className="p-2 bg-amber-100 text-amber-600 rounded-lg">💰</span>
        <h3 className="text-slate-700 font-bold tracking-wide flex-1">核心财务防线与资金流</h3>
        {onReextract && (
          <button 
            onClick={(e) => { e.stopPropagation(); onReextract(); }}
            className="p-1.5 ml-1 text-slate-400 hover:text-amber-500 hover:bg-amber-50 rounded-md transition-colors"
            title="重新提取该部分"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
          </button>
        )}
      </div>

      <div className="overflow-y-auto custom-scrollbar pr-2 space-y-6 flex-1 pb-4">
        {/* 核心预算对标 */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-slate-50 p-4 rounded-2xl border border-slate-100">
            <div className="text-xs font-bold text-slate-500 mb-1">采购总预算 (Budget)</div>
            <div className="text-2xl font-black text-slate-700">{formatMoney(budget?.amount)}</div>
          </div>
          <div className="bg-rose-50 p-4 rounded-2xl border border-rose-100 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-16 h-16 bg-rose-500/10 rounded-full blur-xl -mr-4 -mt-4"></div>
            <div className="text-xs font-bold text-rose-500 mb-1 relative z-10 flex items-center gap-1">最高投标限价 (Max Limit) 🚫</div>
            <div className="text-2xl font-black text-rose-600 relative z-10">{formatMoney(max_price_limit?.amount)}</div>
          </div>
        </div>

        {/* 不可竞争/单价限制 */}
        {(provisional_sum || Object.keys(unit_price_limits).length > 0 || contract_price_type || tax_rate_requirement) && (
          <div className="bg-slate-50 rounded-xl border border-slate-200 p-4 space-y-3">
            <div className="grid grid-cols-2 gap-4 text-sm">
              {contract_price_type && (
                <div><span className="text-slate-400 mr-2">计价方式:</span><span className="font-bold text-slate-700">{contract_price_type}</span></div>
              )}
              {tax_rate_requirement && (
                <div><span className="text-slate-400 mr-2">税率要求:</span><span className="font-bold text-slate-700">{tax_rate_requirement}</span></div>
              )}
            </div>
            {provisional_sum && (
              <div className="flex items-center gap-2 text-sm pt-2 border-t border-slate-200">
                <span className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded text-xs font-bold">暂列金额</span>
                <span className="font-bold text-slate-700">{formatMoney(provisional_sum.amount)}</span>
                <span className="text-xs text-slate-400">(不可竞争费用)</span>
              </div>
            )}
            {Object.keys(unit_price_limits).map((key) => (
              <div key={key} className="flex justify-between items-center text-sm pt-2 border-t border-slate-200">
                <span className="text-slate-600">{key}</span>
                <span className="font-bold text-rose-600 border-b border-rose-300 border-dashed pb-0.5">限价: {formatMoney(unit_price_limits[key])}</span>
              </div>
            ))}
          </div>
        )}

        {/* 付款节点 */}
        {payment_milestones.length > 0 && (
          <div>
            <h4 className="text-xs font-bold text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-blue-400"></div> 资金流与付款节点
            </h4>
            <div className="space-y-2">
              {payment_milestones.map((m, idx) => (
                <div key={idx} className="flex gap-3 text-sm text-slate-700 bg-blue-50/30 p-3 rounded-xl border border-blue-100/50">
                  <div className="font-bold text-blue-600 shrink-0 w-12 text-right">{m.percentage}%</div>
                  <div>
                    <div className="font-bold text-slate-800 mb-0.5">{m.stage} {m.invoice_required ? <span className="text-[10px] bg-slate-200 text-slate-500 px-1 rounded ml-1">需发票</span> : ''}</div>
                    <div className="text-xs text-slate-500 leading-relaxed">{m.condition}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 保证金要求 */}
        {hasBonds && (
          <div>
            <h4 className="text-xs font-bold text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-400"></div> 资金占用 (保证金)
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {[
                { title: '投标保证金', data: bid_bond },
                { title: '履约保证金', data: performance_bond },
                { title: '质保金', data: warranty_bond }
              ].map((bond, idx) => bond.data && (
                <div key={idx} className="bg-amber-50/50 p-3 rounded-xl border border-amber-100/50 flex flex-col">
                  <div className="text-xs font-bold text-amber-700 mb-1">{bond.title}</div>
                  <div className="font-bold text-slate-800 text-sm mb-1">{bond.data.calculated_amount ? formatMoney(bond.data.calculated_amount) : bond.data.amount_description}</div>
                  {bond.data.acceptable_forms && bond.data.acceptable_forms.length > 0 && (
                    <div className="text-[10px] text-slate-500 mt-auto">{bond.data.acceptable_forms.join('/')}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
