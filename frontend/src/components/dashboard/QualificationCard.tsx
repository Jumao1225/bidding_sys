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
  };
}

export function QualificationCard({ qualification = {} }: QualificationProps) {
  const min_registered_capital_wuyuan = qualification.min_registered_capital_wuyuan;
  const mandatory_qualifications = qualification.mandatory_qualifications || [];
  const personnel_requirements = qualification.personnel_requirements || [];
  const performance_requirements = qualification.performance_requirements || [];
  const system_certifications = qualification.system_certifications || [];
  const bonus_qualifications = qualification.bonus_qualifications || [];
  const credit_and_legal_reqs = qualification.credit_and_legal_reqs || [];

  const mandatoryPersonnel = personnel_requirements.filter(p => p.is_mandatory);
  const bonusPersonnel = personnel_requirements.filter(p => !p.is_mandatory);

  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-emerald-100 flex flex-col group hover:shadow-md transition-all h-[400px] overflow-hidden">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="p-2 bg-emerald-100 text-emerald-600 rounded-lg">🏅</span>
          <h3 className="text-slate-700 font-bold tracking-wide">资质与合规准入</h3>
        </div>
        {min_registered_capital_wuyuan && (
          <span className="px-3 py-1 bg-emerald-50 text-emerald-700 text-xs font-bold rounded-full border border-emerald-200 shadow-sm">
            资本金 ≥ {min_registered_capital_wuyuan}万
          </span>
        )}
      </div>

      <div className="overflow-y-auto custom-scrollbar pr-2 space-y-6 flex-1 pb-4">
        {/* 废标红线区 */}
        <div>
          <h4 className="text-xs font-bold text-slate-400 mb-3 uppercase tracking-wider flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-rose-400"></div> 废标项 (Mandatory)
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
