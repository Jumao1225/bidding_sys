import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Shield, CheckCircle2, Upload, FileText, Activity, Settings, Trash2, RefreshCw, MessageSquare, Sparkles, X
} from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip } from 'recharts';
import {
  fetchTenderDocuments,
  uploadBidDocument,
  triggerBidScore,
  getLatestScoreResult,
  getScoreResultDetail,
  deleteBidDocument,
  rescoreCategory,
  type TenderDocumentRecord,
  type ScoreResultDetail,
  type ScoreItem
} from '../api/bidScorerApi';
import { ChunkAnnotationWorkbench } from '../components/ChunkAnnotationWorkbench';

export const BidScorerLab: React.FC = () => {
  // 1. 数据状态与配置池
  const [tenderDocs, setTenderDocs] = useState<TenderDocumentRecord[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadedDocId, setUploadedDocId] = useState<string>('');
  const [chunkCount, setChunkCount] = useState<number>(0);
  const [scoringRounds, setScoringRounds] = useState<number>(3);
  const [showWorkbench, setShowWorkbench] = useState<boolean>(false);


  // 2. 交互进行时态
  const [loadingDocs, setLoadingDocs] = useState<boolean>(true);
  const [uploading, setUploading] = useState<boolean>(false);
  const [scoring, setScoring] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [statusMessage, setStatusMessage] = useState<string>('');

  // 3. 结果产出物
  const [scoreResult, setScoreResult] = useState<ScoreResultDetail | null>(null);
  const [expandedItemId, setExpandedItemId] = useState<string | null>(null);

  // 4. 微调重算交互（无遮罩内嵌面板）状态
  const [activeRescoreKey, setActiveRescoreKey] = useState<string | null>(null); // 当前展开微调面板的 key ('cat:XXX' 或 'item:YYY')
  const [rescoreInstructionMap, setRescoreInstructionMap] = useState<Record<string, string>>({}); // 存储各个 key 对应的指令草稿
  const [rescoringKey, setRescoringKey] = useState<string | null>(null); // 当前正在重算加载的 key

  const handleApplyRescore = async (
    key: string,
    categoryName: string,
    itemCode?: string,
    targetTitle?: string
  ) => {
    const instruction = rescoreInstructionMap[key];
    if (!scoreResult || !categoryName || !instruction?.trim()) return;
    try {
      setRescoringKey(key);
      setErrorMessage('');
      const targetName = itemCode ? `评分项 [${targetTitle || itemCode}]` : `大类 [${categoryName}]`;
      setStatusMessage(`正在应用微调规则，重新评估 ${targetName}...`);
      const targetResultId = scoreResult.id || scoreResult.result_id;
      const updatedDetail = await rescoreCategory(
        targetResultId!,
        categoryName,
        instruction.trim(),
        1,
        itemCode || undefined
      );
      setScoreResult(updatedDetail);
      setStatusMessage(`✅ ${targetName} 得分微调成功，总分已更新。`);
      setActiveRescoreKey(null);
    } catch (err: any) {
      setErrorMessage(err.message || '微调重算发生错误');
    } finally {
      setRescoringKey(null);
    }
  };

  // 初始化拉取招标文件标准池
  useEffect(() => {
    const loadDocs = async () => {
      try {
        setLoadingDocs(true);
        const docs = await fetchTenderDocuments();
        setTenderDocs(docs);
        if (docs.length > 0) {
          setSelectedSourceId(docs[0].id);
        }
      } catch (err: any) {
        setErrorMessage(err.message || '获取招标文件列表失败');
      } finally {
        setLoadingDocs(false);
      }
    };
    loadDocs();
  }, []);

  // 自动检测并加载已入库的历史打分记录
  useEffect(() => {
    if (!uploadedDocId) return;

    let isMounted = true;
    const autoLoadHistoryScore = async () => {
      try {
        const latest = await getLatestScoreResult(uploadedDocId);
        if (latest && (latest.id || latest.result_id)) {
          const targetId = latest.id || latest.result_id;
          const fullDetail = await getScoreResultDetail(targetId!);
          if (isMounted) {
            setScoreResult(fullDetail);
            setStatusMessage('⚡ 已自动加载该投标文件的历史打分报告与细则明细！');
          }
        } else {
          if (isMounted) {
            setStatusMessage('✅ 投标文件解析准备就绪，可点击【开始智能打分】进行评估。');
          }
        }
      } catch (err: any) {
        console.warn('自动检测历史打分记录失败:', err);
      }
    };

    autoLoadHistoryScore();
    return () => {
      isMounted = false;
    };
  }, [uploadedDocId]);

  // 触发本地选择目标标书并提交超速解析
  const handleUploadBid = async () => {
    if (!selectedFile) {
      setErrorMessage('请先选择要评估的投标文件（支持 PDF / DOCX）。');
      return;
    }
    if (!selectedSourceId) {
      setErrorMessage('请先在左侧选择评分依据的招标文件。');
      return;
    }
    try {
      setUploading(true);
      setErrorMessage('');
      setStatusMessage('正在上传并解析投标文件...');
      const res = await uploadBidDocument(selectedFile, selectedSourceId);
      setUploadedDocId(res.document_id);
      setChunkCount(res.chunk_count || 0);
      setStatusMessage(`上传解析完成！文档已拆分为 ${res.chunk_count} 个切片，可开始智能打分。`);
      setScoreResult(null); // 上传新文件时置空过往报表
    } catch (err: any) {
      setErrorMessage(err.message || '上传失败，请稍后重试。');
    } finally {
      setUploading(false);
    }
  };

  // 命令激活 AI 并发评估计算
  const handleStartScoring = async () => {
    if (!uploadedDocId) {
      setErrorMessage('请先上传有效的投标文件！');
      return;
    }
    try {
      setScoring(true);
      setErrorMessage('');
      setStatusMessage('正在基于招标文件细则对投标文件进行多维度深度打分评估...');
      const summaryResult = await triggerBidScore(uploadedDocId, selectedSourceId, scoringRounds);
      // 为展示完整的穿透打分明细及建议，立马二次回提详细全本
      const targetResultId = summaryResult.result_id || summaryResult.id;
      const fullDetail = await getScoreResultDetail(targetResultId!);
      setScoreResult(fullDetail);
      setStatusMessage('智能打分评估完成！');
    } catch (err: any) {
      setErrorMessage(err.message || '评估计算过程发生错误。');
    } finally {
      setScoring(false);
    }
  };

  // 手动删除当前测试文档记录
  const handleDeleteBid = async () => {
    if (!uploadedDocId) {
      setErrorMessage('请先上传投标文件！');
      return;
    }
    try {
      setUploading(true);
      setErrorMessage('');
      setStatusMessage('正在删除该投标文件的解析与历史打分记录...');
      await deleteBidDocument(uploadedDocId);
      setUploadedDocId('');
      setChunkCount(0);
      setScoreResult(null);
      setStatusMessage('✅ 已清除该投标文件的解析及打分记录，可重新上传文件。');
    } catch (err: any) {
      setErrorMessage(err.message || '删除记录失败。');
    } finally {
      setUploading(false);
    }
  };

  // 为 Recharts 构建转化雷达矩阵
  const radarData = scoreResult && scoreResult.category_scores
    ? Object.entries(scoreResult.category_scores).map(([cat, val]) => ({
        subject: cat,
        scoreRate: Math.round((val.score / val.max_total) * 100) || 0,
        rawScore: val.score,
        maxScore: val.max_total
      }))
    : [];

  return (
    <div className="min-h-screen w-full bg-transparent text-slate-100 font-sans p-6 overflow-y-auto pb-24">
      
      {/* ===================== 1. 全局大标与控制台头罩 (Hero Title) ===================== */}
      <motion.div 
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative mb-8 p-8 rounded-3xl bg-slate-900/90 border border-slate-800/90 shadow-2xl backdrop-blur-2xl overflow-hidden"
      >
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-bl from-emerald-500/10 via-cyan-500/10 to-transparent rounded-full blur-3xl pointer-events-none -mr-20 -mt-20" />
        <div className="flex flex-col md:flex-row md:items-center md:justify-between relative z-10 gap-4">
          <div className="space-y-2">
            <div className="flex items-center space-x-3">
              <div className="p-3 bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 rounded-2xl border border-emerald-500/30 text-emerald-400 shadow-inner">
                <Shield className="w-8 h-8 animate-pulse" />
              </div>
              <h1 className="text-3xl font-extrabold tracking-tight text-white bg-clip-text">
                智能标书评估与打分工作台 <span className="text-sm px-3 py-1 bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 text-emerald-300 rounded-full font-mono border border-emerald-500/30">AI 规则校验与评估</span>
              </h1>
            </div>
            <p className="text-sm text-slate-400 font-normal pl-1 leading-relaxed max-w-3xl">
              严格依据所选《招标文件》中的评分细则与标准，对投标文件进行多维度智能化打分、扣分原因分析及改进建议生成，确保评估过程客观透明、可追溯。
            </p>
          </div>

          <div className="flex items-center space-x-3 self-start md:self-center">
            <button 
              onClick={() => { setScoreResult(null); setUploadedDocId(''); setSelectedFile(null); setStatusMessage(''); setErrorMessage(''); }}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 text-sm font-medium border border-slate-700 transition-all shadow-md"
            >
              <Activity className="w-4 h-4 text-cyan-400" />
              重置当前测评
            </button>
          </div>
        </div>
      </motion.div>

      {/* 消息与警报提示框 */}
      <AnimatePresence>
        {errorMessage && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="mb-6 p-4 rounded-2xl bg-rose-950/40 border border-rose-500/50 text-rose-300 flex items-center gap-3 shadow-lg">
            <Shield className="w-5 h-5 text-rose-400 flex-shrink-0 animate-bounce" />
            <span className="text-sm font-semibold">{errorMessage}</span>
          </motion.div>
        )}
        {statusMessage && !errorMessage && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="mb-6 p-4 rounded-2xl bg-slate-900/90 border border-cyan-500/30 text-cyan-300 flex items-center justify-between shadow-lg">
            <div className="flex items-center gap-3">
              <Activity className="w-5 h-5 text-cyan-400 animate-spin" />
              <span className="text-sm font-medium">{statusMessage}</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ===================== 2. 控制台：招标文件选择 vs 投标文件上传 ===================== */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
        
        {/* 左表 (5列)：招标文件选择 */}
        <div className="lg:col-span-5 bg-slate-900/90 border border-slate-800/90 rounded-3xl p-6 shadow-2xl backdrop-blur-xl flex flex-col justify-between relative overflow-hidden group">
          <div className="absolute -left-12 -bottom-12 w-48 h-48 bg-emerald-500/5 rounded-full blur-3xl" />
          <div>
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center space-x-2.5">
                <Shield className="w-5 h-5 text-emerald-400" />
                <h2 className="text-base font-extrabold tracking-wide text-white uppercase">1. 选择评分依据招标文件</h2>
              </div>
              <span className="text-[11px] font-mono font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
                评分标准源
              </span>
            </div>

            <div className="mt-4 space-y-3">
              <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider">
                选择已被平台解析成功的历史招标文件 (评分标准) :
              </label>
              {loadingDocs ? (
                <div className="p-3 text-center text-xs text-slate-400 animate-pulse bg-slate-950/50 rounded-xl border border-slate-800">
                  正在获取招标文件列表...
                </div>
              ) : (
                <select
                  value={selectedSourceId}
                  onChange={(e) => setSelectedSourceId(e.target.value)}
                  className="w-full bg-slate-950/80 text-white font-medium text-sm rounded-xl border border-slate-700 focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 outline-none p-3 transition-colors cursor-pointer"
                >
                  {tenderDocs.length === 0 ? (
                    <option value="">（暂无可用招标文件，请先在“招标文件解析”页面上传）</option>
                  ) : (
                    tenderDocs.map((d) => (
                      <option key={d.id} value={d.id} className="bg-slate-900 py-2">
                        📑 [招标文件] {d.filename} (ID: {d.id.slice(0, 8)}...)
                      </option>
                    ))
                  )}
                </select>
              )}
              <p className="text-xs text-slate-400 leading-normal pt-1 flex items-start gap-1.5">
                <span className="text-emerald-400 font-bold">•</span>
                系统将自动提取所选招标文件的评分细则树（Score Tree）作为打分与核验标准。
              </p>
            </div>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-500 font-mono">
            <span>当前招标文件 ID:</span>
            <span className="font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">{selectedSourceId ? selectedSourceId.slice(0, 12) + '...' : '未选择'}</span>
          </div>
        </div>

        {/* 右表 (7列)：待评估投标文件上传与操作 */}
        <div className="lg:col-span-7 bg-slate-900/90 border border-slate-800/90 rounded-3xl p-6 shadow-2xl backdrop-blur-xl flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center space-x-2.5">
                <Upload className="w-5 h-5 text-cyan-400" />
                <h2 className="text-base font-extrabold tracking-wide text-white uppercase">2. 上传并评估投标文件 (Bid Document)</h2>
              </div>
              <span className="text-xs font-mono text-cyan-300 bg-cyan-500/10 px-2.5 py-0.5 rounded-full border border-cyan-500/20">
                支持 PDF / DOCX 格式
              </span>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* 文件上传框 */}
              <div className="relative border-2 border-dashed border-slate-700 hover:border-cyan-500/70 bg-slate-950/60 rounded-2xl p-4 flex flex-col items-center justify-center transition-all group cursor-pointer">
                <input 
                  type="file" 
                  accept=".docx,.pdf"
                  onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                      setSelectedFile(e.target.files[0]);
                      setUploadedDocId(''); // 新选则废弃上一本的既有ID
                    }
                  }}
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                />
                <div className="w-10 h-10 rounded-full bg-cyan-500/10 text-cyan-400 flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                  <FileText className="w-5 h-5" />
                </div>
                <span className="text-sm font-semibold text-slate-200 text-center truncate w-full px-2">
                  {selectedFile ? (
                    <span className="text-cyan-300 font-bold">📝 [投标文件] {selectedFile.name}</span>
                  ) : (
                    "点击选择投标文件 (.pdf/.docx)"
                  )}
                </span>
                <span className="text-[11px] text-slate-400 mt-1 font-mono">
                  {selectedFile ? `文件大小: ${(selectedFile.size / 1024).toFixed(1)} KB` : "上传后将自动进行切片解析与结构提取"}
                </span>
              </div>

              {/* 评分控制面板 */}
              <div className="bg-slate-950/40 border border-slate-800 rounded-2xl p-4 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-300 font-semibold">
                    <span className="flex items-center gap-1.5"><Settings className="w-3.5 h-3.5 text-emerald-400" /> AI 评估校验轮次:</span>
                    <span className="font-mono bg-slate-800 text-emerald-300 px-2 py-0.5 rounded font-bold">{scoringRounds} 轮</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 pt-1">
                    {[1, 3, 5].map((rnd) => (
                      <button
                        key={rnd}
                        type="button"
                        onClick={() => setScoringRounds(rnd)}
                        className={`py-1.5 text-xs font-mono font-bold rounded-xl border transition-all ${scoringRounds === rnd ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/60 shadow-lg shadow-emerald-500/10' : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'}`}
                      >
                        {rnd}轮评估
                      </button>
                    ))}
                  </div>
                </div>

                {/* 行动按钮群 */}
                <div className="flex items-center space-x-3 mt-4">
                  {!uploadedDocId ? (
                    <button
                      onClick={handleUploadBid}
                      disabled={uploading || !selectedFile || !selectedSourceId}
                      className="w-full py-2.5 px-4 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold text-sm shadow-xl disabled:opacity-50 transition-all flex items-center justify-center gap-2"
                    >
                      {uploading ? <Activity className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                      {uploading ? '正在上传解析...' : '上传并解析投标文件'}
                    </button>
                  ) : (
                    <div className="flex items-center gap-2 w-full">
                      <button
                        onClick={() => setShowWorkbench(true)}
                        disabled={scoring}
                        className="py-3 px-3 rounded-xl bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 font-bold text-xs border border-indigo-500/40 transition-all flex items-center justify-center gap-1.5"
                      >
                        <FileText className="w-4 h-4 text-indigo-400" />
                        切片标注
                      </button>
                      <button
                        onClick={handleStartScoring}
                        disabled={scoring}
                        className="flex-1 py-3 px-3 rounded-xl bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 font-black text-sm tracking-wide uppercase shadow-[0_0_25px_rgba(16,185,129,0.4)] disabled:opacity-50 transition-all transform hover:scale-[1.01] active:scale-[0.99] flex items-center justify-center gap-1.5"
                      >
                        {scoring ? <Activity className="w-5 h-5 animate-spin text-slate-950" /> : <CheckCircle2 className="w-5 h-5 text-slate-950" />}
                        {scoring ? '智能评估打分中...' : '开始智能打分'}
                      </button>
                      <button
                        onClick={handleDeleteBid}
                        disabled={scoring || uploading}
                        title="清空该投标文件的解析切片与打分记录"
                        className="py-3 px-3.5 rounded-xl bg-gradient-to-br from-rose-600/90 to-red-700 hover:from-rose-500 hover:to-red-600 text-white font-extrabold text-xs shadow-lg shadow-rose-500/25 disabled:opacity-50 transition-all transform hover:scale-105 active:scale-95 flex items-center gap-1.5 border border-rose-400/30 whitespace-nowrap"
                      >
                        <Trash2 className="w-4 h-4 text-rose-200" />
                        <span>删除记录</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 进度指引底层 */}
          <div className="mt-4 flex items-center justify-between text-xs text-slate-400 px-1 font-mono">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-cyan-400" />
              <span>投标文件状态: {uploadedDocId ? `已解析完成 [${chunkCount} 个切片] ID:${uploadedDocId.slice(0,8)}...` : '未上传投标文件'}</span>
            </div>
            {uploadedDocId && (
              <button
                onClick={() => setShowWorkbench(true)}
                className="flex items-center text-indigo-300 hover:text-indigo-200 font-bold gap-1 underline underline-offset-4"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-400" /> 解析完成，点击进入【切片与章节标注工作台】
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 人工切片与章节标注工作台 Modal 弹出框 */}
      <AnimatePresence>
        {showWorkbench && uploadedDocId && (
          <div className="fixed inset-0 bg-slate-950/85 backdrop-blur-md flex items-center justify-center z-50 p-4 md:p-8">
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.96, opacity: 0 }}
              className="w-full h-full max-w-7xl max-h-[92vh] flex flex-col"
            >
              <ChunkAnnotationWorkbench
                documentId={uploadedDocId}
                filename={selectedFile?.name || '投标文件'}
                sourceDocId={selectedSourceId}
                onClose={() => setShowWorkbench(false)}
                onStartScoring={() => {
                  setShowWorkbench(false);
                  handleStartScoring();
                }}
              />
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* ===================== 3. 打分结果概览与维度对比 (Result Overview & Radar) ===================== */}
      {scoreResult && (
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="space-y-8"
        >
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* 左总评主卡牌 (4 列) */}
            <div className="lg:col-span-4 bg-gradient-to-br from-slate-900 via-slate-950 to-emerald-950/30 border border-slate-800/90 hover:border-emerald-500/40 transition-colors rounded-3xl p-6 shadow-2xl backdrop-blur-2xl flex flex-col justify-between relative overflow-hidden">
              <div className="absolute top-0 right-0 w-48 h-48 bg-emerald-500/10 rounded-full blur-2xl pointer-events-none" />
              
              <div>
                <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                  <span className="text-xs font-mono font-bold text-emerald-400 tracking-widest uppercase">
                    综合得分 / Final Score
                  </span>
                  <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 font-bold font-mono text-[11px] border border-emerald-500/20">
                    评标办法：{scoreResult.evaluation_method || '综合评分法'}
                  </span>
                </div>

                <div className="my-8 flex flex-col items-center justify-center relative">
                  {/* 大比重光晕打光底 */}
                  <div className="w-44 h-44 rounded-full bg-gradient-to-t from-slate-900 via-emerald-950/50 to-emerald-500/20 border-4 border-emerald-500/30 flex flex-col items-center justify-center shadow-[0_0_50px_rgba(0,245,155,0.15)] relative group">
                    <span className="text-5xl font-black tracking-tight text-white font-mono group-hover:scale-110 transition-transform duration-300">
                      {scoreResult.total_score}
                    </span>
                    <span className="text-xs font-semibold text-slate-400 mt-1 font-mono uppercase tracking-widest">
                      满分 {scoreResult.max_possible} 分
                    </span>
                    {/* 微圆光环 */}
                    <div className="absolute -inset-1 rounded-full border border-emerald-400/20 animate-pulse" />
                  </div>

                  <div className="mt-6 w-full text-center space-y-1">
                    <div className="text-sm font-bold text-slate-200">
                      综合得分率: <span className="text-emerald-400 font-mono text-base font-extrabold">{Math.round((scoreResult.score_rate || (scoreResult.total_score / scoreResult.max_possible)) * 100)}%</span>
                    </div>
                    <p className="text-xs text-slate-400 italic">
                      “系统基于 {scoreResult.scoring_rounds || scoringRounds} 轮 AI 独立评估进行交叉验证，确保评分结果客观稳定。”
                    </p>
                  </div>
                </div>
              </div>

              <div className="p-3.5 bg-slate-950/80 rounded-2xl border border-slate-800/80 text-xs text-slate-300 leading-relaxed font-mono">
                <span className="text-cyan-400 font-bold block mb-1">📢 智能评估综合结论：</span>
                {scoreResult.summary || "投标文件整体响应质量良好，在核心商务与技术条款上符合要求，部分细节支撑材料可进一步完善。"}
              </div>
            </div>

            {/* 右多边形雷达视听 (8 列)：Recharts 分类 */}
            <div className="lg:col-span-8 bg-slate-900/90 border border-slate-800/90 rounded-3xl p-6 shadow-2xl backdrop-blur-xl flex flex-col justify-between">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center space-x-2">
                  <span className="w-3 h-3 rounded-full bg-cyan-400 animate-ping" />
                  <h3 className="text-base font-extrabold text-white tracking-wide uppercase">各维度得分对比 (Radar Chart)</h3>
                </div>
                <span className="text-xs text-slate-400 font-mono">
                  包含评分大类：{Object.keys(scoreResult.category_scores || {}).length} 类
                </span>
              </div>

              {/* Recharts 雷达绘区 */}
              <div className="w-full h-[320px] pt-4">
                {radarData.length === 0 ? (
                  <div className="w-full h-full flex items-center justify-center text-sm text-slate-400 italic">
                    暂无大类维度得分数据。
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart cx="50%" cy="50%" outerRadius="78%" data={radarData}>
                      <PolarGrid stroke="#334155" strokeDasharray="3 3" />
                      <PolarAngleAxis dataKey="subject" stroke="#CBD5E1" tick={{ fill: '#E2E8F0', fontSize: 13, fontWeight: 600 }} />
                      <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#475569" />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#0B0F19', borderColor: '#1E293B', borderRadius: '12px', boxShadow: '0 15px 25px rgba(0,0,0,0.6)' }}
                        formatter={(val: any, _name: any, props: any) => [
                          `${props.payload.rawScore} / ${props.payload.maxScore} 分 (${val}%)`,
                          '得分率'
                        ]}
                      />
                      <Radar
                        name="各维度得分率"
                        dataKey="scoreRate"
                        stroke="#00E5FF"
                        strokeWidth={2.5}
                        fill="url(#radarGradient)"
                        fillOpacity={0.65}
                      />
                      <defs>
                        <linearGradient id="radarGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#00F59B" stopOpacity={0.85}/>
                          <stop offset="95%" stopColor="#0EA5E9" stopOpacity={0.15}/>
                        </linearGradient>
                      </defs>
                    </RadarChart>
                  </ResponsiveContainer>
                )}
              </div>

              <div className="pt-3 border-t border-slate-800/80 space-y-3 font-sans">
                <div className="flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
                  {Object.entries(scoreResult.category_scores || {}).map(([cName, info]) => {
                    const catKey = `cat:${cName}`;
                    const isCatActive = activeRescoreKey === catKey;
                    const defaultInst = cName === '价格分' 
                      ? '针对单标书评估，默认其投标总价为有效最低报价，按满分计算。' 
                      : `针对【${cName}】大类，凡提供了响应承诺与相关情况说明的，均按满分计算。`;

                    return (
                      <div key={cName} className={`flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-slate-950/60 border font-mono transition-colors ${isCatActive ? 'border-cyan-500 bg-cyan-950/20' : 'border-slate-800 hover:border-cyan-500/40'}`}>
                        <span className="w-2 h-2 rounded-full bg-cyan-400" />
                        <span className="font-bold text-slate-200">{cName}:</span>
                        <span className="text-emerald-400 font-extrabold">{info.score} <span className="text-slate-500 font-normal">/ {info.max_total}</span></span>

                        <button
                          onClick={() => {
                            if (isCatActive) {
                              setActiveRescoreKey(null);
                            } else {
                              setActiveRescoreKey(catKey);
                              if (!rescoreInstructionMap[catKey]) {
                                setRescoreInstructionMap(prev => ({ ...prev, [catKey]: defaultInst }));
                              }
                            }
                          }}
                          className={`ml-1.5 px-2 py-0.5 rounded-lg border text-[11px] font-sans font-bold flex items-center gap-1 transition-all active:scale-95 ${
                            isCatActive 
                              ? 'bg-cyan-500 text-slate-950 border-cyan-400 font-extrabold' 
                              : 'bg-cyan-500/15 hover:bg-cyan-500/30 text-cyan-300 border-cyan-500/30'
                          }`}
                          title={`微调 [${cName}] 得分`}
                        >
                          <MessageSquare className="w-3 h-3" />
                          <span>{isCatActive ? '收起' : '微调'}</span>
                        </button>
                      </div>
                    );
                  })}
                </div>

                {/* 大类内嵌微调展开区 */}
                <AnimatePresence>
                  {activeRescoreKey && activeRescoreKey.startsWith('cat:') && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className="p-4 rounded-2xl bg-slate-950/90 border border-cyan-500/40 shadow-xl space-y-3"
                    >
                      {(() => {
                        const cName = activeRescoreKey.replace('cat:', '');
                        const catKey = activeRescoreKey;
                        const isCatRescoring = rescoringKey === catKey;

                        return (
                          <>
                            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                              <div className="flex items-center space-x-2">
                                <Sparkles className="w-4 h-4 text-cyan-400 animate-pulse" />
                                <span className="text-xs font-bold text-cyan-300">
                                  大类微调规则 — <span className="text-white">[{cName}]</span>
                                </span>
                              </div>
                              <button
                                onClick={() => setActiveRescoreKey(null)}
                                className="text-slate-400 hover:text-white p-1 rounded-lg transition-colors"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            </div>

                            <div className="space-y-1">
                              <label className="text-[11px] font-bold text-slate-300">
                                请输入大类微调评估规则:
                              </label>
                              <textarea
                                value={rescoreInstructionMap[catKey] || ''}
                                onChange={(e) => setRescoreInstructionMap({ ...rescoreInstructionMap, [catKey]: e.target.value })}
                                rows={3}
                                placeholder="例如：针对单标书评估，默认其投标总价为有效最低报价，价格分按满分计算。"
                                className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-500 rounded-xl p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none transition-colors custom-scrollbar"
                              />
                            </div>

                            {/* 快捷指令模板 */}
                            <div className="flex flex-wrap gap-1.5 text-[11px]">
                              <button
                                onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [catKey]: '针对单标书评估，默认其投标总价为有效最低报价，按满分计算。' })}
                                className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                              >
                                💰 价格默认满分
                              </button>
                              <button
                                onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [catKey]: `针对【${cName}】大类，凡提供了响应承诺与相关情况说明的，均按满分计算。` })}
                                className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                              >
                                📜 承诺书视同满足响应
                              </button>
                              <button
                                onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [catKey]: '按招标文件已满足项进行正常梯次打分，宽松认定相关佐证材料。' })}
                                className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                              >
                                ⚖️ 宽松认定佐证材料
                              </button>
                            </div>

                            <div className="pt-2 border-t border-slate-800 flex items-center justify-end space-x-2">
                              <button
                                onClick={() => setActiveRescoreKey(null)}
                                disabled={isCatRescoring}
                                className="px-3 py-1 text-xs text-slate-400 hover:text-white transition-colors"
                              >
                                收起
                              </button>
                              <button
                                onClick={() => handleApplyRescore(catKey, cName)}
                                disabled={isCatRescoring || !(rescoreInstructionMap[catKey] || '').trim()}
                                className="px-4 py-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 text-slate-950 font-black text-xs hover:brightness-110 disabled:opacity-50 transition-all flex items-center space-x-1.5 shadow-md shadow-cyan-500/20"
                              >
                                {isCatRescoring ? (
                                  <>
                                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                    <span>正在微调重算...</span>
                                  </>
                                ) : (
                                  <>
                                    <Sparkles className="w-3.5 h-3.5" />
                                    <span>应用规则重算大类得分</span>
                                  </>
                                )}
                              </button>
                            </div>
                          </>
                        );
                      })()}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* ===================== 4. 规则校验日志与改进建议 ===================== */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* 规则校验日志 */}
            <div className="bg-gradient-to-br from-amber-950/30 via-slate-900/80 to-slate-950 border border-amber-500/30 rounded-3xl p-6 backdrop-blur-xl shadow-2xl flex flex-col justify-between">
              <div>
                <div className="flex items-center space-x-3 pb-3 border-b border-amber-500/20">
                  <div className="p-2 rounded-xl bg-amber-500/15 text-amber-400 border border-amber-500/30">
                    <Shield className="w-5 h-5 animate-pulse" />
                  </div>
                  <div>
                    <h4 className="text-base font-extrabold text-amber-200 tracking-wide">评分规则校验与防幻觉日志</h4>
                    <span className="text-xs text-amber-400/70 font-mono">Rule Verification & Guardrail Logs</span>
                  </div>
                </div>

                <div className="mt-4 space-y-2 max-h-56 overflow-y-auto pr-2 custom-scrollbar">
                  {(!scoreResult.validation_warnings || scoreResult.validation_warnings.length === 0) ? (
                    <div className="p-4 bg-slate-950/60 rounded-2xl border border-emerald-500/30 text-sm text-emerald-300 font-mono flex items-center gap-3">
                      <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                      <span>校验通过！各评分细目得分均符合规则限制，未发现异常超分或逻辑矛盾。</span>
                    </div>
                  ) : (
                    scoreResult.validation_warnings.map((w, idx) => (
                      <div key={idx} className="flex items-start space-x-3 text-xs bg-slate-950/80 p-3 rounded-xl border border-amber-500/30 text-amber-300 font-mono">
                        <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 font-bold font-sans">#LOG_{idx+1}</span>
                        <span className="leading-relaxed font-sans">{typeof w === 'object' ? JSON.stringify(w) : w}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* 优先扣分项与改进提分建议: Top Improvements */}
            <div className="bg-gradient-to-br from-indigo-950/30 via-slate-900/80 to-emerald-950/20 border border-cyan-500/30 rounded-3xl p-6 backdrop-blur-xl shadow-2xl flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                  <div className="flex items-center space-x-3">
                    <div className="p-2 rounded-xl bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
                      <CheckCircle2 className="w-5 h-5 animate-bounce" />
                    </div>
                    <div>
                      <h4 className="text-base font-extrabold text-cyan-200 tracking-wide">主要扣分项与改进提分建议 (TOP 3)</h4>
                      <span className="text-xs text-cyan-400/70 font-mono">Key Deductions & Score Improvement Suggestions</span>
                    </div>
                  </div>
                </div>

                <div className="mt-4 space-y-3.5 max-h-64 overflow-y-auto pr-2 custom-scrollbar">
                  {(!scoreResult.top_improvements || scoreResult.top_improvements.length === 0) ? (
                    <p className="text-sm text-slate-400 italic p-4 bg-slate-950/60 rounded-2xl border border-slate-800">
                      当前投标文件各评分细项响应完整，暂无明显扣分或改进建议。
                    </p>
                  ) : (
                    scoreResult.top_improvements.slice(0, 3).map((tip, idx) => {
                      const isObj = typeof tip === 'object' && tip !== null;
                      const title = isObj ? (tip as any).title || (tip as any).category || '提分建议' : `提分建议 #${idx + 1}`;
                      const category = isObj ? (tip as any).category : null;
                      const priority = isObj ? (tip as any).priority || 'P1' : null;
                      const gain = isObj ? (tip as any).potential_gain : null;
                      const content = isObj ? (tip as any).action || JSON.stringify(tip) : tip;

                      return (
                        <div key={idx} className="group bg-slate-950/80 hover:bg-slate-900/95 transition-all duration-300 p-4 rounded-2xl border border-slate-800 hover:border-cyan-500/50 shadow-md space-y-2">
                          <div className="flex items-center justify-between gap-2 border-b border-slate-800/80 pb-2">
                            <div className="flex items-center space-x-2.5 min-w-0">
                              <div className="w-6 h-6 rounded-lg bg-cyan-500/20 text-cyan-300 font-mono font-bold text-xs flex items-center justify-center flex-shrink-0 border border-cyan-500/40 group-hover:scale-105 transition-transform">
                                0{idx+1}
                              </div>
                              <span className="text-sm font-extrabold text-cyan-300 truncate">{title}</span>
                              {category && (
                                <span className="text-[11px] font-mono px-2 py-0.5 rounded-md bg-slate-800 text-slate-300 border border-slate-700 flex-shrink-0">
                                  {category}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center space-x-2 flex-shrink-0">
                              {priority && (
                                <span className={`text-xs font-mono font-extrabold px-2 py-0.5 rounded ${
                                  priority === 'P0' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40 animate-pulse' :
                                  priority === 'P1' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40' :
                                  'bg-sky-500/20 text-sky-400 border border-sky-500/40'
                                }`}>
                                  {priority}
                                </span>
                              )}
                              {gain !== null && gain !== undefined && (
                                <span className="text-xs font-mono font-black px-2.5 py-0.5 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 shadow-sm">
                                  +{gain}分
                                </span>
                              )}
                            </div>
                          </div>
                          <p className="text-sm text-slate-200 leading-relaxed font-normal pt-0.5">
                            {content}
                          </p>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ===================== 5. 评估细则明细账簿 ===================== */}
          <div className="bg-slate-900/90 border border-slate-800/90 rounded-3xl p-6 shadow-2xl backdrop-blur-xl">
            <div className="flex flex-col md:flex-row md:items-center justify-between pb-4 border-b border-slate-800 gap-2">
              <div className="flex items-center space-x-3">
                <Shield className="w-6 h-6 text-cyan-400" />
                <h3 className="text-lg font-extrabold text-white tracking-tight">
                  评分细则逐条评审与依据明细 <span className="text-xs text-slate-400 font-normal ml-2 font-mono">(含标书原文引用与评分依据)</span>
                </h3>
              </div>
              <div className="text-xs text-slate-400 font-mono bg-slate-950 px-3 py-1 rounded-xl border border-slate-800 self-start md:self-center">
                评分条目总数：{scoreResult.items ? scoreResult.items.length : 0} 项
              </div>
            </div>

            <div className="mt-6 space-y-3.5">
              {(!scoreResult.items || scoreResult.items.length === 0) ? (
                <div className="p-12 text-center text-slate-400 font-mono italic">
                  暂无具体打分细项数据。
                </div>
              ) : (
                scoreResult.items.map((item: ScoreItem) => {
                  const isExpanded = expandedItemId === item.id;
                  const ratio = (item.ai_score / (item.max_score || 1)) * 100;
                  const isPerfect = ratio >= 99;

                  const itemKey = `item:${item.id || item.item_code || item.title}`;
                  const isItemActive = activeRescoreKey === itemKey;
                  const isItemRescoring = rescoringKey === itemKey;
                  const defaultInst = item.category === '价格分' 
                    ? '针对单标书评估，默认其投标总价为有效最低报价，按满分计算。' 
                    : `针对[${item.title}]，凡提供了响应承诺与说明的，按满分计算。`;

                  const handleToggleItemRescore = (e?: React.MouseEvent) => {
                    if (e) e.stopPropagation();
                    if (isItemActive) {
                      setActiveRescoreKey(null);
                    } else {
                      setActiveRescoreKey(itemKey);
                      if (!rescoreInstructionMap[itemKey]) {
                        setRescoreInstructionMap(prev => ({ ...prev, [itemKey]: defaultInst }));
                      }
                    }
                  };

                  return (
                    <div
                      key={item.id}
                      className={`transition-all duration-300 rounded-2xl border ${
                        isItemActive 
                          ? 'bg-slate-900/95 border-cyan-500 shadow-xl shadow-cyan-500/10' 
                          : isExpanded 
                          ? 'bg-slate-900/95 border-cyan-500/50 shadow-xl shadow-cyan-500/5' 
                          : 'bg-slate-950/60 border-slate-800 hover:border-slate-700/90'
                      }`}
                    >
                      {/* 表行头部触感栏 */}
                      <div
                        onClick={() => setExpandedItemId(isExpanded ? null : item.id)}
                        className="p-4.5 flex items-center justify-between cursor-pointer select-none gap-4"
                      >
                        <div className="flex items-center space-x-4 min-w-0">
                          <span className="px-3 py-1.5 rounded-xl bg-slate-800 text-cyan-300 font-mono text-xs font-black border border-slate-700 flex-shrink-0">
                            {item.item_code || '细则条目'}
                          </span>
                          <div className="flex flex-col min-w-0">
                            <span className="text-sm md:text-base font-bold text-slate-100 hover:text-cyan-300 transition-colors truncate">
                              {item.title}
                            </span>
                            <span className="text-xs text-slate-400 font-medium">
                              分类：{item.category} {item.sub_category ? ` ❯ ${item.sub_category}` : ''}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center space-x-6 flex-shrink-0">
                          {/* 置信度徽标 */}
                          <div className="hidden md:flex flex-col items-end">
                            <div className="flex items-center space-x-2">
                              <span className={`w-2 h-2 rounded-full ${(item.confidence || 1) >= 0.85 ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} />
                              <span className="text-xs font-mono font-bold text-slate-300">
                                AI 置信度: {Math.round((item.confidence || 1) * 100)}%
                              </span>
                            </div>
                            <span className="text-[10px] text-slate-400 font-mono mt-0.5">
                              多轮打分记录: [{item.all_round_scores ? item.all_round_scores.join(', ') : `${item.ai_score}`}]
                            </span>
                          </div>

                          {/* 成绩条柱 */}
                          <div className="w-28 text-right flex flex-col items-end">
                            <span className={`text-lg font-black tracking-tight font-mono ${isPerfect ? 'text-emerald-400' : 'text-white'}`}>
                              {item.ai_score} <span className="text-xs font-normal text-slate-500">/ {item.max_score}</span>
                            </span>
                            <div className="w-20 bg-slate-800 rounded-full h-1.5 mt-1 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${isPerfect ? 'bg-emerald-500' : ratio > 60 ? 'bg-cyan-500' : 'bg-rose-500'}`}
                                style={{ width: `${Math.min(100, Math.max(5, ratio))}%` }}
                              />
                            </div>
                          </div>

                          {/* 交互微调按钮 */}
                          <button
                            onClick={handleToggleItemRescore}
                            className={`px-2.5 py-1 rounded-xl border text-xs font-sans font-bold flex items-center gap-1.5 transition-all shadow-sm active:scale-95 flex-shrink-0 ${
                              isItemActive 
                                ? 'bg-cyan-500 text-slate-950 border-cyan-400 font-extrabold' 
                                : 'bg-cyan-500/15 hover:bg-cyan-500/30 text-cyan-300 border-cyan-500/40'
                            }`}
                            title={`精细微调 [${item.title}] 指令重算`}
                          >
                            <MessageSquare className="w-3.5 h-3.5" />
                            <span>{isItemActive ? '收起微调' : '微调'}</span>
                          </button>

                          <button className="text-slate-400 hover:text-white p-1.5 rounded-lg transition-colors text-sm font-black font-mono">
                            {isExpanded ? <span className="text-cyan-400">▲</span> : <span>▼</span>}
                          </button>
                        </div>
                      </div>

                      {/* 卡片内嵌微调控制台 (不遮挡页面) */}
                      <AnimatePresence>
                        {isItemActive && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                            className="px-5 py-4 border-t border-cyan-500/30 bg-slate-900/90 rounded-b-2xl space-y-3 font-sans"
                          >
                            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                              <div className="flex items-center space-x-2">
                                <Sparkles className="w-4 h-4 text-cyan-400 animate-pulse" />
                                <span className="text-xs font-bold text-cyan-300">
                                  自定义微调评分规则 — <span className="text-white">[{item.title}]</span>
                                </span>
                              </div>
                              <button
                                onClick={() => setActiveRescoreKey(null)}
                                className="text-slate-400 hover:text-white p-1 rounded-lg transition-colors"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            </div>

                            <div className="space-y-1">
                              <label className="text-[11px] font-bold text-slate-300">
                                请输入微调评分规则:
                              </label>
                              <textarea
                                value={rescoreInstructionMap[itemKey] || ''}
                                onChange={(e) => setRescoreInstructionMap({ ...rescoreInstructionMap, [itemKey]: e.target.value })}
                                rows={3}
                                placeholder="例如：针对单标书评估，默认其投标总价为有效最低报价，按满分计算。"
                                className="w-full bg-slate-950 border border-slate-700 focus:border-cyan-500 rounded-xl p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none transition-colors custom-scrollbar"
                              />
                            </div>

                            {/* 快捷模板推荐 */}
                            <div className="space-y-1">
                              <span className="text-[10px] font-bold text-slate-400 font-mono">💡 常用快捷指令模板 (点击一键填入):</span>
                              <div className="flex flex-wrap gap-1.5 text-[11px]">
                                <button
                                  onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [itemKey]: '针对单标书评估，默认其投标总价为有效最低报价，按满分计算。' })}
                                  className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                                >
                                  💰 价格默认满分
                                </button>
                                <button
                                  onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [itemKey]: `针对[${item.title}]，凡提供了响应承诺与说明的，按满分计算。` })}
                                  className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                                >
                                  📜 承诺书视同满足响应
                                </button>
                                <button
                                  onClick={() => setRescoreInstructionMap({ ...rescoreInstructionMap, [itemKey]: '按招标文件已满足项进行正常梯次打分，宽松认定相关佐证材料。' })}
                                  className="px-2 py-0.5 rounded-lg bg-slate-800 hover:bg-cyan-950/60 hover:text-cyan-300 border border-slate-700 text-slate-300 transition-colors"
                                >
                                  ⚖️ 宽松认定佐证材料
                                </button>
                              </div>
                            </div>

                            <div className="pt-2 border-t border-slate-800 flex items-center justify-end space-x-2">
                              <button
                                onClick={() => setActiveRescoreKey(null)}
                                disabled={isItemRescoring}
                                className="px-3 py-1 text-xs text-slate-400 hover:text-white transition-colors"
                              >
                                收起
                              </button>
                              <button
                                onClick={() => handleApplyRescore(itemKey, item.category, item.item_code || item.title, item.title)}
                                disabled={isItemRescoring || !(rescoreInstructionMap[itemKey] || '').trim()}
                                className="px-4 py-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 text-slate-950 font-black text-xs hover:brightness-110 disabled:opacity-50 transition-all flex items-center space-x-1.5 shadow-md shadow-cyan-500/20"
                              >
                                {isItemRescoring ? (
                                  <>
                                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                    <span>正在微调重算...</span>
                                  </>
                                ) : (
                                  <>
                                    <Sparkles className="w-3.5 h-3.5" />
                                    <span>应用规则并重新打分</span>
                                  </>
                                )}
                              </button>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>

                      {/* 打开手风琴内部: 原文依据与原因 */}
                      {isExpanded && (
                        <div className="px-5 pb-6 pt-3 border-t border-slate-800/80 bg-slate-950/90 rounded-b-2xl space-y-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                            
                            {/* 证据来源语境 */}
                            <div className="md:col-span-2 bg-slate-900/90 border border-slate-800 p-4 rounded-2xl space-y-2 shadow-inner">
                              <div className="flex items-center space-x-2 text-xs font-bold text-emerald-400 uppercase tracking-wider">
                                <FileText className="w-4 h-4" />
                                <span>投标文件原文依据 (Ground Truth)</span>
                              </div>
                              <p className="text-xs font-mono text-slate-300 leading-relaxed pl-4 border-l-2 border-emerald-500/60 bg-slate-950/50 p-3 rounded-r-xl">
                                {item.scoring_basis || '标书中已提供对应的响应说明与佐证材料。'}
                              </p>
                            </div>

                            {/* 评分判定理由与扣分分析 */}
                            <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-2xl space-y-3 flex flex-col justify-between shadow-inner">
                              <div>
                                <div className={`flex items-center space-x-2 text-xs font-bold uppercase tracking-wider ${isPerfect ? 'text-emerald-400' : 'text-rose-400'}`}>
                                  {isPerfect ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <Shield className="w-4 h-4 text-rose-400" />}
                                  <span>{isPerfect ? '满分得分理由' : '扣分原因分析'}</span>
                                </div>
                                <p className={`text-xs text-slate-300 mt-2 pl-3 border-l-2 p-2.5 rounded-r-xl leading-relaxed ${isPerfect ? 'border-emerald-500/60 bg-emerald-950/20 font-sans font-medium' : 'border-rose-500/50 bg-rose-950/10'}`}>
                                  {item.deduction_reason ? item.deduction_reason : (isPerfect ? `该项响应内容完整，完全符合招标文件评分标准，给予满分 ${item.max_score} 分。` : '未提供相关响应文件，按规则扣分。')}
                                </p>
                              </div>

                              {item.suggestion && (
                                <div className="pt-3 border-t border-slate-800/80">
                                  <span className="text-[11px] text-cyan-300 font-extrabold flex items-center gap-1 mb-1.5">
                                    💡 提分建议 / Suggestion
                                  </span>
                                  <p className="text-xs text-slate-300 font-normal leading-relaxed bg-slate-950/80 p-2.5 rounded-xl border border-slate-800">
                                    {item.suggestion}
                                  </p>
                                </div>
                              )}

                              <div className="pt-2 border-t border-slate-800/80">
                                <button
                                  onClick={handleToggleItemRescore}
                                  className="w-full py-2.5 rounded-xl bg-gradient-to-r from-cyan-500/20 to-emerald-500/20 hover:from-cyan-500/30 hover:to-emerald-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-extrabold flex items-center justify-center gap-2 transition-all shadow-md active:scale-98"
                                >
                                  <Sparkles className="w-4 h-4 text-cyan-400 animate-pulse" />
                                  <span>{isItemActive ? '收起微调面板' : '微调本项得分'}</span>
                                </button>
                              </div>
                            </div>

                          </div>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
};
