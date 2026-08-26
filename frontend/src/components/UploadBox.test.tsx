import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('./SmartDocViewer', () => ({
  SmartDocViewer: () => null,
}));

import { get_original_file_preview_id, UploadBox } from './UploadBox';

describe('UploadBox Component', () => {
  it('应该正常渲染上传组件的核心提示信息', () => {
    render(<UploadBox />);
    
    // 寻找包含上传相关字眼的文本
    const dragText = screen.getByText(/拖拽 Word\/PDF 文件到此处/i);
    const clickText = screen.getByText(/点击浏览文件/i);
    expect(dragText).toBeInTheDocument();
    expect(clickText).toBeInTheDocument();
  });

  it('存在持久化文档 ID 时应优先用于原文件预览', () => {
    expect(get_original_file_preview_id(
      'task-123',
      { document_id: 'document-456' },
      'initial-task-789',
    )).toBe('document-456');
  });

  it('尚未建档时应回退到当前任务 ID', () => {
    expect(get_original_file_preview_id(
      'task-123',
      null,
      'initial-task-789',
    )).toBe('task-123');
  });
});
