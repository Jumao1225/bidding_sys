export type AnalysisErrorSource = 'task' | 'connection' | 'request';

export interface AnalysisErrorInfo {
  title: string;
  message: string;
  suggestion: string;
  code: string;
}

const INTERNAL_ERROR_PATTERNS = [
  /retryerror/i,
  /<future\b/i,
  /0x[0-9a-f]+/i,
  /traceback/i,
  /stack trace/i,
];

const MODEL_UNAVAILABLE_PATTERNS = [
  'model not found',
  'model_not_found',
  'model unavailable',
  'model is not available',
  'model does not exist',
  'model not exist',
  'unsupported model',
  'model has been deprecated',
  '模型不可用',
  '模型不存在',
  '模型已下线',
  '模型已停用',
  '不支持该模型',
  '模型权限',
];

/**
 * 从不同接口错误结构中提取文本，避免 UI 层依赖某一种后端响应格式。
 */
function extract_error_message(raw_error: unknown): string {
  if (typeof raw_error === 'string') return raw_error.trim();
  if (raw_error instanceof Error) return raw_error.message.trim();
  if (!raw_error || typeof raw_error !== 'object') return '';

  const error_record = raw_error as Record<string, unknown>;
  for (const key of ['message', 'detail', 'error']) {
    const value = error_record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

/**
 * 仅保留简短、无内部实现痕迹的业务错误，防止内存地址和异常栈直接暴露给用户。
 */
function is_safe_business_message(message: string): boolean {
  if (!message || message.length > 160) return false;
  return !INTERNAL_ERROR_PATTERNS.some((pattern) => pattern.test(message));
}

/**
 * 将解析链路的技术异常转换为稳定、可操作的中文提示。
 */
export function build_analysis_error_info(
  raw_error: unknown,
  source: AnalysisErrorSource = 'task',
): AnalysisErrorInfo {
  const raw_message = extract_error_message(raw_error);
  const normalized_message = raw_message.toLowerCase();

  if (
    normalized_message.includes('retryerror')
    || normalized_message.includes('raised retryerror')
    || normalized_message.includes('重试次数')
  ) {
    return {
      title: '解析服务暂时不可用',
      message: '系统已自动重试多次，但上游 AI 服务仍未响应。',
      suggestion: '请检查“模型配置”中的 API 地址、密钥和模型可用性，或稍后重新解析。',
      code: 'UPSTREAM_RETRY_EXHAUSTED',
    };
  }

  if (
    normalized_message.includes('timeout')
    || normalized_message.includes('timed out')
    || normalized_message.includes('超时')
  ) {
    return {
      title: '解析等待超时',
      message: '文档解析在规定时间内没有完成。',
      suggestion: '请稍后重试；若持续出现，请检查模型服务和文档解析服务是否可用。',
      code: 'ANALYSIS_TIMEOUT',
    };
  }

  const is_model_unavailable = MODEL_UNAVAILABLE_PATTERNS.some((pattern) =>
    normalized_message.includes(pattern),
  ) || (
    normalized_message.includes('model')
    && (
      normalized_message.includes('permission')
      || normalized_message.includes('forbidden')
      || normalized_message.includes('unauthorized')
      || normalized_message.includes('access denied')
    )
  );
  if (is_model_unavailable) {
    return {
      title: '当前模型不可用',
      message: '配置的模型不存在、已停用或当前账号无权访问。',
      suggestion: '请前往“模型配置”切换可用模型后重新解析。',
      code: 'MODEL_UNAVAILABLE',
    };
  }

  if (
    normalized_message.includes('unauthorized')
    || normalized_message.includes('forbidden')
    || normalized_message.includes('api key')
    || normalized_message.includes('apikey')
    || normalized_message.includes('鉴权')
    || normalized_message.includes('密钥')
  ) {
    return {
      title: '模型服务认证失败',
      message: '当前模型服务配置未通过认证。',
      suggestion: '请在“模型配置”中检查 API 密钥、服务地址和账号权限。',
      code: 'MODEL_AUTH_FAILED',
    };
  }

  if (source === 'connection') {
    return {
      title: '解析进度连接已中断',
      message: '页面暂时无法接收解析进度，当前任务可能仍在后台运行。',
      suggestion: '请稍后重试；若重复出现，请检查后端服务与网络连接。',
      code: 'PROGRESS_CONNECTION_LOST',
    };
  }

  if (source === 'request') {
    return {
      title: '解析请求未能提交',
      message: '页面暂时无法连接解析服务。',
      suggestion: '请检查后端服务和网络连接后重试。',
      code: 'ANALYSIS_REQUEST_FAILED',
    };
  }

  return {
    title: '文档解析失败',
    message: is_safe_business_message(raw_message) ? raw_message : '解析过程中出现异常，未能生成结果。',
    suggestion: '请重新解析；若问题持续出现，请联系管理员并提供下方错误编号。',
    code: 'ANALYSIS_FAILED',
  };
}
