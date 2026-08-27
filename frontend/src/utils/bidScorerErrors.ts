import { BidDocumentUploadError } from '../api/bidScorerApi';

/**
 * 将上传接口的临时网络或解析服务异常转换为用户可执行的重试提示。
 */
export function getBidUploadErrorMessage(error: unknown): string {
  if (error instanceof BidDocumentUploadError && error.status >= 500) {
    return '网络或文档解析服务暂时不稳定，本次上传未完成，请稍后重新点击“上传并解析投标文件”重试。';
  }

  if (!(error instanceof Error)) {
    return '网络连接异常，本次上传未完成，请稍后重新点击“上传并解析投标文件”重试。';
  }

  if (error.name === 'TypeError' || /网络|network|fetch|failed to fetch|连接|超时|timeout/i.test(error.message)) {
    return '网络连接暂时不稳定，本次上传未完成，请稍后重新点击“上传并解析投标文件”重试。';
  }

  return error.message || '上传失败，请稍后重新点击“上传并解析投标文件”重试。';
}
