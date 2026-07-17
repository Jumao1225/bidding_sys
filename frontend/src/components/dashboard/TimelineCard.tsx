import React from 'react';

interface TimelineProps {
  timeline?: {
    bid_deadline?: string | null;
    construction_period_days?: number | null;
    tender_milestones?: any[];
    acquisition_info?: any;
    contacts?: any[];
    document_requirements?: any;
  };
}

export function TimelineCard({ timeline = {} }: TimelineProps) {
  const bid_deadline = timeline.bid_deadline;
  const construction_period_days = timeline.construction_period_days;
  const tender_milestones = timeline.tender_milestones || [];
  const acquisition_info = timeline.acquisition_info;
  const document_requirements = timeline.document_requirements;

  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-blue-100 flex flex-col group hover:shadow-md transition-all h-[400px] overflow-hidden">
      <div className="flex items-center gap-3 mb-6 shrink-0">
        <span className="p-2 bg-blue-100 text-blue-600 rounded-lg">🕒</span>
        <h3 className="text-slate-700 font-bold tracking-wide flex-1">商务时限与排期</h3>
        {construction_period_days && (
          <span className="px-3 py-1 bg-slate-100 text-slate-600 text-xs font-bold rounded-full border border-slate-200">
            交付/工期: {construction_period_days}天
          </span>
        )}
      </div>
      
      <div className="overflow-y-auto custom-scrollbar pr-2 flex-1 pb-4">
        <div className="relative border-l-2 border-slate-200 ml-4 space-y-6">
          
          {/* 动态渲染时间节点 */}
          {tender_milestones.map((milestone, idx) => {
            const milestoneName = milestone.name || milestone.milestone_name;
            const deadline = milestone.deadline || milestone.time_description;
            const isHighRisk = milestoneName?.includes('开标') || milestoneName?.includes('截止');
            return (
              <div key={idx} className="relative pl-6">
                <div className={`absolute -left-[9px] top-1.5 w-4 h-4 rounded-full bg-white border-2 ${isHighRisk ? 'border-rose-500 shadow-[0_0_8px_rgba(225,29,72,0.4)]' : 'border-blue-400'}`}></div>
                <p className="text-xs text-slate-500 font-bold uppercase tracking-wider mb-0.5">{milestoneName}</p>
                <p className={`text-sm font-black ${isHighRisk ? 'text-rose-600' : 'text-slate-800'}`}>
                  {deadline || '未提取到明确时间'}
                </p>
                {(milestone.description || milestone.action_required) && (
                  <p className="text-[11px] text-slate-500 mt-1 leading-relaxed bg-slate-50 p-1.5 rounded inline-block border border-slate-100">{milestone.description || milestone.action_required}</p>
                )}
              </div>
            );
          })}

          {/* 如果后端的里程碑为空，至少显示开标时间和工期作为兜底 */}
          {tender_milestones.length === 0 && bid_deadline && (
            <div className="relative pl-6">
              <div className="absolute -left-[9px] top-1.5 w-4 h-4 rounded-full bg-white border-2 border-rose-500 shadow-[0_0_8px_rgba(225,29,72,0.4)]"></div>
              <p className="text-xs text-slate-500 font-bold uppercase tracking-wider mb-0.5">投标截止/开标时间 (高危)</p>
              <p className="text-sm font-black text-rose-600">{bid_deadline}</p>
            </div>
          )}

          {/* 其他零碎信息 (标书领购/密封) */}
          {(acquisition_info || document_requirements) && (
            <div className="relative pl-6 pt-4 mt-4 border-t border-slate-100 border-dashed">
              <div className="absolute -left-[9px] top-6 w-4 h-4 rounded-full bg-white border-2 border-slate-300"></div>
              {acquisition_info?.method && (
                <div className="mb-2">
                  <span className="text-xs text-slate-400 font-bold mr-2">标书领购:</span>
                  <span className="text-xs text-slate-600">{acquisition_info.method} {acquisition_info.price ? `(¥${acquisition_info.price})` : ''}</span>
                </div>
              )}
              {document_requirements && (
                <div>
                  <span className="text-xs text-slate-400 font-bold mr-2">装订/份数:</span>
                  <span className="text-xs text-slate-600">正本 {document_requirements.original_copies || document_requirements.original_count || 1}，副本 {document_requirements.duplicate_copies || document_requirements.copy_count || 0}</span>
                  {(document_requirements.seal_requirements || document_requirements.sealing_requirements) && (
                    <div className="text-[10px] text-slate-400 mt-1 line-clamp-2">{document_requirements.seal_requirements || document_requirements.sealing_requirements}</div>
                  )}
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
