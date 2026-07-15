import React from 'react';

interface TimelineProps {
  biddingDeadline?: string;
  projectDuration?: string;
  qaDeadline?: string;
}

export function TimelineCard({ biddingDeadline, projectDuration, qaDeadline }: TimelineProps) {
  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-blue-100 flex flex-col justify-between group hover:shadow-md transition-all">
      <div className="flex items-center gap-3 mb-6">
        <span className="p-2 bg-blue-100 text-blue-600 rounded-lg">🕒</span>
        <h3 className="text-slate-700 font-bold tracking-wide">商务时限与排期</h3>
      </div>
      
      <div className="relative border-l-2 border-blue-200 ml-4 space-y-6">
        <div className="relative pl-6">
          <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-orange-400"></div>
          <p className="text-sm text-slate-500 font-medium">答疑截止时间</p>
          <p className="text-lg font-semibold text-slate-800">{qaDeadline || '未提及或暂无'}</p>
        </div>
        
        <div className="relative pl-6">
          <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-rose-500 shadow-[0_0_10px_rgba(225,29,72,0.5)]"></div>
          <p className="text-sm text-slate-500 font-medium">投标截止/开标时间 (高危)</p>
          <p className="text-lg font-bold text-rose-600">{biddingDeadline || '未获取到开标时间'}</p>
        </div>
        
        <div className="relative pl-6">
          <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full bg-white border-2 border-emerald-500"></div>
          <p className="text-sm text-slate-500 font-medium">合同交货/施工工期</p>
          <p className="text-lg font-semibold text-slate-800">{projectDuration || '未提及'}</p>
        </div>
      </div>
    </div>
  );
}
