import React, { useState, useRef } from 'react';

export const DocxDebuggerPage: React.FC = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [promptInput, setPromptInput] = useState<string>('将项目名称修改为’智慧城市大模型填报系统’，投标人名称修改为’聚猫科技有限公司’，报价改为’680,000.00’');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [isGeneratingSample, setIsGeneratingSample] = useState<boolean>(false);
  const [modifiedBlob, setModifiedBlob] = useState<Blob | null>(null);
  const [downloadFilename, setDownloadFilename] = useState<string>('modified_bidding.docx');
  const [modifiedKeys, setModifiedKeys] = useState<string[]>([]);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  
  // 新增高级 Skill 工具链状态
  const [isSkillToolProcessing, setIsSkillToolProcessing] = useState<boolean>(false);
  const [extractedComments, setExtractedComments] = useState<Array<{id: string; author: string; date: string; text: string}> | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // 1. 处理文件选择
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith('.docx')) {
        setStatusMessage({ type: 'error', text: '仅支持上传 .docx 格式的 Word 文档！' });
        return;
      }
      setSelectedFile(file);
      setModifiedBlob(null);
      setStatusMessage({ type: 'info', text: `已成功选择文件: ${file.name} (${(file.size / 1024).toFixed(1)} KB)` });
    }
  };

  // 2. 拖拽文件支持
  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith('.docx')) {
        setStatusMessage({ type: 'error', text: '仅支持上传 .docx 格式的 Word 文档！' });
        return;
      }
      setSelectedFile(file);
      setModifiedBlob(null);
      setStatusMessage({ type: 'info', text: `已拖拽选择文件: ${file.name} (${(file.size / 1024).toFixed(1)} KB)` });
    }
  };

  // 3. 一键生成测试模版并自动设置为当前调试文件
  const handleFetchSampleTemplate = async () => {
    setIsGeneratingSample(true);
    setStatusMessage({ type: 'info', text: '正在从后端拉取标准标书测试模版...' });
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/generate-sample`);
      if (!res.ok) {
        throw new Error('获取测试模版失败');
      }
      const blob = await res.blob();
      const sampleFile = new File([blob], 'bidding_test_template.docx', {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      setSelectedFile(sampleFile);
      setModifiedBlob(null);
      setStatusMessage({ type: 'success', text: '成功载入标准测试模版！你可以直接输入修改指令进行调试。' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `拉取测试模版失败: ${err.message}` });
    } finally {
      setIsGeneratingSample(false);
    }
  };

  // 4. 提交调试修改请求
  const handleSubmitModify = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件，或点击拉取测试模版！' });
      return;
    }
    if (!promptInput.trim()) {
      setStatusMessage({ type: 'error', text: '请输入针对该 Word 的修改指令！' });
      return;
    }

    setIsProcessing(true);
    setModifiedBlob(null);
    setModifiedKeys([]);
    setStatusMessage({ type: 'info', text: '正在基于 docx 技能规范执行原位修改与下划线保持...' });

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('prompt', promptInput);

      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/debug-modify`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({ detail: '修改请求失败' }));
        throw new Error(errorData.detail || '修改文件失败');
      }

      // 读取 Response Headers 中的修改字段 Key 列表（增加 decodeURIComponent 解码）
      const keysHeader = res.headers.get('X-Modified-Keys');
      if (keysHeader) {
        try {
          const decodedStr = decodeURIComponent(keysHeader);
          const parsedKeys = JSON.parse(decodedStr);
          setModifiedKeys(parsedKeys);
        } catch (e) {
          console.error('解析修改键名失败', e);
        }
      }

      const blob = await res.blob();
      setModifiedBlob(blob);
      setDownloadFilename(`modified_${selectedFile.name}`);
      setStatusMessage({ type: 'success', text: '🎉 Word 修改成功！下划线与排版样式已保留，可直接下载结果。' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `修改失败: ${err.message}` });
    } finally {
      setIsProcessing(false);
    }
  };

  // 5. 触发浏览器文件下载
  const handleDownloadResult = () => {
    if (!modifiedBlob) return;
    const url = window.URL.createObjectURL(modifiedBlob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  // 6. 开发者高级工具: 接受全文修订痕迹
  const handleAcceptTrackedChanges = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件！' });
      return;
    }
    setIsSkillToolProcessing(true);
    setStatusMessage({ type: 'info', text: '正在清理与全量接受文档中的修订痕迹...' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/accept-tracked-changes`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('接受修订痕迹失败');
      const blob = await res.blob();
      setModifiedBlob(blob);
      setDownloadFilename(`accepted_${selectedFile.name}`);
      setStatusMessage({ type: 'success', text: '🎉 成功清除文档中的所有红线修订痕迹，生成干净正文！' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `处理失败: ${err.message}` });
    } finally {
      setIsSkillToolProcessing(false);
    }
  };

  // 7. 开发者高级工具: 自动插入/更新目录
  const handleInsertTOC = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件！' });
      return;
    }
    setIsSkillToolProcessing(true);
    setStatusMessage({ type: 'info', text: '正在为文档生成与配置动态 Word 目录...' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/insert-toc`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('自动插入目录失败');
      const blob = await res.blob();
      setModifiedBlob(blob);
      setDownloadFilename(`toc_${selectedFile.name}`);
      setStatusMessage({ type: 'success', text: '🎉 成功为文档配置动态目录域！在 Word 中打开时将自动刷新。' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `处理失败: ${err.message}` });
    } finally {
      setIsSkillToolProcessing(false);
    }
  };

  // 8. 开发者高级工具: 隐秘元数据脱敏清洗
  const handleScrubPrivacy = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件！' });
      return;
    }
    setIsSkillToolProcessing(true);
    setStatusMessage({ type: 'info', text: '正在脱敏清洗 Word 中的隐秘作者信息与 RSID 历史痕迹...' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/scrub-privacy`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('隐秘数据脱敏清洗失败');
      const blob = await res.blob();
      setModifiedBlob(blob);
      setDownloadFilename(`scrubbed_${selectedFile.name}`);
      setStatusMessage({ type: 'success', text: '🎉 成功抹去文档内置作者、修改时间及 RSID 调试轨迹！' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `处理失败: ${err.message}` });
    } finally {
      setIsSkillToolProcessing(false);
    }
  };

  // 9. 开发者高级工具: 提取全文审阅批注
  const handleExtractComments = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件！' });
      return;
    }
    setIsSkillToolProcessing(true);
    setExtractedComments(null);
    setStatusMessage({ type: 'info', text: '正在抓取文档包含的全部审阅批注...' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/extract-comments`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('提取批注失败');
      const data = await res.json();
      setExtractedComments(data.data || []);
      setStatusMessage({ type: 'success', text: `🎉 成功抓取到 ${data.data?.length || 0} 条审阅批注！` });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `提取失败: ${err.message}` });
    } finally {
      setIsSkillToolProcessing(false);
    }
  };

  // 10. 开发者高级工具: 彻底清空 Word 批注
  const handleStripComments = async () => {
    if (!selectedFile) {
      setStatusMessage({ type: 'error', text: '请先上传 Word (.docx) 文件！' });
      return;
    }
    setIsSkillToolProcessing(true);
    setStatusMessage({ type: 'info', text: '正在从 Word 中彻底抹除与剔除所有批注节点...' });
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await fetch(`${baseUrl}/api/v1/docx/strip-comments`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error('剔除批注失败');
      const blob = await res.blob();
      setModifiedBlob(blob);
      setExtractedComments([]);
      setDownloadFilename(`no_comments_${selectedFile.name}`);
      setStatusMessage({ type: 'success', text: '🎉 成功彻底抹除 Word 文件内的所有批注，生成干净交付文档！' });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: `处理失败: ${err.message}` });
    } finally {
      setIsSkillToolProcessing(false);
    }
  };

  // 快捷 Prompt 快选 Pills
  const promptTemplates = [
    "将项目名称修改为’智能AI招投标项目’，投标人名称修改为’聚猫科技’，报价改为’980,000.00’",
    "修改法定代表人为’张三’，授权代理人为’李四’，工期改为’60日历天’",
    "将项目编号修改为’SZ-2026-009’，投标日期改为’2026年07月24日’"
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-fade-in text-slate-100">
      {/* 顶部 Heading Banner */}
      <div className="relative overflow-hidden bg-gradient-to-r from-slate-900 via-indigo-950 to-blue-900 p-8 rounded-3xl border border-white/10 shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl -mr-20 -mt-20 pointer-events-none"></div>
        <div className="relative z-10 space-y-3">
          <div className="inline-flex items-center px-3 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs font-semibold border border-blue-400/30">
            ✨ DOCX SKILL INTEGRATION DEBUGGER
          </div>
          <h1 className="text-3xl font-extrabold bg-gradient-to-r from-white via-slate-100 to-blue-200 bg-clip-text text-transparent">
            Word 格式与指令改写智能调试工作台
          </h1>
          <p className="text-slate-300 text-sm max-w-3xl leading-relaxed">
            本实验室页面专门用于测试与调试基于 <code className="bg-black/40 text-blue-300 px-2 py-0.5 rounded border border-blue-500/30 font-mono text-xs">docx 技能</code> 的 Word 原位改写。
            上传你的 <code className="text-amber-300">.docx</code> 标书文件，并输入自然语言指令（支持指定修改项目名称、格式下划线保留、DXA 双宽度表格填充等）。
          </p>
        </div>
      </div>

      {/* 主工作区网格 (2 列) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* 左侧：文件上传与指令控制盘 (7 列) */}
        <div className="lg:col-span-7 space-y-6">
          
          {/* 文件上传 Zone */}
          <div className="bg-slate-900/80 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white flex items-center">
                <svg className="w-5 h-5 mr-2 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 0115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                1. 选择或拖拽上传 Word 文件
              </h2>
              <button
                onClick={handleFetchSampleTemplate}
                disabled={isGeneratingSample}
                className="px-3 py-1.5 bg-blue-600/30 hover:bg-blue-600/50 text-blue-300 border border-blue-500/40 rounded-xl text-xs font-semibold transition-all flex items-center space-x-1.5 shadow-sm"
              >
                {isGeneratingSample ? (
                  <span className="inline-block animate-spin mr-1">🌀</span>
                ) : (
                  <span>📄</span>
                )}
                <span>一键拉取测试模版</span>
              </button>
            </div>

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all ${
                selectedFile
                  ? 'border-emerald-500/50 bg-emerald-950/20'
                  : 'border-slate-700 hover:border-blue-500/50 bg-slate-950/40 hover:bg-slate-800/40'
              }`}
            >
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".docx"
                className="hidden"
              />

              {selectedFile ? (
                <div className="space-y-2">
                  <div className="w-12 h-12 bg-emerald-500/20 text-emerald-400 rounded-2xl flex items-center justify-center mx-auto text-2xl border border-emerald-500/30">
                    📝
                  </div>
                  <div className="text-emerald-300 font-bold">{selectedFile.name}</div>
                  <div className="text-xs text-slate-400">
                    文件大小: {(selectedFile.size / 1024).toFixed(1)} KB | 点击或重新拖拽替换
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="w-12 h-12 bg-blue-500/10 text-blue-400 rounded-2xl flex items-center justify-center mx-auto text-2xl border border-white/5">
                    📤
                  </div>
                  <div className="text-slate-300 font-medium text-sm">
                    点击此处选择文件，或将 <span className="text-blue-400 font-semibold">.docx</span> 文件拖拽至此
                  </div>
                  <p className="text-xs text-slate-500">支持真实招投标 Word 模版与标准响应文件格式</p>
                </div>
              )}
            </div>
          </div>

          {/* 自然语言指令输入 Card */}
          <div className="bg-slate-900/80 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-white flex items-center">
              <svg className="w-5 h-5 mr-2 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              2. 输入修改指令 Prompt
            </h2>

            {/* 快捷模板 Pills */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-slate-400">快捷提示词模版 (点击自动套用)：</span>
              <div className="flex flex-wrap gap-2">
                {promptTemplates.map((tpl, i) => (
                  <button
                    key={i}
                    onClick={() => setPromptInput(tpl)}
                    className="text-xs bg-slate-800/80 hover:bg-indigo-900/50 text-slate-300 hover:text-indigo-200 border border-white/5 hover:border-indigo-500/30 px-3 py-1.5 rounded-xl transition-all text-left"
                  >
                    💡 {tpl.slice(0, 26)}...
                  </button>
                ))}
              </div>
            </div>

            <textarea
              rows={4}
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="请输入具体的修改指令，例如：将项目名称修改为XXX，投标人名称为聚猫科技，报价改为50万元..."
              className="w-full bg-slate-950/60 border border-white/10 rounded-2xl p-4 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all font-mono"
            />

            <button
              onClick={handleSubmitModify}
              disabled={isProcessing || !selectedFile}
              className={`w-full py-4 rounded-2xl font-bold text-white shadow-xl transition-all flex items-center justify-center space-x-2 ${
                isProcessing || !selectedFile
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-white/5'
                  : 'bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 shadow-blue-500/20 active:scale-[0.99]'
              }`}
            >
              {isProcessing ? (
                <>
                  <span className="inline-block animate-spin mr-2">🌀</span>
                  <span>正在执行 Word 修改与下划线保持...</span>
                </>
              ) : (
                <>
                  <span>🚀</span>
                  <span>提交调试并执行 Word 原位修改</span>
                </>
              )}
            </button>
          </div>

          {/* 🛠️ 高级 DOCX Skill 拓展工具箱 Card */}
          <div className="bg-slate-900/80 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl space-y-4">
            <h2 className="text-lg font-bold text-white flex items-center">
              <svg className="w-5 h-5 mr-2 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              3. 高级 Word Skill 拓展工具箱 (Documents Skill)
            </h2>
            <p className="text-xs text-slate-400">
              集成 Codex Documents 插件工具链，对已选 DOCX 目标执行专业级修改与清理。
            </p>

            <div className="grid grid-cols-2 gap-3 pt-2">
              <button
                onClick={handleAcceptTrackedChanges}
                disabled={isSkillToolProcessing || !selectedFile}
                className="p-3 bg-slate-800/80 hover:bg-purple-900/40 text-purple-200 border border-purple-500/20 hover:border-purple-500/50 rounded-2xl text-xs font-semibold transition-all text-left flex flex-col space-y-1"
              >
                <div className="flex items-center space-x-1.5 font-bold">
                  <span>📝</span>
                  <span>接受全文修订</span>
                </div>
                <span className="text-[10px] text-slate-400 font-normal">一键清除红线痕迹生成干净正文</span>
              </button>

              <button
                onClick={handleInsertTOC}
                disabled={isSkillToolProcessing || !selectedFile}
                className="p-3 bg-slate-800/80 hover:bg-blue-900/40 text-blue-200 border border-blue-500/20 hover:border-blue-500/50 rounded-2xl text-xs font-semibold transition-all text-left flex flex-col space-y-1"
              >
                <div className="flex items-center space-x-1.5 font-bold">
                  <span>📑</span>
                  <span>自动生成目录</span>
                </div>
                <span className="text-[10px] text-slate-400 font-normal">自动插入 Word TOC 动态目录域</span>
              </button>

              <button
                onClick={handleScrubPrivacy}
                disabled={isSkillToolProcessing || !selectedFile}
                className="p-3 bg-slate-800/80 hover:bg-emerald-900/40 text-emerald-200 border border-emerald-500/20 hover:border-emerald-500/50 rounded-2xl text-xs font-semibold transition-all text-left flex flex-col space-y-1"
              >
                <div className="flex items-center space-x-1.5 font-bold">
                  <span>🛡️</span>
                  <span>隐私脱敏清洗</span>
                </div>
                <span className="text-[10px] text-slate-400 font-normal">清除作者姓名、修改时间与轨迹</span>
              </button>

              <button
                onClick={handleExtractComments}
                disabled={isSkillToolProcessing || !selectedFile}
                className="p-3 bg-slate-800/80 hover:bg-amber-900/40 text-amber-200 border border-amber-500/20 hover:border-amber-500/50 rounded-2xl text-xs font-semibold transition-all text-left flex flex-col space-y-1"
              >
                <div className="flex items-center space-x-1.5 font-bold">
                  <span>💬</span>
                  <span>提取全文批注</span>
                </div>
                <span className="text-[10px] text-slate-400 font-normal">抓取文档内置的全部审阅批注</span>
              </button>

              <button
                onClick={handleStripComments}
                disabled={isSkillToolProcessing || !selectedFile}
                className="p-3 bg-slate-800/80 hover:bg-rose-900/40 text-rose-200 border border-rose-500/20 hover:border-rose-500/50 rounded-2xl text-xs font-semibold transition-all text-left flex flex-col space-y-1"
              >
                <div className="flex items-center space-x-1.5 font-bold">
                  <span>✂️</span>
                  <span>清空 Word 批注</span>
                </div>
                <span className="text-[10px] text-slate-400 font-normal">直接从 Word 中擦除所有批注节点</span>
              </button>
            </div>
          </div>
        </div>

        {/* 右侧：结果展示与测试导出一览 (5 列) */}
        <div className="lg:col-span-5 space-y-6">
          
          {/* 修改状态与日志面板 */}
          <div className="bg-slate-900/80 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl space-y-5 min-h-[420px] flex flex-col justify-between">
            <div className="space-y-4">
              <h2 className="text-lg font-bold text-white flex items-center border-b border-white/10 pb-3">
                <svg className="w-5 h-5 mr-2 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                3. 修改结果与导出
              </h2>

              {/* Status Notice Toast */}
              {statusMessage && (
                <div
                  className={`p-4 rounded-2xl text-xs font-medium border leading-relaxed ${
                    statusMessage.type === 'error'
                      ? 'bg-rose-950/40 border-rose-500/30 text-rose-300'
                      : statusMessage.type === 'success'
                      ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
                      : 'bg-blue-950/40 border-blue-500/30 text-blue-300'
                  }`}
                >
                  {statusMessage.text}
                </div>
              )}

              {/* 已成功匹配并修改的字段名 Chips */}
              {modifiedKeys.length > 0 && (
                <div className="space-y-2 bg-slate-950/40 p-4 rounded-2xl border border-white/5">
                  <div className="text-xs text-slate-400 font-semibold">✨ 本次识别并修改的字段项：</div>
                  <div className="flex flex-wrap gap-1.5">
                    {modifiedKeys.map((key, idx) => (
                      <span
                        key={idx}
                        className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-lg text-xs font-mono"
                      >
                        ✓ {key}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* docx 技能特性说明 */}
              <div className="space-y-3 bg-slate-950/30 p-4 rounded-2xl border border-white/5 text-xs text-slate-400 leading-relaxed">
                <div className="font-bold text-slate-300 border-b border-white/5 pb-1">🛡️ docx 技能核心控制原则：</div>
                <ul className="list-disc list-inside space-y-1 text-slate-400">
                  <li><strong className="text-slate-200">下划线精准保留</strong>：仅在原文该位置带有 <code className="text-amber-300">w:u</code> 或连续下划线时显示下划线。</li>
                  <li><strong className="text-slate-200">表格 DXA 双重列宽</strong>：同时设定 Table 与 Cell 的 DXA 像素宽度。</li>
                  <li><strong className="text-slate-200">纯黑字体</strong>：导出文字统一设为 <code className="text-amber-300">RGB(0,0,0)</code>，无杂色。</li>
                </ul>
              </div>
            </div>

            {/* 下载结果按钮 */}
            {modifiedBlob ? (
              <button
                onClick={handleDownloadResult}
                className="w-full py-4 bg-emerald-600 hover:bg-emerald-500 active:scale-[0.99] text-white rounded-2xl font-bold shadow-xl shadow-emerald-600/20 transition-all flex items-center justify-center space-x-2"
              >
                <span>💾</span>
                <span>下载修改后的 Word (.docx)</span>
              </button>
            ) : (
              <div className="text-center py-4 text-xs text-slate-500 border border-dashed border-slate-800 rounded-2xl">
                提交修改指令后可直接点击下载
              </div>
            )}
          </div>

          {/* 提取出的批注展示卡片 */}
          {extractedComments !== null && (
            <div className="bg-slate-900/80 backdrop-blur-xl border border-white/10 p-6 rounded-3xl shadow-xl space-y-4">
              <h3 className="text-sm font-bold text-amber-300 flex items-center justify-between border-b border-white/10 pb-2">
                <span>💬 文档审阅批注列表 ({extractedComments.length})</span>
                <button
                  onClick={() => setExtractedComments(null)}
                  className="text-xs text-slate-400 hover:text-white"
                >
                  ✕ 关闭
                </button>
              </h3>

              {extractedComments.length === 0 ? (
                <div className="text-xs text-slate-500 text-center py-4">
                  该 Word 文档中未发现任何审阅批注。
                </div>
              ) : (
                <div className="space-y-2.5 max-h-60 overflow-y-auto pr-1">
                  {extractedComments.map((item) => (
                    <div key={item.id} className="bg-slate-950/60 p-3 rounded-xl border border-white/5 space-y-1 text-xs">
                      <div className="flex items-center justify-between text-slate-400 font-medium">
                        <span className="text-amber-400 font-semibold">👤 {item.author}</span>
                        <span className="text-[10px] text-slate-500">{item.date}</span>
                      </div>
                      <p className="text-slate-200 text-xs leading-relaxed font-sans">{item.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>

      </div>
    </div>
  );
};
