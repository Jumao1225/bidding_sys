import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { UploadBox } from './UploadBox';

describe('UploadBox Component', () => {
  it('应该正常渲染上传组件的核心提示信息', () => {
    render(<UploadBox />);
    
    // 寻找包含上传相关字眼的文本
    const dragText = screen.getByText(/拖拽 PDF 文件到此处/i);
    const clickText = screen.getByText(/点击浏览文件/i);
    expect(dragText).toBeInTheDocument();
    expect(clickText).toBeInTheDocument();
  });
});
