import { describe, expect, it, vi } from 'vitest';
import { deduplicate_documents, type DocumentRecord } from './Home';

describe('deduplicate_documents', () => {
  it('存在重复文档 ID 时应仅保留第一条记录', () => {
    const warn_spy = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const documents: DocumentRecord[] = [
      { id: 'document-1', filename: '招标文件.pdf', status: 'completed', created_at: null },
      { id: 'document-1', filename: '重复招标文件.pdf', status: 'completed', created_at: null },
      { id: 'document-2', filename: '投标文件.docx', status: 'pending', created_at: null },
    ];

    const result = deduplicate_documents(documents);

    expect(result).toEqual([documents[0], documents[2]]);
    expect(warn_spy).toHaveBeenCalledWith(
      '文档列表返回重复 ID，已忽略重复记录',
      expect.objectContaining({ document_id: 'document-1' }),
    );
    warn_spy.mockRestore();
  });
});
