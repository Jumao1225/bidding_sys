import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { EnvConfigPage, getDraftStorageKey, parseEnvContent, serializeEnvContent } from './EnvConfigPage';

describe('EnvConfigPage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('应该展示配置分组并允许编辑后保存草稿', () => {
    render(<EnvConfigPage />);

    const modelNameInput = screen.getByLabelText('模型名称', { selector: '#env-LLM_MODEL_NAME' });
    fireEvent.change(modelNameInput, { target: { value: 'gpt-4.1' } });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));

    expect(localStorage.getItem(getDraftStorageKey())).toContain('gpt-4.1');
    expect(screen.getByText('模型配置草稿已保存到当前浏览器')).toBeInTheDocument();
  });

  it('应该导入合法变量并忽略注释、空行和非法行', async () => {
    render(<EnvConfigPage />);
    const file = new File(['# comment\nLLM_MODEL_NAME=gpt-4.1\nINVALID LINE\nOPENAI_API_BASE="https://example.com/v1"\n'], '.env', { type: 'text/plain' });

    fireEvent.change(screen.getByLabelText('导入 .env 文件'), { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText('已导入 2 项模型配置，请检查后保存或导出')).toBeInTheDocument());
    expect(screen.getByLabelText('模型名称', { selector: '#env-LLM_MODEL_NAME' })).toHaveValue('gpt-4.1');
    expect(screen.getByLabelText('API 地址', { selector: '#env-OPENAI_API_BASE' })).toHaveValue('https://example.com/v1');
  });

  it('应该稳定序列化带空格和引号的变量值', () => {
    const content = serializeEnvContent({ LLM_MODEL_NAME: 'gpt-4.1', SIMPLE: 'value', WITH_SPACE: 'hello world', WITH_QUOTE: 'a"b' });

    expect(content).toContain('LLM_MODEL_NAME=gpt-4.1');
    expect(content).toContain('SIMPLE=value');
    expect(content).toContain('WITH_SPACE="hello world"');
    expect(content).toContain('WITH_QUOTE="a\\"b"');
    expect(parseEnvContent(content)).toMatchObject({ SIMPLE: 'value', WITH_SPACE: 'hello world', WITH_QUOTE: 'a"b' });
  });

  it('应该为不同用户生成相互隔离的草稿存储空间', () => {
    localStorage.setItem('bidding_user', JSON.stringify({ id: 'user-a' }));
    const firstUserKey = getDraftStorageKey();
    localStorage.setItem('bidding_user', JSON.stringify({ id: 'user-b' }));
    const secondUserKey = getDraftStorageKey();

    expect(firstUserKey).not.toBe(secondUserKey);
  });
});
