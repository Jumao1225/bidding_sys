import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.company_qualification_service import CompanyQualificationService


def test_parse_image_should_prompt_for_missing_tenant_vlm_config():
    """租户未配置视觉模型时，图片资质解析应提示填写租户配置。"""
    service = CompanyQualificationService()
    file_descriptor, image_path = tempfile.mkstemp(suffix=".png")
    os.close(file_descriptor)
    try:
        with patch(
            "app.services.model_config_service.model_config_service.get_effective_values",
            return_value={
                "ALI_VLM_API_KEY": "",
                "ALI_VLM_API_BASE": "",
                "ALI_VLM_MODEL_NAME": "",
            },
        ):
            with pytest.raises(HTTPException, match="模型配置") as error_info:
                service._parse_image_via_vlm(
                    db=None,
                    file_path=image_path,
                    file_url="/uploads/qualifications/missing-config.png",
                    tenant_id="tenant-a",
                )
    finally:
        os.remove(image_path)

    assert error_info.value.status_code == 400
