"""
.doc 到 .docx 转换功能单元测试
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.extractor_service import ExtractorService


def test_convert_doc_to_docx_when_target_docx_already_exists_should_return_path_immediately(tmp_path):
    """测试当目标 .docx 文件已经存在时，直接返回已有路径而不重新调用转换逻辑"""
    service = ExtractorService()
    doc_file = tmp_path / "sample.doc"
    doc_file.write_text("dummy doc content", encoding="utf-8")
    docx_file = tmp_path / "sample.docx"
    docx_file.write_text("existing docx content", encoding="utf-8")

    result = service.convert_doc_to_docx(str(doc_file))
    assert result == str(docx_file)


def test_convert_doc_to_docx_soffice_found_in_path_should_run_soffice_cmd(tmp_path):
    """测试当系统存在 soffice 时，正常触发 LibreOffice 转换指令"""
    service = ExtractorService()
    doc_file = tmp_path / "test.doc"
    doc_file.write_text("dummy doc content", encoding="utf-8")
    docx_file = tmp_path / "test.docx"

    def mock_subprocess_run(cmd, **kwargs):
        # 模拟 LibreOffice 转换成功产出 test.docx
        docx_file.write_text("converted docx", encoding="utf-8")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stderr = ""
        return mock_res

    with patch("shutil.which", return_value="/usr/bin/soffice"):
        with patch("subprocess.run", side_effect=mock_subprocess_run):
            result = service.convert_doc_to_docx(str(doc_file))
            assert result == str(docx_file)
            assert os.path.exists(result)


def test_convert_doc_to_docx_all_methods_fail_should_raise_runtime_error_with_detailed_guide(tmp_path):
    """测试当 LibreOffice、win32com 与 doc2docx 均不可用时，系统抛出包含指引说明的 RuntimeError 并且不产生裸崩溃"""
    service = ExtractorService()
    doc_file = tmp_path / "not_existing_engine.doc"
    doc_file.write_text("dummy content", encoding="utf-8")

    with patch("shutil.which", return_value=None):
        with patch("os.path.isfile", return_value=False):
            with patch("sys.platform", "linux"):  # 模拟非 Windows 无 win32com 降级
                with pytest.raises(RuntimeError) as exc_info:
                    service.convert_doc_to_docx(str(doc_file))
                
                assert ".doc 转 .docx 失败" in str(exc_info.value)
                assert "LibreOffice" in str(exc_info.value)
