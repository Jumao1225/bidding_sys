import { apiFetch, API_BASE_URL } from '../utils/api';

/**
 * 招标文件（测试打分参考源与标准裁判指南）数据对象
 */
export interface TenderDocumentRecord {
  id: string;
  filename: string;
  doc_type?: string;
  file_path?: string;
  source_doc_id?: string;
  status: string;
  created_at: string | null;
}

/**
 * 分类打分结果概要
 */
export interface ScoreCategory {
  score: number;
  max_total: number;
  count: number;
}

/**
 * 细分考研评分项明细 (带三连次打分置信度与 RAG 依据证据链)
 */
export interface ScoreItem {
  id: string;
  item_code: string;
  category: string;
  sub_category?: string;
  title: string;
  max_score: number;
  ai_score: number;
  confidence: number;          // 共识度 0.0 ~ 1.0
  score_variance: number;      // 3轮打分标准差
  all_round_scores: number[];  // [round1, round2, round3]
  scoring_basis?: string;      // RAG 取证原句背书
  deduction_reason?: string;   // 扣分因由
  suggestion?: string;         // 定向 AI 修补指导
}

export interface ImprovementAction {
  priority?: string;
  category?: string;
  title?: string;
  current_score?: number;
  potential_gain?: number;
  action?: string;
}

/**
 * 单次打分完整度诊断报告
 */
export interface ScoreResultDetail {
  id: string;
  result_id?: string;
  document_id: string;
  source_doc_id: string;
  evaluation_method?: string;
  total_score: number;
  max_possible: number;
  score_rate: number;          // 如 0.945
  category_scores: Record<string, ScoreCategory>;
  summary: string;
  top_improvements: (string | ImprovementAction | any)[];  // 前三甲涨分锦囊（支持纯字符串及强类型对象）
  validation_warnings: (string | any)[]; // 防幻觉L5自适应审核截断纪录
  scoring_rounds: number;
  model_name?: string;
  created_at?: string;
  items?: ScoreItem[];
}

/**
 * 投标文件上传接口错误，保留 HTTP 状态码供页面区分临时服务异常与用户输入错误。
 */
export class BidDocumentUploadError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'BidDocumentUploadError';
    this.status = status;
  }
}

/**
 * 1. 拉取所有状态完好的历史解析招标文件作为“评分尺度/裁判法典 (source_doc)”
 * 默认仅查询 doc_type=tender 招标文件
 */
export async function fetchTenderDocuments(docType: string = 'tender'): Promise<TenderDocumentRecord[]> {
  const queryUrl = docType ? `${API_BASE_URL}/api/v1/documents/?doc_type=${docType}` : `${API_BASE_URL}/api/v1/documents/`;
  const res = await apiFetch(queryUrl);
  if (!res.ok) throw new Error('无法加载历史招标文件列表');
  const json = await res.json();
  const list = Array.isArray(json?.data) ? json.data : (Array.isArray(json) ? json : []);
  return list.filter((doc: any) => {
    const status = String(doc?.status || '').toLowerCase();
    return status === 'parsed' || status === 'completed' || status === 'success' || (status !== '' && !status.includes('fail'));
  });
}

/**
 * 2. 专向轻量上传被检验的投标文件并绑带指定评分字典主键
 */
export async function uploadBidDocument(file: File, sourceDocId: string): Promise<{ document_id: string; chunk_count: number; parse_status: string }> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source_doc_id', sourceDocId);

  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/upload-bid`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const errText = await res.text();
    let errorMessage = '投标文件轻量解析上传失败';

    try {
      const errJson = JSON.parse(errText);
      if (typeof errJson.detail === 'string' && errJson.detail.trim()) {
        errorMessage = errJson.detail;
      }
    } catch {
      if (errText.trim()) {
        errorMessage = `投标文件轻量解析上传失败: ${errText}`;
      }
    }

    throw new BidDocumentUploadError(errorMessage, res.status);
  }
  const json = await res.json();
  return json.data;
}

/**
 * 3. 发火指令：开启多类别并发中位投票打分流水线 (Map-Reduce Engine)
 */
export async function triggerBidScore(documentId: string, sourceDocId: string, scoringRounds = 3): Promise<ScoreResultDetail> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      document_id: documentId,
      source_doc_id: sourceDocId,
      scoring_rounds: scoringRounds,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    try {
      const errJson = JSON.parse(errText);
      throw new Error(errJson.detail || '大模型智能评分触发异常');
    } catch {
      throw new Error('大模型智能评分触发异常');
    }
  }
  const json = await res.json();
  if (json.code !== 200) {
    throw new Error(json.message || '打分发生异常');
  }
  return json.data;
}

/**
 * 4. 调取最近成果概况（支持不重复发打分请求直接翻读）
 */
export async function getLatestScoreResult(documentId: string): Promise<ScoreResultDetail | null> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/results/${documentId}/latest`, {
    method: 'GET',
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error('同步最近评分报告失败');
  const json = await res.json();
  return json.data;
}

/**
 * 5. 深扎到底取回单笔评量战报含所有自适应考核项
 */
export async function getScoreResultDetail(resultId: string): Promise<ScoreResultDetail> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/detail/${resultId}`, {
    method: 'GET',
  });
  if (!res.ok) throw new Error('无法读取完整打分明细清单');
  const json = await res.json();
  return json.data;
}

/**
 * 6. 一键抹去已传标书分层记忆流并清退所有测试过往报表
 */
export async function deleteBidDocument(documentId: string): Promise<boolean> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/document/${documentId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errText = await res.text();
    try {
      const errJson = JSON.parse(errText);
      throw new Error(errJson.detail || '清理记忆文档失败');
    } catch {
      throw new Error('清零遗留记录无法按期卸除');
    }
  }
  return true;
}

export interface DocChunkDetail {
  id: string;
  document_id: string;
  chunk_index: number;
  section_title?: string;
  parent_chapter?: string;
  content: string;
  page_num?: number;
  has_table?: boolean;
}

export interface ChunkUpdateItem {
  id?: string;
  chunk_index: number;
  section_title?: string;
  parent_chapter?: string;
  content: string;
  page_num?: number;
}

/**
 * 7. 获取指定文档的所有切片明细列表（用于人工章节标注与预览）
 */
export async function fetchDocumentChunks(documentId: string): Promise<DocChunkDetail[]> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/chunks/${documentId}`);
  if (!res.ok) throw new Error('拉取切片明细失败');
  const json = await res.json();
  return json.data || [];
}

/**
 * 8. 批量保存人工修改与章节标注后的切片数据（触发向量重计算）
 */
export async function updateDocumentChunks(documentId: string, chunks: ChunkUpdateItem[]): Promise<{ chunk_count: number; human_annotated: boolean }> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/chunks/${documentId}/batch-update`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chunks }),
  });
  if (!res.ok) {
    const errText = await res.text();
    try {
      const errJson = JSON.parse(errText);
      throw new Error(errJson.detail || '保存切片标注失败');
    } catch {
      throw new Error('保存切片标注失败: ' + errText);
    }
  }
  const json = await res.json();
  return json.data;
}

/**
 * 9. 针对特定评估维度发送用户微调指令重新打分 (Human-in-the-Loop Interactive Rescore)
 */
export async function rescoreCategory(
  resultId: string,
  category: string,
  userInstruction: string,
  scoringRounds: number = 1,
  itemCode?: string
): Promise<ScoreResultDetail> {
  const res = await apiFetch(`${API_BASE_URL}/api/v1/bid-scorer/rescore-category`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      result_id: resultId,
      category: category,
      item_code: itemCode,
      user_instruction: userInstruction,
      scoring_rounds: scoringRounds,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    try {
      const errJson = JSON.parse(errText);
      throw new Error(errJson.detail || '微调重算失败');
    } catch {
      throw new Error('微调重算失败: ' + errText);
    }
  }

  const json = await res.json();
  return json.data;
}
