import React from 'react';

interface QualificationProps {
  qualification?: {
    min_registered_capital_wuyuan?: number | null;
    mandatory_qualifications?: string[];
    personnel_requirements?: any[];
    performance_requirements?: any[];
    system_certifications?: string[];
    bonus_qualifications?: string[];
    credit_and_legal_reqs?: string[];
    invalid_bid_clauses?: string[];
    project_annulment_clauses?: string[];
  };
  onReextract?: () => void;
  isRetrying?: boolean;
}

export function QualificationCard({ qualification = {}, onReextract, isRetrying = false }: QualificationProps) {
  const min_registered_capital_wuyuan = qualification.min_registered_capital_wuyuan;
  const mandatory_qualifications = qualification.mandatory_qualifications || [];
  const personnel_requirements = qualification.personnel_requirements || [];
  const performance_requirements = qualification.performance_requirements || [];
  const system_certifications = qualification.system_certifications || [];
  const bonus_qualifications = qualification.bonus_qualifications || [];
  const credit_and_legal_reqs = qualification.credit_and_legal_reqs || [];
  const invalid_bid_clauses = qualification.invalid_bid_clauses || [];
  const project_annulment_clauses = qualification.project_annulment_clauses || [];

  const mandatoryPersonnel = personnel_requirements.filter(p => p.is_mandatory);
  const bonusPersonnel = personnel_requirements.filter(p => !p.is_mandatory);

  return (
    <div className={`bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-emerald-100 flex flex-col group hover:shadow-md transition-all h-[400px] overflow-hidden relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-white/40 backdrop-blur-[1px] rounded-3xl">
          <svg className="animate-spin h-8 w-8 text-emerald-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      )}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3 flex-1">
          <span className="p-2 bg-emerald-100 text-emerald-600 rounded-lg">🏅</span>
          <h3 className="text-slate-700 font-bold tracking-wide">资质与合规准入</h3>
        </div>
        <div className="flex items-center gap-2">
          {min_registered_capital_wuyuan && (
            <span className="px-3 py-1 bg-emerald-50 text-emerald-700 text-xs font-bold rounded-full border border-emerald-200 shadow-sm">
              资本金 ≥ {min_registered_capital_wuyuan}万
            </span>
          )}
          {onReextract && (
            <button 
              onClick={(e) => { e.stopPropagation(); onReextract(); }}
              className="p-1.5 text-slate-400 hover:text-emerald-500 hover:bg-emerald-50 rounded-md transition-colors"
              title="重新提取该部分"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
            </button>
          )}
        </div>
      </div>

      <div className="overflow-y-auto custom-scrollbar pr-2 space-y-6 flex-1 pb-4">
        {/* 一票否决/强制性门槛区 */}
        <div>
          <h4 className="text-xs font-bold text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-rose-400"></div> 强制性门槛 (Mandatory)
          </h4>
          <ul className="space-y-3">
            {mandatory_qualifications.map((q, idx) => (
              <li key={`mq-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-rose-50/50 p-3 rounded-xl border border-rose-100/50">
                <span className="text-rose-500 shrink-0">🚫</span>
                <span className="font-medium leading-relaxed">{q}</span>
              </li>
            ))}
            {mandatoryPersonnel.map((p, idx) => (
              <li key={`mp-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-rose-50/50 p-3 rounded-xl border border-rose-100/50">
                <span className="text-rose-500 shrink-0">👤</span>
                <div>
                  <span className="font-bold text-slate-800">{p.role}</span>: 需具备 <span className="font-bold text-rose-600">{p.cert_name}</span> ({p.count}人)
                  {p.other_requirements && <div className="text-xs text-slate-500 mt-1">{p.other_requirements}</div>}
                </div>
              </li>
            ))}
            {performance_requirements.map((perf, idx) => (
              <li key={`perf-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-rose-50/50 p-3 rounded-xl border border-rose-100/50">
                <span className="text-rose-500 shrink-0">🏆</span>
                <div>
                  <div className="font-bold text-slate-800 mb-2">历史业绩要求 ({perf.required_count}个)</div>
                  <div className="flex flex-wrap gap-2 mb-2">
                    {perf.time_frame_years && <span className="text-xs bg-white px-2.5 py-1 rounded-md border border-rose-200 text-rose-600 shadow-sm font-bold">近{perf.time_frame_years}年</span>}
                    {perf.min_amount_wuyuan && <span className="text-xs bg-white px-2.5 py-1 rounded-md border border-rose-200 text-rose-600 shadow-sm font-bold">≥{perf.min_amount_wuyuan}万</span>}
                    {perf.keyword_or_domain && <span className="text-xs bg-white px-2.5 py-1 rounded-md border border-rose-200 text-rose-600 shadow-sm font-bold">{perf.keyword_or_domain}</span>}
                  </div>
                  <div className="text-xs text-slate-500 leading-relaxed">{perf.description}</div>
                </div>
              </li>
            ))}
            {credit_and_legal_reqs.length > 0 && (
              <li className="flex gap-2 text-sm text-slate-700 bg-slate-50 p-3 rounded-xl border border-slate-200">
                <span className="text-slate-400 shrink-0">⚖️</span>
                <span className="text-xs leading-relaxed">{credit_and_legal_reqs.join('；')}</span>
              </li>
            )}
            {mandatory_qualifications.length === 0 && mandatoryPersonnel.length === 0 && performance_requirements.length === 0 && credit_and_legal_reqs.length === 0 && (
              <div className="text-xs text-emerald-600 bg-emerald-50 p-3 rounded-xl border border-emerald-100 flex items-center gap-2">
                <span>✅</span> 未提取到明确硬性废标资质要求
              </div>
            )}
          </ul>
        </div>

        {/* 无效投标与废标雷区 Checklist */}
        <div>
          <h4 className="text-xs font-bold text-rose-500 mb-3 uppercase tracking-wider flex items-center gap-1">
            <span className="text-base leading-none">⛔</span> 致命雷区 (程序性废标项)
          </h4>
          
          {(invalid_bid_clauses.length > 0 || project_annulment_clauses.length > 0) ? (
            <div className="space-y-3">
              {invalid_bid_clauses.length > 0 && (
                <div className="bg-red-50 p-4 rounded-xl border border-red-100">
                  <div className="text-xs font-bold text-red-600 mb-2">无效投标/否决投标条款 (针对单家投标人)</div>
                  <ul className="list-disc pl-4 space-y-1">
                    {invalid_bid_clauses.map((clause, idx) => (
                      <li key={`inv-${idx}`} className="text-sm text-red-800 leading-relaxed">{clause}</li>
                    ))}
                  </ul>
                </div>
              )}
              {project_annulment_clauses.length > 0 && (
                <div className="bg-orange-50 p-4 rounded-xl border border-orange-100">
                  <div className="text-xs font-bold text-orange-600 mb-2">项目废标条款 (导致整个招标失败)</div>
                  <ul className="list-disc pl-4 space-y-1">
                    {project_annulment_clauses.map((clause, idx) => (
                      <li key={`ann-${idx}`} className="text-sm text-orange-800 leading-relaxed">{clause}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <div className="text-xs text-slate-500 bg-slate-50 p-4 rounded-xl border border-slate-200 border-dashed flex items-center gap-2">
              <span>🔍</span> 智能引擎未在当前标书中提取到集中的“程序性废标”条款。由于该事项极为关键，建议人工通过右侧阅读器检索“无效”、“否决”等关键字进行最后复核。
            </div>
          )}
        </div>

        {/* 加分项区 */}
        {(bonus_qualifications.length > 0 || system_certifications.length > 0 || bonusPersonnel.length > 0) && (
          <div>
            <h4 className="text-xs font-bold text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400"></div> 加分/优选项 (Bonus)
            </h4>
            <ul className="space-y-3">
              {bonus_qualifications.map((q, idx) => (
                <li key={`bq-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-emerald-50/50 p-3 rounded-xl border border-emerald-100/50">
                  <span className="text-emerald-500 shrink-0">✨</span>
                  <span className="leading-relaxed">{q}</span>
                </li>
              ))}
              {system_certifications.map((cert, idx) => (
                <li key={`cert-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-blue-50/50 p-3 rounded-xl border border-blue-100/50">
                  <span className="text-blue-500 shrink-0">🔖</span>
                  <span className="font-medium">体系认证: {cert}</span>
                </li>
              ))}
              {bonusPersonnel.map((p, idx) => (
                <li key={`bp-${idx}`} className="flex gap-2 text-sm text-slate-700 bg-emerald-50/50 p-3 rounded-xl border border-emerald-100/50">
                  <span className="text-emerald-500 shrink-0">👤</span>
                  <div>
                    <span className="font-bold text-slate-800">{p.role}</span>: <span className="font-bold text-emerald-700">{p.cert_name}</span> ({p.count}人)
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
