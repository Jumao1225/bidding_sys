import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CostTable, normalizeCostText, normalizeCostTextList } from './CostTable';

vi.mock('../utils/api', () => ({
  API_BASE_URL: '',
  apiFetch: vi.fn(),
}));

describe('CostTable 设备清单重新提取入口', () => {
  it('结构化关键参数应转换为可展示文本而不是直接渲染对象', () => {
    expect(normalizeCostText({ type: 'text', input: '10kV' })).toBe('10kV');
    expect(normalizeCostTextList([{ type: 'text', input: '10kV' }, '630A'])).toEqual(['10kV', '630A']);
  });

  it('历史结构化关键参数应正常渲染成本表', () => {
    render(
      <CostTable
        costAnalysis={{
          items: [{
            name: '并网柜',
            unit: null,
            qty: 1,
            ref_price: 100,
            key_parameters: [{ type: 'text', input: '10kV' }],
            match_quality: '精准匹配'
          }]
        }}
      />
    );

    expect(screen.getByText('10kV')).toBeInTheDocument();
  });

  it('点击重新提取设备清单按钮应触发回调', () => {
    const onReextractEquipment = vi.fn();

    render(
      <CostTable
        costAnalysis={{ items: [] }}
        onReextractEquipment={onReextractEquipment}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: '重新提取设备清单' }));

    expect(onReextractEquipment).toHaveBeenCalledTimes(1);
  });

  it('重新提取执行期间应禁用重新提取按钮', () => {
    render(
      <CostTable
        costAnalysis={{ items: [] }}
        onReextractEquipment={vi.fn()}
        isExtractingEquipment
      />
    );

    expect(screen.getByRole('button', { name: '重新提取设备清单' })).toBeDisabled();
    expect(screen.getByText('正在重新提取设备清单并计算成本...')).toBeInTheDocument();
  });
});
