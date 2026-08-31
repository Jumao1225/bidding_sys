import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.main import app
from app.api.deps import get_current_active_user
from app.db.models.metadata import FinancialMetadata

@pytest.mark.asyncio
async def test_update_cost_analysis_should_succeed():
    """测试手动更新 BOM 成本核算明细与自定义费用分项，验证小计、总成本重算与持久化落盘"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {"budget_limit": "100000"}

    payload = {
        "items": [
            {
                "name": "并网柜",
                "spec_requirement": "10kV 并网柜",
                "qty": 2,
                "unit": "台",
                "ref_price": 20000.0,
                "matched_name": "并网柜",
                "matched_brand": "正泰",
                "match_quality": "精准匹配",
                "remark": "含成套安装调试费"
            },
            {
                "name": "现场施工人工费",
                "spec_requirement": "含设备安装调试与调班人工费",
                "qty": 1,
                "unit": "项",
                "ref_price": 15000.0,
                "match_quality": "手动添加"
            },
            {
                "name": "售后运维服务费",
                "spec_requirement": "3年免费质保与定期维保服务",
                "qty": 1,
                "unit": "项",
                "ref_price": 5000.0,
                "match_quality": "手动添加"
            }
        ],
        "analysis_summary": "手动补充施工与售后维保服务费用。"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-123/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                assert res_json["code"] == 200
                
                data = res_json["data"]
                # 2*20000 + 15000 + 5000 = 60000.0
                assert data["total_cost"] == 60000.0
                assert len(data["items"]) == 3
                assert data["items"][1]["name"] == "现场施工人工费"
                assert data["items"][1]["subtotal"] == 15000.0
                assert data["items"][2]["name"] == "售后运维服务费"
                assert data["items"][2]["subtotal"] == 5000.0
                assert data["items"][0]["remark"] == "含成套安装调试费"
                assert "可控" in data["budget_status"]
                
                # 验证 mock_doc 中的 parsed_metadata 正确持久化
                saved_cost = mock_doc.parsed_metadata["cost_analysis"]
                assert saved_cost["total_cost"] == 60000.0
                assert len(saved_cost["items"]) == 3
                assert saved_cost["items"][0]["remark"] == "含成套安装调试费"
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_update_cost_analysis_with_financial_max_price_limit_exceeded():
    """测试当 FinancialMetadata 存在最高投标限价，且人工修改总成本超出限额时，精准返回已超出最高限价与超额金额"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    # Mock FinancialMetadata
    mock_fin = MagicMock(spec=FinancialMetadata)
    mock_fin.max_price_limit = {"amount": 50000.0, "currency": "CNY"}
    mock_fin.budget = {"amount": 60000.0, "currency": "CNY"}

    payload = {
        "items": [
            {
                "name": "高规格逆变器",
                "qty": 2,
                "ref_price": 30000.0,
                "unit": "台"
            }
        ],
        "analysis_summary": "人工调整为高规格逆变器"
    }

    mock_db_session = MagicMock()
    mock_db_session.query.return_value.filter.return_value.first.return_value = mock_fin
    from app.api.endpoints.analysis import get_db
    app.dependency_overrides[get_db] = lambda: mock_db_session

    try:
        transport = httpx.ASGITransport(app=app)
        
        # Mock DB 查询 FinancialMetadata
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):

            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-exceed/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                data = res_json["data"]
                
                # 总成本 60000.0 > 最高限价 50000.0，超额 10000.0
                assert data["total_cost"] == 60000.0
                assert data["budget_numeric"] == 50000.0
                assert data["limit_type"] == "max_price_limit"
                assert "已超出最高投标限价" in data["budget_status"]
                assert "10,000.00" in data["budget_status"] or "10000" in data["budget_status"]
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_update_cost_analysis_with_section_name():
    """测试多区域/分标段场景下，section_name 字段的正确传递、自愈与持久化"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    payload = {
        "items": [
            {
                "name": "光伏组件 635Wp",
                "spec_requirement": "单晶硅正A级",
                "qty": 956,
                "unit": "块",
                "ref_price": 880.0,
                "section_name": "斜桥工业二区",
                "match_quality": "精准匹配"
            },
            {
                "name": "光伏组件 635Wp",
                "spec_requirement": "单晶硅正A级",
                "qty": 384,
                "unit": "块",
                "ref_price": 880.0,
                "section_name": "斜桥工业园区",
                "match_quality": "精准匹配"
            }
        ],
        "analysis_summary": "两区域光伏组件分项核算"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-section-1/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                data = res_json["data"]
                
                assert len(data["items"]) == 2
                assert data["items"][0]["section_name"] == "斜桥工业二区"
                assert data["items"][0]["qty"] == 956
                assert data["items"][1]["section_name"] == "斜桥工业园区"
                assert data["items"][1]["qty"] == 384
                # 956*880 + 384*880 = (956+384)*880 = 1340*880 = 1179200.0
                assert data["total_cost"] == 1179200.0
                
                saved_cost = mock_doc.parsed_metadata["cost_analysis"]
                assert saved_cost["items"][0]["section_name"] == "斜桥工业二区"
                assert saved_cost["items"][1]["section_name"] == "斜桥工业园区"
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_update_cost_analysis_hierarchical_rollup_for_parent_items():
    """测试多级 BOM 成套母项自底向上自动汇总子项总价、计算折合单价并防双重计费"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    # 模拟“导体和导线”成套主标的物及其下属 3 个子项（电缆、终端等）
    payload = {
        "items": [
            {
                "name": "导体和导线",
                "spec_requirement": "成套主标的物，含多规格电缆及终端",
                "qty": 1,
                "unit": "项",
                "ref_price": 0.0,
                "parent_item": None,
                "tree_level": 1,
                "match_quality": "未匹配"
            },
            {
                "name": "10kV交流电缆 3*300",
                "spec_requirement": "ZC-YJV22-8.7/15kV-3*300",
                "qty": 200,
                "unit": "米",
                "ref_price": 920.61,
                "parent_item": "导体和导线",
                "tree_level": 2,
                "match_quality": "手动修改"
            },
            {
                "name": "10kV交流电缆 3*70",
                "spec_requirement": "ZC-YJV22-8.7/15kV-3*70",
                "qty": 700,
                "unit": "米",
                "ref_price": 330.0,
                "parent_item": "导体和导线",
                "tree_level": 2,
                "match_quality": "手动修改"
            },
            {
                "name": "10kV交流电缆终端",
                "spec_requirement": "户内配合 3*300",
                "qty": 4,
                "unit": "套",
                "ref_price": 3650.0,
                "parent_item": "导体和导线",
                "tree_level": 2,
                "match_quality": "手动修改"
            }
        ],
        "analysis_summary": "已填写电缆及终端子项价格"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-rollup-1/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                data = res_json["data"]
                
                items = data["items"]
                # 子项金额计算：
                # 200 * 920.61 = 184122.0
                # 700 * 330.0 = 231000.0
                # 4 * 3650.0 = 14600.0
                # 汇总 = 184122.0 + 231000.0 + 14600.0 = 429722.0
                expected_rollup_subtotal = 429722.0
                
                # 验证母项“导体和导线”自动获得了子项汇总小计与折算单价
                parent_node = items[0]
                assert parent_node["name"] == "导体和导线"
                assert parent_node["subtotal"] == expected_rollup_subtotal
                assert parent_node["ref_price"] == expected_rollup_subtotal  # qty=1 时单价等于小计
                assert parent_node["match_quality"] == "成套汇总"
                
                # 验证预估总成本（严格等于母项根节点金额，不重复计费）
                assert data["total_cost"] == expected_rollup_subtotal
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_update_cost_analysis_with_custom_brand_model_should_persist_fields():
    """测试手动更新与新增分项时，品牌、规格型号、生产厂家字段能够正确解析并持久化落盘"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    payload = {
        "items": [
            {
                "name": "组串式逆变器",
                "spec_requirement": "110kW 组串式逆变器",
                "qty": 5,
                "unit": "台",
                "ref_price": 28000.0,
                "matched_name": "组串式逆变器",
                "matched_brand": "华为",
                "matched_model": "SUN2000-110KTL",
                "matched_manufacturer": "华为技术有限公司",
                "match_quality": "手动修改"
            },
            {
                "name": "深化设计+屋面承载力验算",
                "spec_requirement": "具备电力、结构双资质设计院出具",
                "qty": 1,
                "unit": "项",
                "ref_price": 16000.0,
                "brand": "自定义",
                "model": "标准验算服务",
                "manufacturer": "某建筑设计研究院",
                "match_quality": "手动添加"
            }
        ],
        "analysis_summary": "已补充品牌、型号与生产厂家信息。"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-brand-model/cost-analysis", json=payload)
                
                assert res.status_code == 200
                res_json = res.json()
                data = res_json["data"]
                
                # 验证返回的数据结构包含正确的品牌、型号与厂商
                items = data["items"]
                assert len(items) == 2
                
                assert items[0]["matched_brand"] == "华为"
                assert items[0]["matched_model"] == "SUN2000-110KTL"
                assert items[0]["matched_manufacturer"] == "华为技术有限公司"
                
                assert items[1]["matched_brand"] == "自定义"
                assert items[1]["matched_model"] == "标准验算服务"
                assert items[1]["matched_manufacturer"] == "某建筑设计研究院"
                
                # 验证 mock_doc 中的 parsed_metadata 正确持久化
                saved_cost = mock_doc.parsed_metadata["cost_analysis"]
                saved_items = saved_cost["items"]
                assert saved_items[0]["matched_brand"] == "华为"
                assert saved_items[0]["matched_model"] == "SUN2000-110KTL"
                assert saved_items[0]["matched_manufacturer"] == "华为技术有限公司"
                assert saved_items[1]["matched_brand"] == "自定义"
                assert saved_items[1]["matched_model"] == "标准验算服务"
                assert saved_items[1]["matched_manufacturer"] == "某建筑设计研究院"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_cost_analysis_with_legacy_structured_key_parameter_should_succeed():
    """测试历史 {type,input} 关键参数与空单位不会再导致成本保存接口 422。"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}
    payload = {
        "items": [{
            "name": "并网柜",
            "unit": None,
            "qty": 1,
            "ref_price": 100,
            "key_parameters": [{"type": "text", "input": "10kV"}],
            "match_quality": "精准匹配"
        }]
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-legacy-cost/cost-analysis", json=payload)

        assert res.status_code == 200
        data = res.json()["data"]
        assert data["items"][0]["key_parameters"] == ["10kV"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_cost_analysis_parent_custom_pricing_priority_over_children():
    """测试当父项被用户自定义修改（is_parent_modified=True 或 pricing_mode='parent'）时，父项自身单价与小计优先，不再被子项求和覆盖"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    payload = {
        "items": [
            {
                "name": "高压开关柜成套设备",
                "spec_requirement": "KYN28A-12 包含进线柜/出线柜/PT柜",
                "qty": 2,
                "unit": "面",
                "ref_price": 50000.0,  # 用户手动设定的整套单价 50,000 元
                "is_parent_modified": True,
                "pricing_mode": "parent",
                "match_quality": "手动修改"
            },
            {
                "name": "真空断路器",
                "spec_requirement": "VS1-12/1250-31.5",
                "qty": 2,
                "unit": "台",
                "ref_price": 12000.0,  # 子项小计 24,000
                "parent_item": "高压开关柜成套设备",
                "tree_level": 2,
                "match_quality": "精准匹配"
            },
            {
                "name": "微机保护装置",
                "spec_requirement": "线路保护测控",
                "qty": 2,
                "unit": "台",
                "ref_price": 8000.0,  # 子项小计 16,000
                "parent_item": "高压开关柜成套设备",
                "tree_level": 2,
                "match_quality": "精准匹配"
            }
        ],
        "analysis_summary": "用户直接指定成套设备整套单价 50000 元/面"
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-parent-custom-1/cost-analysis", json=payload)

        assert res.status_code == 200
        data = res.json()["data"]
        items = data["items"]

        # 验证母项保留了用户自定义的单价 50000 和小计 100000（2 * 50000），没有被子项求和（40000）覆盖
        parent_node = items[0]
        assert parent_node["name"] == "高压开关柜成套设备"
        assert parent_node["ref_price"] == 50000.0
        assert parent_node["subtotal"] == 100000.0
        assert parent_node["is_parent_modified"] is True
        assert parent_node["pricing_mode"] == "parent"

        # 验证预估总成本严格以母项 100000.0 为准
        assert data["total_cost"] == 100000.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_cost_analysis_with_raw_baseline_and_mutex_fields_persistence():
    """测试基线快照（raw_...）及互斥标记（is_parent_modified, is_child_modified, is_custom_added）正确落盘与回传"""
    mock_user = MagicMock()
    mock_user.id = "user-test-999"
    mock_user.tenant_id = "tenant-test-888"
    app.dependency_overrides[get_current_active_user] = lambda: mock_user

    mock_doc = MagicMock()
    mock_doc.project_id = "proj-123"
    mock_doc.parsed_metadata = {}

    payload = {
        "items": [
            {
                "name": "箱式变电站",
                "spec_requirement": "YBM-12/0.4-630kVA",
                "qty": 1,
                "unit": "台",
                "ref_price": 180000.0,
                "is_parent_modified": False,
                "is_child_modified": True,
                "is_custom_added": False,
                "pricing_mode": "children",
                "raw_ref_price": 160000.0,
                "raw_name": "预装式变电站",
                "raw_brand": "特变电工",
                "raw_model": "YBM-630",
                "raw_manufacturer": "特变电工股份有限公司",
                "raw_spec": "YBM-12/0.4-630kVA 初始标书要求",
                "raw_qty": 1,
                "raw_unit": "台",
                "raw_match_quality": "精准匹配"
            },
            {
                "name": "智能温控排风系统",
                "spec_requirement": "带双路风机与温度自启动",
                "qty": 2,
                "unit": "套",
                "ref_price": 3500.0,
                "parent_item": "箱式变电站",
                "is_custom_added": True,
                "is_child_modified": True,
                "raw_ref_price": 0.0,
                "raw_name": "智能温控排风系统"
            }
        ]
    }

    try:
        transport = httpx.ASGITransport(app=app)
        with patch("app.db.crud.document.document_crud.get_document_by_id", return_value=mock_doc), \
             patch("sqlalchemy.orm.attributes.flag_modified"):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
                res = await ac.put("/api/v1/analysis/doc-baseline-1/cost-analysis", json=payload)

        assert res.status_code == 200
        data = res.json()["data"]
        items = data["items"]

        parent_item = items[0]
        assert parent_item["raw_brand"] == "特变电工"
        assert parent_item["raw_model"] == "YBM-630"
        assert parent_item["raw_ref_price"] == 160000.0
        assert parent_item["is_child_modified"] is True
        assert parent_item["pricing_mode"] == "children"

        child_item = items[1]
        assert child_item["is_custom_added"] is True
        assert child_item["is_child_modified"] is True
        assert child_item["parent_item"] == "箱式变电站"
    finally:
        app.dependency_overrides.clear()



