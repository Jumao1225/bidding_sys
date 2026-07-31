import React, { useState, useEffect, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  FileText, GitMerge, Save, Sparkles, CheckCircle2, 
  Tag, RefreshCw, X, Edit3, CheckSquare, 
  Square, AlertCircle, MousePointerClick, PlusCircle, Eye, Crop, Trash2, BookOpen
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DocChunkDetail, ChunkUpdateItem } from '../api/bidScorerApi';
import { fetchDocumentChunks, updateDocumentChunks } from '../api/bidScorerApi';
import { SmartDocViewer } from './SmartDocViewer';
import { API_BASE_URL } from '../utils/api';

interface ChunkAnnotationWorkbenchProps {
  documentId: string;
  filename: string;
  sourceDocId?: string;
  onClose?: () => void;
  onStartScoring: (documentId: string) => void;
}


export const ChunkAnnotationWorkbench: React.FC<ChunkAnnotationWorkbenchProps> = ({
  documentId,
  filename,
  onClose,
  onStartScoring,
}: any) => {
  const [chunks, setChunks] = useState<DocChunkDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // 页码范围批量标注弹窗 State
  const [showPageRangeModal, setShowPageRangeModal] = useState(false);
  const [startPage, setStartPage] = useState<number | ''>('');
  const [endPage, setEndPage] = useState<number | ''>('');
  const [rangeSectionTitle, setRangeSectionTitle] = useState('');

  // 视图模式：'original' (真实原文件 PDF/Word) 还是 'markdown' (提取 Markdown)
  const [viewMode, setViewMode] = useState<'original' | 'markdown'>('original');


  // 标注工具模式：'text' (划选文本) 还是 'box' (矩形框选图片/区域)
  const [annotationTool, setAnnotationTool] = useState<'text' | 'box'>('text');
  const [isBoxDragging, setIsBoxDragging] = useState(false);
  const [boxStart, setBoxStart] = useState<{ x: number; y: number } | null>(null);
  const [boxEnd, setBoxEnd] = useState<{ x: number; y: number } | null>(null);
  const [croppedImageData, setCroppedImageData] = useState<string | null>(null);
  const docContainerRef = useRef<HTMLDivElement>(null);



  // 选中的切片 ID 列表 (用于批量修改)
  const [selectedChunkIds, setSelectedChunkIds] = useState<Set<string>>(new Set());
  // 当前聚焦高亮的切片 ID
  const [activeChunkId, setActiveChunkId] = useState<string | null>(null);

  // 鼠标在原文档区域划选文本的状态
  const [selectedTextFromDoc, setSelectedTextFromDoc] = useState<string>('');
  const [selectionPopoverPos, setSelectionPopoverPos] = useState<{ x: number; y: number } | null>(null);
  const [targetSectionForSelection, setTargetSectionForSelection] = useState<string>('');

  // 批量修改章节名称弹出框
  const [showBatchModal, setShowBatchModal] = useState(false);
  const [batchSectionTitle, setBatchSectionTitle] = useState('');

  // 编辑特定切片文本模态框
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');

  // 目录列表（从已有切片的 section_title 自动去重提取白名单）
  const uniqueSections = useMemo(() => {
    const set = new Set<string>();
    chunks.forEach(c => {
      if (c.section_title && c.section_title !== '无章节/正文') {
        set.add(c.section_title);
      }
    });
    return Array.from(set);
  }, [chunks]);

  // 监听左侧原文档区域的鼠标松开划选事件 (MouseUp Text Selection)
  // 监听左侧原文档区域的鼠标松开划选事件 (MouseUp Text Selection & Auto Region Capture)
  const handleDocTextMouseUp = () => {
    if (annotationTool !== 'text') return;
    const selection = window.getSelection();
    const text = selection ? selection.toString().trim() : '';
    if (!selection || selection.rangeCount === 0) return;

    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();

    if (text.length >= 2 || (rect.width > 30 && rect.height > 20)) {
      setSelectedTextFromDoc(text);
      setCroppedImageData(null);

      // 自动切取划选选区的 PDF/Word 物理图象 (支持图文并茂自动抓取)
      if (docContainerRef.current && rect.width > 20 && rect.height > 20) {
        const containerEl = docContainerRef.current;
        const containerRect = containerEl.getBoundingClientRect();
        const targetCanvas = containerEl.querySelector('canvas') as HTMLCanvasElement | null;

        if (targetCanvas) {
          try {
            const canvasRect = targetCanvas.getBoundingClientRect();
            const scaleX = targetCanvas.width / canvasRect.width;
            const scaleY = targetCanvas.height / canvasRect.height;

            const x1 = rect.left - containerRect.left;
            const y1 = rect.top - containerRect.top;

            const cropX = Math.max(0, (x1 - (canvasRect.left - containerRect.left)) * scaleX);
            const cropY = Math.max(0, (y1 - (canvasRect.top - containerRect.top)) * scaleY);
            const cropW = Math.min(targetCanvas.width - cropX, rect.width * scaleX);
            const cropH = Math.min(targetCanvas.height - cropY, rect.height * scaleY);

            if (cropW > 10 && cropH > 10) {
              const cropCanvas = document.createElement('canvas');
              cropCanvas.width = Math.max(1, cropW);
              cropCanvas.height = Math.max(1, cropH);
              const ctx = cropCanvas.getContext('2d');
              if (ctx) {
                ctx.drawImage(targetCanvas, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);
                const imgData = cropCanvas.toDataURL('image/png');
                setCroppedImageData(imgData);
              }
            }
          } catch (err) {
            console.warn('Auto crop image warning:', err);
          }
        }
      }

      setSelectionPopoverPos({
        x: rect.left + rect.width / 2,
        y: Math.max(20, rect.top - 60)
      });
    }
  };

  // 矩形框选图片/区域鼠标事件
  const handleBoxMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (annotationTool !== 'box' || !docContainerRef.current) return;
    const rect = docContainerRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setBoxStart({ x, y });
    setBoxEnd({ x, y });
    setIsBoxDragging(true);
    setSelectionPopoverPos(null);
    setCroppedImageData(null);
  };

  const handleBoxMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isBoxDragging || !boxStart || !docContainerRef.current) return;
    const rect = docContainerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const y = Math.max(0, Math.min(e.clientY - rect.top, rect.height));
    setBoxEnd({ x, y });
  };

  const handleBoxMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isBoxDragging || !boxStart || !boxEnd || !docContainerRef.current) return;
    setIsBoxDragging(false);

    const x1 = Math.min(boxStart.x, boxEnd.x);
    const y1 = Math.min(boxStart.y, boxEnd.y);
    const width = Math.abs(boxEnd.x - boxStart.x);
    const height = Math.abs(boxEnd.y - boxStart.y);

    if (width > 20 && height > 20) {
      const containerEl = docContainerRef.current;
      const targetCanvas = containerEl.querySelector('canvas') as HTMLCanvasElement | null;
      
      let base64Image = '';
      if (targetCanvas) {
        try {
          const containerRect = containerEl.getBoundingClientRect();
          const canvasRect = targetCanvas.getBoundingClientRect();
          
          const scaleX = targetCanvas.width / canvasRect.width;
          const scaleY = targetCanvas.height / canvasRect.height;

          const cropX = Math.max(0, (x1 - (canvasRect.left - containerRect.left)) * scaleX);
          const cropY = Math.max(0, (y1 - (canvasRect.top - containerRect.top)) * scaleY);
          const cropW = Math.min(targetCanvas.width - cropX, width * scaleX);
          const cropH = Math.min(targetCanvas.height - cropY, height * scaleY);

          const cropCanvas = document.createElement('canvas');
          cropCanvas.width = Math.max(1, cropW);
          cropCanvas.height = Math.max(1, cropH);
          const ctx = cropCanvas.getContext('2d');
          if (ctx) {
            ctx.drawImage(targetCanvas, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH);
            base64Image = cropCanvas.toDataURL('image/png');
          }
        } catch (err) {
          console.warn('Canvas crop warning:', err);
        }
      }

      if (!base64Image) {
        base64Image = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="%234f46e5"/><text x="50%" y="50%" fill="white" font-size="12" text-anchor="middle" dominant-baseline="middle">框选图片/盖章 (${Math.round(width)}x${Math.round(height)})</text></svg>`;
      }

      setCroppedImageData(base64Image);
      setSelectedTextFromDoc('');
      setSelectionPopoverPos({
        x: e.clientX,
        y: Math.max(20, e.clientY - 60)
      });
    } else {
      setBoxStart(null);
      setBoxEnd(null);
    }
  };

  // 确认原文档划选的内容，直接新建/追加切片 (智能图文融合)
  const handleConfirmSelectionChunk = () => {
    if (!selectedTextFromDoc && !croppedImageData) return;
    if (!targetSectionForSelection.trim()) return;

    let finalContent = selectedTextFromDoc;
    if (croppedImageData) {
      finalContent = selectedTextFromDoc 
        ? `${selectedTextFromDoc}\n\n![划选选区图像及图表](${croppedImageData})`
        : `![框选图片/印章/图表](${croppedImageData})`;
    }

    const newChunk: DocChunkDetail = {
      id: `manual_${Date.now()}`,
      document_id: documentId,
      chunk_index: chunks.length,
      section_title: targetSectionForSelection.trim(),
      parent_chapter: targetSectionForSelection.trim(),
      content: finalContent,
      page_num: 1,
      has_table: !!croppedImageData,
    };

    setChunks(prev => [...prev, newChunk]);
    setActiveChunkId(newChunk.id);
    setSelectedTextFromDoc('');
    setCroppedImageData(null);
    setSelectionPopoverPos(null);
    setTargetSectionForSelection('');
    setHasUnsavedChanges(true);
  };


  // 按章节过滤
  const [selectedCategoryFilter, setSelectedCategoryFilter] = useState<string | null>(null);

  // 加载数据与原文档切片备份
  const [allOriginalChunks, setAllOriginalChunks] = useState<DocChunkDetail[]>([]);

  useEffect(() => {
    loadChunks();
  }, [documentId]);

  const loadChunks = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const data = await fetchDocumentChunks(documentId);
      setChunks(data);
      setAllOriginalChunks(data); // 永远备份一份全量原文档真实切片与物理页文本
      if (data.length > 0) {
        setActiveChunkId(data[0].id);
      }
    } catch (err: any) {
      setErrorMsg(err.message || '加载切片失败');
    } finally {
      setLoading(false);
    }
  };

  // 记忆化原文档 Viewer 的参数对象，杜绝切片状态修改时导致 PDF 视图重新加载与滚动位置丢失
  const viewerDocuments = useMemo(() => [
    {
      uri: `${API_BASE_URL}/api/v1/analysis/download/${documentId}`,
      fileName: filename,
      fileType: filename.split('.').pop()?.toLowerCase() || 'pdf',
    }
  ], [documentId, filename]);

  // 章节过滤后的切片列表
  const filteredChunks = useMemo(() => {
    if (!selectedCategoryFilter) return chunks;
    return chunks.filter(c => c.section_title === selectedCategoryFilter);
  }, [chunks, selectedCategoryFilter]);

  // 修改单个切片的所属章节
  const handleUpdateChunkTitle = (chunkId: string, newTitle: string) => {
    setChunks(prev =>
      prev.map(c => (c.id === chunkId ? { ...c, section_title: newTitle } : c))
    );
    setHasUnsavedChanges(true);
  };

  // 多选切片全选/反选
  const toggleSelectAll = () => {
    if (selectedChunkIds.size === filteredChunks.length) {
      setSelectedChunkIds(new Set());
    } else {
      setSelectedChunkIds(new Set(filteredChunks.map(c => c.id)));
    }
  };

  const toggleSelectChunk = (id: string) => {
    setSelectedChunkIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // 应用批量章节名称更新
  const handleApplyBatchSectionTitle = () => {
    if (!batchSectionTitle.trim() || selectedChunkIds.size === 0) return;
    setChunks(prev =>
      prev.map(c =>
        selectedChunkIds.has(c.id) ? { ...c, section_title: batchSectionTitle.trim() } : c
      )
    );
    setSelectedChunkIds(new Set());
    setShowBatchModal(false);
    setBatchSectionTitle('');
    setHasUnsavedChanges(true);
  };

  // 与下一项合并切片
  const handleMergeWithNext = (index: number) => {
    if (index >= chunks.length - 1) return;
    const current = chunks[index];
    const next = chunks[index + 1];

    const mergedChunk: DocChunkDetail = {
      ...current,
      content: current.content + '\n\n' + next.content,
    };

    const newChunks = [...chunks];
    newChunks.splice(index, 2, mergedChunk);
    // 重新修正 chunk_index
    const reindexed = newChunks.map((c, i) => ({ ...c, chunk_index: i }));
    setChunks(reindexed);
    setHasUnsavedChanges(true);
  };

  // 拆分当前切片
  const handleSplitChunk = (chunkId: string) => {
    const target = chunks.find(c => c.id === chunkId);
    if (!target) return;
    setEditingChunkId(chunkId);
    setEditText(target.content);
  };

  // 删除单个指定切片 (支持人工智能与人工标注切片)
  const handleDeleteChunk = (chunkId: string) => {
    if (window.confirm('确定要删除此切片吗？')) {
      setChunks(prev => prev.filter(c => c.id !== chunkId));
      setSelectedChunkIds(prev => {
        const next = new Set(prev);
        next.delete(chunkId);
        return next;
      });
      setHasUnsavedChanges(true);
      setSuccessMsg('✅ 已成功删除该切片');
    }
  };

  // 批量删除选中的切片
  const handleBatchDeleteChunks = () => {
    if (selectedChunkIds.size === 0) return;
    if (window.confirm(`确定要删除选中的 ${selectedChunkIds.size} 块切片吗？`)) {
      setChunks(prev => prev.filter(c => !selectedChunkIds.has(c.id)));
      setSelectedChunkIds(new Set());
      setHasUnsavedChanges(true);
      setSuccessMsg(`✅ 已成功批量删除 ${selectedChunkIds.size} 块切片`);
    }
  };

  // 仅清空人工标注的切片
  const handleClearManualChunksOnly = () => {
    const manualChunks = chunks.filter(c => c.id.startsWith('manual_'));
    if (manualChunks.length === 0) {
      setSuccessMsg('当前暂无人工标注的切片。');
      return;
    }
    if (window.confirm(`确定要清空您手动标注的 ${manualChunks.length} 块人工切片吗？`)) {
      setChunks(prev => prev.filter(c => !c.id.startsWith('manual_')));
      setSelectedChunkIds(new Set());
      setHasUnsavedChanges(true);
      setSuccessMsg(`✅ 已成功清空 ${manualChunks.length} 块人工标注切片！`);
    }
  };

  // 保存文本或拆分后的切片
  const handleSaveTextEdit = () => {
    if (!editingChunkId) return;
    setChunks(prev =>
      prev.map(c => (c.id === editingChunkId ? { ...c, content: editText } : c))
    );
    setEditingChunkId(null);
    setEditText('');
    setHasUnsavedChanges(true);
  };

  // 按页码范围批量标注 (Page Range Batch Annotation)
  const handleApplyPageRangeAnnotation = () => {
    if (!startPage || !endPage || !rangeSectionTitle.trim()) return;
    const sPage = Number(startPage);
    const ePage = Number(endPage);
    if (sPage > ePage) {
      setErrorMsg('起始页码不能大于结束页码');
      return;
    }

    const matchingChunkIds = new Set<string>();
    chunks.forEach(c => {
      const pNum = c.page_num || 1;
      if (pNum >= sPage && pNum <= ePage) {
        matchingChunkIds.add(c.id);
      }
    });

    if (matchingChunkIds.size > 0) {
      setChunks(prev =>
        prev.map(c =>
          matchingChunkIds.has(c.id) ? { ...c, section_title: rangeSectionTitle.trim() } : c
        )
      );
      setSuccessMsg(`✅ 成功将第 ${sPage} 页 ~ 第 ${ePage} 页的 ${matchingChunkIds.size} 块切片归为【${rangeSectionTitle.trim()}】`);
    } else {
      // 从后端全量原文档备份数据中抓取 [sPage, ePage] 范围内的真实正文文本！
      const origInPageRange = allOriginalChunks.filter(c => (c.page_num || 1) >= sPage && (c.page_num || 1) <= ePage);

      let realExtractedText = origInPageRange.map(c => c.content).filter(Boolean).join('\n\n');
      if (!realExtractedText.trim()) {
        realExtractedText = `原文档第 ${sPage} 页至第 ${ePage} 页正文区间 (归属: ${rangeSectionTitle.trim()})`;
      }

      const newChunk: DocChunkDetail = {
        id: `manual_page_${Date.now()}`,
        document_id: documentId,
        chunk_index: chunks.length,
        section_title: rangeSectionTitle.trim(),
        parent_chapter: rangeSectionTitle.trim(),
        content: realExtractedText,
        page_num: sPage,
        has_table: false,
      };

      setChunks(prev => [...prev, newChunk]);
      setSuccessMsg(`✅ 已成功提取第 ${sPage} 页 ~ 第 ${ePage} 页真实原文档正文，并标注归属为【${rangeSectionTitle.trim()}】`);
    }

    setHasUnsavedChanges(true);
    setShowPageRangeModal(false);
    setStartPage('');
    setEndPage('');
    setRangeSectionTitle('');
  };

  // 清空 AI 自动切片（智能保留用户人工划选/框选/按页标注的切片）
  const handleClearAiChunksOnly = () => {
    // 识别人工创建的切片 (ID 以 manual_ 开头)
    const manualChunks = chunks.filter(c => c.id.startsWith('manual_'));
    const aiChunksCount = chunks.length - manualChunks.length;

    if (aiChunksCount === 0) {
      setSuccessMsg('当前所有切片均为您的纯人工标注，无 AI 自动切片。');
      return;
    }

    if (window.confirm(`确定要清空 ${aiChunksCount} 块 AI 自动切片吗？\n（您亲自标注的 ${manualChunks.length} 块人工切片将被完好保留）`)) {
      setChunks(manualChunks);
      setSelectedChunkIds(new Set());
      setActiveChunkId(manualChunks.length > 0 ? manualChunks[0].id : null);
      setHasUnsavedChanges(true);
      setSuccessMsg(`✅ 已清除 ${aiChunksCount} 块 AI 切片，完好保留您的 ${manualChunks.length} 块人工切片！`);
    }
  };

  // 批量保存并落库
  const handleSaveAnnotations = async () => {
    setSaving(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const updatePayload: ChunkUpdateItem[] = chunks.map((c, i) => ({
        id: c.id,
        chunk_index: i,
        section_title: c.section_title || '无章节/正文',
        parent_chapter: c.parent_chapter || c.section_title || '无章节/正文',
        content: c.content,
        page_num: c.page_num || 1,
      }));

      const res = await updateDocumentChunks(documentId, updatePayload);
      setHasUnsavedChanges(false);
      setSuccessMsg(`✅ 标注成功保存！系统已为 ${res.chunk_count} 块切片重算向量并同步落库`);
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setErrorMsg(err.message || '保存标注失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-100 rounded-xl overflow-hidden shadow-2xl border border-slate-800">
      {/* 1. 顶部 Header 操作工具栏 */}
      <div className="bg-slate-950/80 backdrop-blur border-b border-slate-800 px-6 py-4 flex items-center justify-between z-10">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-indigo-500/10 rounded-lg text-indigo-400 border border-indigo-500/20">
            <FileText className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              {filename}
              {hasUnsavedChanges ? (
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  未保存修改
                </span>
              ) : (
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  已与向量库对齐
                </span>
              )}
            </h2>
            <p className="text-xs text-slate-400 flex items-center gap-3">
              <span>共 <strong className="text-indigo-300">{chunks.length}</strong> 块切片</span>
              <span>•</span>
              <span>识别到 <strong className="text-indigo-300">{uniqueSections.length}</strong> 个主要章节</span>
            </p>
          </div>
        </div>

        {/* 顶部操作按钮 */}
        <div className="flex items-center space-x-3">
          {/* 按页码范围批量标注 */}
          <button
            onClick={() => setShowPageRangeModal(true)}
            className="px-3 py-1.5 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
            title="选择起始页码与结束页码，一次性将范围内所有切片归为指定章节"
          >
            <BookOpen className="w-3.5 h-3.5" />
            按页码范围标注
          </button>

          {/* 仅清空 AI 自动切片 */}
          <button
            onClick={handleClearAiChunksOnly}
            className="px-3 py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/20 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
            title="仅清空系统 AI 自动拆分的切片，完好保留您手动划选/框选/按页标注的人工切片"
          >
            <Trash2 className="w-3.5 h-3.5" />
            清空AI切片 (保留人工)
          </button>

          {/* 仅清空人工标注切片 */}
          <button
            onClick={handleClearManualChunksOnly}
            className="px-3 py-1.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/20 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
            title="仅清空您手动划选/框选/按页标注的人工切片"
          >
            <Trash2 className="w-3.5 h-3.5" />
            清空人工切片
          </button>

          {selectedChunkIds.size > 0 && (
            <>
              <button
                onClick={() => setShowBatchModal(true)}
                className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition flex items-center gap-1.5 shadow-lg shadow-indigo-600/20"
              >
                <Tag className="w-3.5 h-3.5" />
                批量设置章节 ({selectedChunkIds.size})
              </button>
              <button
                onClick={handleBatchDeleteChunks}
                className="px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-medium transition flex items-center gap-1.5 shadow-lg shadow-rose-600/20"
              >
                <Trash2 className="w-3.5 h-3.5" />
                批量删除选中 ({selectedChunkIds.size})
              </button>
            </>
          )}

          <button
            onClick={handleSaveAnnotations}
            disabled={saving}
            className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition border ${
              hasUnsavedChanges
                ? 'bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-500 shadow-lg shadow-indigo-600/30'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700'
            }`}
          >
            {saving ? (
              <RefreshCw className="w-4 h-4 animate-spin text-indigo-300" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saving ? '向量重算中...' : '保存切片标注'}
          </button>

          <button
            onClick={() => onStartScoring(documentId)}
            className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-emerald-600/25"
          >
            <Sparkles className="w-4 h-4 text-emerald-200" />
            开启 AI 智能打分
          </button>

          {onClose && (
            <button onClick={onClose} className="p-2 text-slate-400 hover:text-slate-200 transition">
              <X className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      {/* 提示 Alert 区域 */}
      <AnimatePresence>
        {errorMsg && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="bg-rose-500/10 border-b border-rose-500/20 px-6 py-2.5 text-rose-300 text-xs flex items-center justify-between">
            <span className="flex items-center gap-2"><AlertCircle className="w-4 h-4 text-rose-400" /> {errorMsg}</span>
            <button onClick={() => setErrorMsg(null)}><X className="w-4 h-4" /></button>
          </motion.div>
        )}
        {successMsg && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="bg-emerald-500/10 border-b border-emerald-500/20 px-6 py-2.5 text-emerald-300 text-xs flex items-center justify-between">
            <span className="flex items-center gap-2"><CheckCircle2 className="w-4 h-4 text-emerald-400" /> {successMsg}</span>
            <button onClick={() => setSuccessMsg(null)}><X className="w-4 h-4" /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 2. 双栏分屏主体 */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-slate-400 text-sm gap-3">
          <RefreshCw className="w-6 h-6 animate-spin text-indigo-400" />
          正在解析文档切片与物理章节...
        </div>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* 左栏：原文 / PDF / Word 原文档全景呈现 (60%) */}
          <div
            onMouseUp={handleDocTextMouseUp}
            className="w-3/5 border-r border-slate-800 flex flex-col bg-slate-950/40 relative select-text"
          >
            {/* 视图模式 & 标注工具切换 Toolbar */}
            <div className="p-3 border-b border-slate-800 flex items-center justify-between bg-slate-950/80 gap-2">
              {/* 左侧：视图模式切换 */}
              <div className="flex items-center space-x-1.5">
                <button
                  onClick={() => setViewMode('original')}
                  className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1 border ${
                    viewMode === 'original'
                      ? 'bg-indigo-600 text-white border-indigo-500 shadow-md shadow-indigo-600/20'
                      : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                  }`}
                >
                  <Eye className="w-3.5 h-3.5" /> 原文档 (PDF/Word)
                </button>
                <button
                  onClick={() => setViewMode('markdown')}
                  className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-1 border ${
                    viewMode === 'markdown'
                      ? 'bg-indigo-600 text-white border-indigo-500 shadow-md shadow-indigo-600/20'
                      : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-white'
                  }`}
                >
                  <FileText className="w-3.5 h-3.5" /> Markdown 视图
                </button>
              </div>

              {/* 中间：标注模式工具栏 (划选文本 vs 矩形框选图片) */}
              <div className="flex items-center space-x-1 bg-slate-900 p-1 rounded-xl border border-slate-800">
                <button
                  onClick={() => {
                    setAnnotationTool('text');
                    setSelectionPopoverPos(null);
                  }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition flex items-center gap-1 ${
                    annotationTool === 'text'
                      ? 'bg-indigo-500 text-white font-bold shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <MousePointerClick className="w-3.5 h-3.5" /> 划选文本
                </button>
                <button
                  onClick={() => {
                    setAnnotationTool('box');
                    setSelectionPopoverPos(null);
                  }}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition flex items-center gap-1 ${
                    annotationTool === 'box'
                      ? 'bg-indigo-500 text-white font-bold shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Crop className="w-3.5 h-3.5" /> 框选图片/盖章
                </button>
              </div>

              <span className="text-[11px] text-indigo-300 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 hidden xl:inline">
                {annotationTool === 'text' ? '💡 拖动鼠标拉选文本' : '🖼️ 鼠标画矩形框截取图片/印章'}
              </span>
            </div>

            {/* 模式 1: 真实原文档渲染引擎 (SmartDocViewer) */}
            {viewMode === 'original' ? (
              <div
                ref={docContainerRef}
                onMouseDown={handleBoxMouseDown}
                onMouseMove={handleBoxMouseMove}
                onMouseUp={handleBoxMouseUp}
                className={`flex-1 w-full h-full overflow-hidden bg-slate-900/50 relative ${
                  annotationTool === 'box' ? 'cursor-crosshair select-none' : ''
                }`}
              >
                <SmartDocViewer documents={viewerDocuments} />

                {/* 矩形框选 Drag 高亮显示框 */}
                {isBoxDragging && boxStart && boxEnd && (
                  <div
                    style={{
                      position: 'absolute',
                      left: `${Math.min(boxStart.x, boxEnd.x)}px`,
                      top: `${Math.min(boxStart.y, boxEnd.y)}px`,
                      width: `${Math.abs(boxEnd.x - boxStart.x)}px`,
                      height: `${Math.abs(boxEnd.y - boxStart.y)}px`,
                    }}
                    className="border-2 border-dashed border-indigo-400 bg-indigo-500/20 backdrop-blur-[1px] pointer-events-none rounded-lg z-30 shadow-lg shadow-indigo-500/30"
                  />
                )}
              </div>
            ) : (
              /* 模式 2: 提取 Markdown 卡片全景视图 */
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {filteredChunks.map((chunk) => (
                  <div
                    key={chunk.id}
                    onClick={() => setActiveChunkId(chunk.id)}
                    className={`p-4 rounded-xl border transition cursor-pointer relative ${
                      activeChunkId === chunk.id
                        ? 'border-indigo-500/80 bg-indigo-500/5 shadow-md shadow-indigo-500/10'
                        : 'border-slate-800 hover:border-slate-700 bg-slate-900/50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-indigo-300 font-semibold">
                        #{String(chunk.chunk_index + 1).padStart(2, '0')}
                      </span>
                      <span className="text-xs font-medium text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/50">
                        章节: {chunk.section_title || '无章节/正文'}
                      </span>
                    </div>
                    <div className="prose prose-invert prose-sm max-w-none text-slate-300 line-clamp-6">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{chunk.content}</ReactMarkdown>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>


          {/* 右栏：切片与章节标注工作台 (40%) */}
          <div className="w-2/5 flex flex-col bg-slate-900/80 overflow-hidden">
            {/* 章节过滤器与多选全选 Toolbar */}
            <div className="p-4 border-b border-slate-800 bg-slate-950/40 space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <button
                  onClick={toggleSelectAll}
                  className="flex items-center gap-1.5 hover:text-white transition"
                >
                  {selectedChunkIds.size === filteredChunks.length && filteredChunks.length > 0 ? (
                    <CheckSquare className="w-4 h-4 text-indigo-400" />
                  ) : (
                    <Square className="w-4 h-4 text-slate-500" />
                  )}
                  全选当前结果 ({selectedChunkIds.size}/{filteredChunks.length})
                </button>
                
                {selectedCategoryFilter && (
                  <button
                    onClick={() => setSelectedCategoryFilter(null)}
                    className="text-indigo-400 hover:underline text-xs flex items-center gap-1"
                  >
                    清除过滤器 ({selectedCategoryFilter})
                  </button>
                )}
              </div>

              {/* 章节快速标签筛选 */}
              <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto pt-1">
                <button
                  onClick={() => setSelectedCategoryFilter(null)}
                  className={`text-xs px-2.5 py-1 rounded-full border transition ${
                    selectedCategoryFilter === null
                      ? 'bg-indigo-600 text-white border-indigo-500'
                      : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
                  }`}
                >
                  全部 ({chunks.length})
                </button>
                {uniqueSections.map((sec) => (
                  <button
                    key={sec}
                    onClick={() => setSelectedCategoryFilter(sec)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition ${
                      selectedCategoryFilter === sec
                        ? 'bg-indigo-600 text-white border-indigo-500'
                        : 'bg-slate-800 text-slate-400 border-slate-700 hover:text-white'
                    }`}
                  >
                    {sec}
                  </button>
                ))}
              </div>
            </div>

            {/* 切片卡片标注列表 */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {filteredChunks.map((chunk, idx) => {
                const isSelected = selectedChunkIds.has(chunk.id);
                const isActive = activeChunkId === chunk.id;

                return (
                  <div
                    key={chunk.id}
                    className={`p-4 rounded-xl border transition flex flex-col space-y-3 ${
                      isActive
                        ? 'border-indigo-500 bg-slate-800/90 shadow-lg shadow-indigo-500/10'
                        : isSelected
                        ? 'border-indigo-500/60 bg-indigo-950/20'
                        : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
                    }`}
                  >
                    {/* Header */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center space-x-2">
                        <button onClick={() => toggleSelectChunk(chunk.id)}>
                          {isSelected ? (
                            <CheckSquare className="w-4 h-4 text-indigo-400" />
                          ) : (
                            <Square className="w-4 h-4 text-slate-600" />
                          )}
                        </button>
                        <span className="text-xs font-mono font-bold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                          #{String(chunk.chunk_index + 1).padStart(2, '0')}
                        </span>
                        <span className="text-xs text-slate-400">页码: P.{chunk.page_num || 1}</span>
                      </div>

                      <div className="flex items-center space-x-1">
                        <button
                          onClick={() => handleSplitChunk(chunk.id)}
                          title="修饰文本或拆分切片"
                          className="p-1 text-slate-400 hover:text-indigo-300 hover:bg-slate-800 rounded transition"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                        {idx < filteredChunks.length - 1 && (
                          <button
                            onClick={() => handleMergeWithNext(idx)}
                            title="与下一个切片合并"
                            className="p-1 text-slate-400 hover:text-indigo-300 hover:bg-slate-800 rounded transition"
                          >
                            <GitMerge className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteChunk(chunk.id)}
                          title="删除此切片 (支持人工智能与人工切片)"
                          className="p-1 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded transition"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* 所属章节选择框 */}
                    <div className="flex flex-col space-y-1">
                      <label className="text-[11px] font-medium text-slate-400 flex items-center gap-1">
                        <Tag className="w-3 h-3 text-indigo-400" /> 人工指定所属章节:
                      </label>
                      <input
                        type="text"
                        list={`sections-list-${chunk.id}`}
                        value={chunk.section_title || ''}
                        onChange={(e) => handleUpdateChunkTitle(chunk.id, e.target.value)}
                        placeholder="输入或选择所属章节 (例如: 一、商务响应)"
                        className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-lg px-3 py-1.5 text-xs text-slate-200 outline-none transition"
                      />
                      <datalist id={`sections-list-${chunk.id}`}>
                        {uniqueSections.map((s) => (
                          <option key={s} value={s} />
                        ))}
                      </datalist>
                    </div>

                    {/* 文本内容简短预览 */}
                    <div className="text-xs text-slate-400 bg-slate-950/60 p-2.5 rounded-lg border border-slate-800/60 line-clamp-4 font-mono leading-relaxed">
                      {chunk.content}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 3. 批量设置章节模态框 */}
      <AnimatePresence>
        {showBatchModal && (
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 w-full max-w-md space-y-5 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Tag className="w-5 h-5 text-indigo-400" /> 批量指定切片章节
                </h3>
                <button onClick={() => setShowBatchModal(false)}><X className="w-5 h-5 text-slate-400" /></button>
              </div>

              <div className="space-y-2">
                <p className="text-xs text-slate-400">
                  当前已选中 <strong className="text-indigo-400 font-bold">{selectedChunkIds.size}</strong> 块切片。请输入或选择要统一归属的章节名称：
                </p>
                <input
                  type="text"
                  list="batch-sections-list"
                  value={batchSectionTitle}
                  onChange={(e) => setBatchSectionTitle(e.target.value)}
                  placeholder="例如: 二、技术方案及施工组织"
                  className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-xl p-3 text-sm text-slate-100 outline-none"
                />
                <datalist id="batch-sections-list">
                  {uniqueSections.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button onClick={() => setShowBatchModal(false)} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold">
                  取消
                </button>
                <button onClick={handleApplyBatchSectionTitle} className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/30">
                  应用批量更新
                </button>
              </div>
            </motion.div>
          </div>
        )}

        {/* 编辑修改切片文本模态框 */}
        {editingChunkId && (
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} className="bg-slate-900 border border-slate-800 rounded-2xl p-6 w-full max-w-2xl space-y-5 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Edit3 className="w-5 h-5 text-indigo-400" /> 编辑切片文本
                </h3>
                <button onClick={() => setEditingChunkId(null)}><X className="w-5 h-5 text-slate-400" /></button>
              </div>

              <div className="space-y-2">
                <textarea
                  rows={10}
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-xl p-3 text-xs font-mono text-slate-200 outline-none leading-relaxed"
                />
              </div>

              <div className="flex justify-end space-x-3">
                <button onClick={() => setEditingChunkId(null)} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold">
                  取消
                </button>
                <button onClick={handleSaveTextEdit} className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-indigo-600/30">
                  确认应用修改
                </button>
              </div>
            </motion.div>
          </div>
        )}

        {/* 按页码范围批量标注模态框 (Page Range Modal) */}
        {showPageRangeModal && (
          <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-6 w-full max-w-md space-y-5 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-indigo-400" /> 按页码范围批量标注
                </h3>
                <button onClick={() => setShowPageRangeModal(false)}>
                  <X className="w-5 h-5 text-slate-400 hover:text-white" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-400 font-semibold mb-1 block">起始页码 (Start Page)</label>
                    <input
                      type="number"
                      min={1}
                      value={startPage}
                      onChange={(e) => setStartPage(e.target.value ? Number(e.target.value) : '')}
                      placeholder="如: 5"
                      className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-xl px-3 py-2 text-sm text-slate-100 outline-none font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 font-semibold mb-1 block">结束页码 (End Page)</label>
                    <input
                      type="number"
                      min={1}
                      value={endPage}
                      onChange={(e) => setEndPage(e.target.value ? Number(e.target.value) : '')}
                      placeholder="如: 12"
                      className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-xl px-3 py-2 text-sm text-slate-100 outline-none font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs text-slate-400 font-semibold mb-1 block">归属章节名称 (Section Title)</label>
                  <input
                    type="text"
                    list="range-sections"
                    value={rangeSectionTitle}
                    onChange={(e) => setRangeSectionTitle(e.target.value)}
                    placeholder="如: 三、资格证明文件 / 商务部分"
                    className="w-full bg-slate-950 border border-slate-800 focus:border-indigo-500 rounded-xl px-3 py-2 text-sm text-slate-100 outline-none"
                  />
                  <datalist id="range-sections">
                    {uniqueSections.map((s) => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                </div>

                <p className="text-[11px] text-slate-400 leading-relaxed bg-slate-950/60 p-3 rounded-xl border border-slate-800/80">
                  💡 提示：输入页码范围后，系统会自动将第 <strong>{startPage || 'X'}</strong> 页至第 <strong>{endPage || 'Y'}</strong> 页内的所有切片一次性更新为该章节！
                </p>
              </div>

              <div className="flex justify-end space-x-3 pt-2 border-t border-slate-800">
                <button
                  onClick={() => setShowPageRangeModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold"
                >
                  取消
                </button>
                <button
                  onClick={handleApplyPageRangeAnnotation}
                  disabled={!startPage || !endPage || !rangeSectionTitle.trim()}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-bold transition shadow-lg shadow-indigo-600/30"
                >
                  确认应用标注
                </button>
              </div>
            </motion.div>
          </div>
        )}

        {/* 原文档划选/框选浮动标注气泡 (Selection Popover) */}
        {selectionPopoverPos && selectedTextFromDoc && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 5 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9 }}
            style={{
              position: 'fixed',
              left: `${selectionPopoverPos.x}px`,
              top: `${selectionPopoverPos.y}px`,
              transform: 'translateX(-50%)',
            }}
            className="z-50 bg-slate-950/95 border border-indigo-500 shadow-2xl rounded-xl p-3 flex items-center gap-3 backdrop-blur-md"
          >
            {croppedImageData ? (
              <div className="flex items-center gap-2">
                <img
                  src={croppedImageData}
                  alt="框选截图"
                  className="h-10 w-16 object-cover rounded border border-indigo-500/50 bg-white"
                />
                <span className="text-xs text-indigo-300 font-semibold flex items-center gap-1">
                  <Crop className="w-3.5 h-3.5 text-indigo-400" /> 已框选图片:
                </span>
              </div>
            ) : (
              <span className="text-xs text-indigo-300 font-semibold flex items-center gap-1">
                <MousePointerClick className="w-3.5 h-3.5 text-indigo-400" /> 已划选文本 ({selectedTextFromDoc.length}字):
              </span>
            )}
            <input
              type="text"
              list="popover-sections"
              value={targetSectionForSelection}
              onChange={(e) => setTargetSectionForSelection(e.target.value)}
              placeholder="指定章节 (如 一、投标函)"
              className="bg-slate-900 border border-slate-700 text-xs text-slate-100 rounded-lg px-2.5 py-1.5 focus:border-indigo-500 outline-none w-44"
            />
            <datalist id="popover-sections">
              {uniqueSections.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
            <button
              onClick={handleConfirmSelectionChunk}
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1 shadow-md shadow-indigo-600/30"
            >
              <PlusCircle className="w-3.5 h-3.5" /> 确认生成切片
            </button>
            <button
              onClick={() => {
                setSelectionPopoverPos(null);
                setCroppedImageData(null);
              }}
              className="text-slate-400 hover:text-white p-1"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
