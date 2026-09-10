/** 当前浏览器会话中选中的真实文档 ID。 */
export const ACTIVE_DOCUMENT_STORAGE_KEY = 'bidding_document_id';

/** 文档 ID 变化事件，供 App 和 ChatPanel 同步当前文档。 */
export const DOCUMENT_CHANGED_EVENT = 'bidding_document_changed';

/**
 * 保存真实文档 ID，并通知依赖当前文档的组件。
 * 任务 ID 不能传入此函数，调用方应只传入 documents.id。
 */
export function set_active_document_id(document_id: unknown): boolean {
  if (typeof document_id !== 'string' || !document_id.trim()) {
    return false;
  }

  const normalized_document_id = document_id.trim();
  if (localStorage.getItem(ACTIVE_DOCUMENT_STORAGE_KEY) === normalized_document_id) {
    return false;
  }

  localStorage.setItem(ACTIVE_DOCUMENT_STORAGE_KEY, normalized_document_id);
  window.dispatchEvent(new Event(DOCUMENT_CHANGED_EVENT));
  return true;
}

/**
 * 清理当前文档 ID；可传 expected_document_id 防止误删后来写入的新文档。
 */
export function clear_active_document_id(expected_document_id?: string): boolean {
  const current_document_id = localStorage.getItem(ACTIVE_DOCUMENT_STORAGE_KEY);
  if (!current_document_id) {
    return false;
  }
  if (expected_document_id && current_document_id !== expected_document_id) {
    return false;
  }

  localStorage.removeItem(ACTIVE_DOCUMENT_STORAGE_KEY);
  window.dispatchEvent(new Event(DOCUMENT_CHANGED_EVENT));
  return true;
}
