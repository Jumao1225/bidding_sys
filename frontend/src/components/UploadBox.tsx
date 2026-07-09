import React, { useState, useMemo } from 'react';

export function UploadBox() {
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [result, setResult] = useState<any>(null);

  // 展开状态控制
  const [activeTab, setActiveTab] = useState<'qual' | 'risk'>('qual');

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
      setResult(null); // 上传新文件清空结果
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setResult(null);
    }
  };

  const handleAnalyze = async () => {
    if (!file) return;

    setIsAnalyzing(true);
    setProgress(0);
    setStatusText("准备上传...");
    setResult(null);

    // 模拟公司资质数据
    const mockCompanyQuals = "本公司具有建筑工程施工总承包一级资质，注册资金5000万元，拥有 ISO9001 质量认证体系。";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("company_quals", mockCompanyQuals);

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
      const response = await fetch(`${baseUrl}/api/v1/analysis/upload-and-analyze`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (data.code === 200 && data.data.task_id) {
        const taskId = data.data.task_id;
        setStatusText("任务已提交，排队中...");
        
        // 开启 SSE 监听
        const eventSource = new EventSource(`${baseUrl}/api/v1/sse/progress/${taskId}`);
        
        eventSource.onmessage = (event) => {
          try {
            const msgData = JSON.parse(event.data);
            if (msgData.status) setStatusText(msgData.status);
            if (msgData.progress) setProgress(msgData.progress);
            
            if (msgData.progress === 100) {
              if (msgData.result && !msgData.result.error) {
                setResult(msgData.result);
              } else if (msgData.result && msgData.result.error) {
                alert("解析出错: " + msgData.result.error);
              }
              eventSource.close();
              setTimeout(() => setIsAnalyzing(false), 500); // 延迟关闭以展示 100% 状态
            }
          } catch (e) {
            console.error("SSE parsing error", e);
          }
        };

        eventSource.onerror = (error) => {
          console.error("EventSource failed:", error);
          eventSource.close();
          setIsAnalyzing(false);
          alert("进度连接中断，请重试。");
        };

      } else {
        alert("解析失败: " + data.message);
        setIsAnalyzing(false);
      }
    } catch (error) {
      console.error("解析失败:", error);
      alert("解析请求失败，请检查后端服务及跨域设置。");
      setIsAnalyzing(false);
    }
  };

  // 高亮组件
  const HighlightText = ({ text, resultData }: { text: string, resultData: any }) => {
    const highlights = useMemo(() => {
      const list: any[] = [];
      if (resultData?.qualifications_analysis?.items) {
        resultData.qualifications_analysis.items.forEach((item: any) => {
          if (item.exact_quote) list.push({ quote: item.exact_quote, type: item.status, obj: item });
        });
      }
      if (resultData?.risks_analysis) {
        resultData.risks_analysis.forEach((risk: any) => {
          if (risk.exact_quote) list.push({ quote: risk.exact_quote, type: risk.severity, obj: risk });
        });
      }

      const indices: any[] = [];
      list.forEach(h => {
        if (!h.quote) return;
        const idx = text.indexOf(h.quote);
        if (idx !== -1) {
          indices.push({ start: idx, end: idx + h.quote.length, ...h });
        }
      });
      // Sort by start index
      indices.sort((a, b) => a.start - b.start);
      return indices;
    }, [text, resultData]);

    const nodes = [];
    let lastIndex = 0;

    highlights.forEach((h, i) => {
      if (h.start < lastIndex) return; // skip overlaps

      nodes.push(<span key={`text-${i}`} className="transition-colors duration-300">{text.substring(lastIndex, h.start)}</span>);

      let colorClass = 'bg-gray-200';
      if (h.type === '做不到' || h.type === '高') colorClass = 'bg-red-200 text-red-900 border-b-2 border-red-500 shadow-sm';
      else if (h.type === '努力可做到' || h.type === '中') colorClass = 'bg-orange-200 text-orange-900 border-b-2 border-orange-500 shadow-sm';
      else if (h.type === '可以做到' || h.type === '低') colorClass = 'bg-green-200 text-green-900 border-b-2 border-green-500 shadow-sm';

      nodes.push(
        <mark key={`mark-${i}`} className={`${colorClass} px-1 rounded cursor-help hover:ring-2 hover:ring-offset-1 transition-all duration-200`} title={h.obj.reason || h.obj.description}>
          {text.substring(h.start, h.end)}
        </mark>
      );
      lastIndex = h.end;
    });

    nodes.push(<span key="text-end" className="transition-colors duration-300">{text.substring(lastIndex)}</span>);

    return <div className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700">{nodes}</div>;
  };

  return (
    <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 h-full flex flex-col transition-all duration-300 hover:shadow-md">
      {/* 顶部上传区域 */}
      <div className="flex-shrink-0">
        <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
          <span className="bg-blue-100 p-1.5 rounded-lg text-blue-600">🤖</span>
          招标文件智能解析
        </h3>
        
        {!result && !isAnalyzing && (
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all duration-300 transform ${
              isDragging ? 'border-blue-500 bg-blue-50 scale-[1.02]' : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="flex flex-col items-center justify-center space-y-4">
              <div className={`w-16 h-16 rounded-full flex items-center justify-center text-3xl transition-transform duration-500 ${isDragging ? 'bg-blue-200 scale-110' : 'bg-blue-100'}`}>
                📄
              </div>
              <div>
                <p className="text-slate-700 font-medium">拖拽 Word/PDF 文件到此处，或</p>
                <label className="text-blue-600 hover:text-blue-800 font-bold cursor-pointer mt-1 block transition-colors">
                  点击浏览文件
                  <input type="file" className="hidden" accept=".pdf,.doc,.docx" onChange={handleFileSelect} />
                </label>
              </div>
              <p className="text-sm text-slate-400">支持 50MB 以内的文档</p>
            </div>
          </div>
        )}

        {file && !isAnalyzing && (
          <div className="mt-4 p-4 bg-slate-50 rounded-xl flex items-center justify-between border border-slate-200 hover:border-blue-300 transition-colors animate-fade-in-up">
            <div className="flex items-center space-x-4">
              <div className="p-3 bg-white rounded-lg shadow-sm text-2xl">📑</div>
              <div>
                <p className="font-bold text-slate-800">{file.name}</p>
                <p className="text-sm text-slate-500 font-medium">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
              </div>
            </div>
            <button
              onClick={handleAnalyze}
              className="px-6 py-2.5 rounded-xl font-bold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 shadow-lg shadow-blue-200 transform transition-all hover:-translate-y-0.5 hover:shadow-xl active:scale-95"
            >
              开始 AI 解析
            </button>
          </div>
        )}

        {/* 流式进度条 UI */}
        {isAnalyzing && (
          <div className="mt-6 p-8 bg-slate-50 rounded-2xl border border-blue-100 shadow-inner overflow-hidden relative animate-fade-in">
            <div className="absolute top-0 left-0 h-1.5 bg-gradient-to-r from-blue-400 via-indigo-500 to-purple-500 transition-all duration-700 ease-out" style={{ width: `${progress}%` }}></div>
            <div className="flex flex-col items-center justify-center space-y-4 relative z-10">
              <div className="relative">
                <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-100 border-t-blue-600"></div>
                <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-blue-600">
                  {progress}%
                </div>
              </div>
              <p className="text-slate-700 font-bold text-lg animate-pulse">{statusText}</p>
              <p className="text-slate-400 text-sm">正在调度多智能体网络进行深度分析...</p>
            </div>
          </div>
        )}
      </div>

      {/* 结果分屏区域 */}
      {result && !isAnalyzing && (
        <div className="mt-8 flex gap-6 flex-1 min-h-[500px] animate-fade-in-up">
          {/* 左侧原文对照区 */}
          <div className="w-1/2 flex flex-col border border-slate-200 rounded-2xl overflow-hidden bg-slate-50 shadow-sm transition-all hover:shadow-md">
            <div className="bg-white px-5 py-4 border-b border-slate-200 font-bold text-slate-800 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <span className="text-blue-500">🔍</span>
                <span>原文对照区</span>
              </div>
              <span className="text-xs text-slate-400 font-medium bg-slate-100 px-2 py-1 rounded-md">悬浮高亮查看说明</span>
            </div>
            <div className="p-6 overflow-y-auto flex-1 h-[600px] custom-scrollbar">
              <HighlightText text={result.extracted_text || ""} resultData={result} />
            </div>
          </div>

          {/* 右侧分析结论区 */}
          <div className="w-1/2 flex flex-col border border-slate-200 rounded-2xl overflow-hidden bg-white shadow-sm transition-all hover:shadow-md">
            <div className="bg-slate-50 flex border-b border-slate-200 p-1 gap-1">
              <button 
                className={`flex-1 py-3 px-4 font-bold text-sm transition-all rounded-xl ${activeTab === 'qual' ? 'text-blue-700 bg-white shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}
                onClick={() => setActiveTab('qual')}
              >
                🎯 履约盘点 <span className="ml-1 px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs">{result.qualifications_analysis?.match_score || 0}分</span>
              </button>
              <button 
                className={`flex-1 py-3 px-4 font-bold text-sm transition-all rounded-xl ${activeTab === 'risk' ? 'text-blue-700 bg-white shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}
                onClick={() => setActiveTab('risk')}
              >
                ⚠️ 风险提示 <span className="ml-1 px-2 py-0.5 bg-rose-100 text-rose-700 rounded-full text-xs">{result.risks_analysis?.length || 0}</span>
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto flex-1 h-[600px] bg-slate-50/50 custom-scrollbar">
              {activeTab === 'qual' && (
                <div className="space-y-4 animate-fade-in">
                  {result.qualifications_analysis?.items?.map((item: any, idx: number) => (
                    <div key={idx} className="p-5 rounded-xl border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow">
                      <div className="flex justify-between items-start mb-3">
                        <h4 className="font-bold text-slate-800 leading-tight pr-4">{item.requirement}</h4>
                        <span className={`flex-shrink-0 px-3 py-1 text-xs rounded-full font-bold shadow-sm ${
                          item.status === '做不到' ? 'bg-red-100 text-red-700 border border-red-200' :
                          item.status === '努力可做到' ? 'bg-orange-100 text-orange-700 border border-orange-200' :
                          'bg-green-100 text-green-700 border border-green-200'
                        }`}>
                          {item.status}
                        </span>
                      </div>
                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                        <p className="text-sm text-slate-600"><span className="font-bold text-slate-700 mr-2">🤖 AI 分析:</span>{item.reason}</p>
                      </div>
                    </div>
                  ))}
                  {(!result.qualifications_analysis?.items || result.qualifications_analysis.items.length === 0) && (
                    <div className="flex flex-col items-center justify-center h-48 text-slate-400">
                      <span className="text-4xl mb-3">✨</span>
                      <p>未发现明确资质要求</p>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'risk' && (
                <div className="space-y-4 animate-fade-in">
                  {result.risks_analysis?.map((risk: any, idx: number) => (
                    <div key={idx} className="p-5 rounded-xl border border-rose-100 bg-white shadow-sm hover:shadow-md transition-shadow relative overflow-hidden">
                      <div className={`absolute left-0 top-0 bottom-0 w-1 ${
                          risk.severity === '高' ? 'bg-rose-500' :
                          risk.severity === '中' ? 'bg-orange-400' :
                          'bg-blue-400'
                        }`}></div>
                      <div className="flex justify-between items-start mb-3 pl-2">
                        <div className="flex items-center space-x-2">
                          <span className="font-bold text-slate-800">{risk.risk_type}</span>
                        </div>
                        <span className={`px-3 py-1 text-xs rounded-full font-bold shadow-sm ${
                          risk.severity === '高' ? 'bg-rose-100 text-rose-700 border border-rose-200' :
                          risk.severity === '中' ? 'bg-orange-100 text-orange-700 border border-orange-200' :
                          'bg-blue-100 text-blue-700 border border-blue-200'
                        }`}>
                          {risk.severity}风险
                        </span>
                      </div>
                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 ml-2">
                        <p className="text-sm text-slate-600"><span className="font-bold text-slate-700 mr-2">⚠️ 描述:</span>{risk.description}</p>
                      </div>
                    </div>
                  ))}
                  {(!result.risks_analysis || result.risks_analysis.length === 0) && (
                    <div className="flex flex-col items-center justify-center h-48 text-slate-400">
                      <span className="text-4xl mb-3">🛡️</span>
                      <p>未发现明显风险条款</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
