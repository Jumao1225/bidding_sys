import React from 'react';

interface EngineeringProps {
  engineering?: {
    special_working_conditions?: string[];
    site_environment_constraints?: string | null;
    mandatory_standards?: string[];
    tech_validation?: any;
    safety_and_env_requirements?: string[];
  };
  onReextract?: () => void;
  isRetrying?: boolean;
}

export function EngineeringCard({ engineering = {}, onReextract, isRetrying = false }: EngineeringProps) {
  const special_working_conditions = engineering.special_working_conditions || [];
  const site_environment_constraints = engineering.site_environment_constraints;
  const mandatory_standards = engineering.mandatory_standards || [];
  const tech_validation = engineering.tech_validation;
  const safety_and_env_requirements = engineering.safety_and_env_requirements || [];

  const hasTechValidation = tech_validation && tech_validation.requires_sample_or_poc;

  return (
    <div className={`bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-amber-100 flex flex-col group hover:shadow-md transition-all h-[400px] overflow-hidden relative ${isRetrying ? 'opacity-70 pointer-events-none' : ''}`}>
      {isRetrying && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-white/40 backdrop-blur-[1px] rounded-3xl">
          <svg className="animate-spin h-8 w-8 text-amber-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      )}
      <div className="flex items-center gap-3 mb-4 shrink-0">
        <span className="p-2 bg-amber-100 text-amber-600 rounded-lg">🏗️</span>
        <h3 className="text-slate-700 font-bold tracking-wide flex-1">施工痛点与技术防线</h3>
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
      
      <div className="overflow-y-auto custom-scrollbar pr-2 space-y-5 flex-1 pb-4">
        
        {/* 高危技术验证 (POC/样品/检测) */}
        {hasTechValidation && (
          <div className="bg-rose-50 p-3 rounded-xl border border-rose-200 shadow-sm relative overflow-hidden">
            <div className="absolute top-0 right-0 w-12 h-12 bg-rose-500/10 rounded-full blur-xl -mr-2 -mt-2"></div>
            <h4 className="text-xs font-bold text-rose-600 mb-2 uppercase flex items-center gap-1 relative z-10">
              <span className="text-rose-500">🚨</span> 实体验证红线 (废标风险高)
            </h4>
            <div className="text-xs text-rose-800 font-medium leading-relaxed relative z-10">
              {tech_validation.description}
            </div>
          </div>
        )}

        {/* 高危施工工况 */}
        <div>
          <h4 className="text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">高危施工工况 (AI 自动扫雷)</h4>
          {special_working_conditions.length > 0 ? (
            <ul className="space-y-2">
              {special_working_conditions.map((point, idx) => (
                <li key={idx} className="flex gap-2 text-sm text-slate-700 bg-orange-50/50 p-2.5 rounded-lg border border-orange-100/50">
                  <span className="text-orange-500 mt-0.5 shrink-0">⚠️</span>
                  <span className="leading-relaxed font-medium">{point}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-xs text-emerald-600 bg-emerald-50 p-2.5 rounded-lg border border-emerald-100 flex items-center gap-2">
              <span>✅</span> 未扫描到特殊的高危施工痛点
            </div>
          )}
        </div>

        {/* 现场环境约束 */}
        {site_environment_constraints && (
          <div>
            <h4 className="text-xs font-bold text-slate-400 mb-2 uppercase tracking-wider">现场环境约束</h4>
            <div className="text-sm text-slate-600 bg-slate-50 p-3 rounded-lg border border-slate-100 leading-relaxed italic">
              {site_environment_constraints}
            </div>
          </div>
        )}

        {/* 标准规范与安全要求 */}
        {(mandatory_standards.length > 0 || safety_and_env_requirements.length > 0) && (
          <div className="grid grid-cols-1 gap-3 border-t border-slate-100 pt-3">
            {mandatory_standards.length > 0 && (
              <div>
                <h4 className="text-[10px] font-bold text-slate-400 mb-1">强制标准规范</h4>
                <div className="flex flex-wrap gap-1.5">
                  {mandatory_standards.map((std, idx) => (
                    <span key={`std-${idx}`} className="px-2 py-1 bg-slate-100 text-slate-600 rounded text-[10px] font-medium border border-slate-200">
                      {std}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {safety_and_env_requirements.length > 0 && (
              <div>
                <h4 className="text-[10px] font-bold text-slate-400 mb-1">安全文明要求</h4>
                <ul className="space-y-1">
                  {safety_and_env_requirements.map((req, idx) => (
                    <li key={`req-${idx}`} className="text-[11px] text-slate-500 flex items-start gap-1">
                      <span className="text-emerald-500">•</span> {req}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
