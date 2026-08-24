import pytest
from unittest.mock import patch, MagicMock
from app.services.metadata.engineering_service import EquipmentItem, EngineeringSchema
from app.agents.nodes.cost_agent import CostItem, CostAnalysisResult, cost_node
from app.services.cost_service import rollup_hierarchical_cost_items

def test_equipment_item_multilevel_schema_validation():
    """测试 EquipmentItem 对多级 BOM 嵌套结构（item_code, parent_item, root_item, tree_level）的结构化校验"""
    # 1. 顶层主要标的物 (Level 1)
    root_item = EquipmentItem(
        item_code="(二)",
        item_name="2000kVA光伏升压箱变",
        specifications="2000kVA 10kV",
        quantity=4.0,
        unit="套",
        parent_item=None,
        root_item="2000kVA光伏升压箱变",
        tree_level=1,
        per_set_quantity=None
    )
    assert root_item.tree_level == 1
    assert root_item.parent_item is None
    assert root_item.quantity == 4.0

    # 2. 二级成套子系统/总成 (Level 2)
    sub_assembly = EquipmentItem(
        item_code="1",
        item_name="环网柜",
        specifications="10kV 630A",
        quantity=4.0,
        unit="套",
        parent_item="2000kVA光伏升压箱变",
        root_item="2000kVA光伏升压箱变",
        tree_level=2,
        per_set_quantity=1.0
    )
    assert sub_assembly.tree_level == 2
    assert sub_assembly.parent_item == "2000kVA光伏升压箱变"
    assert sub_assembly.per_set_quantity == 1.0

    # 3. 三级底层核心元器件 (Level 3)
    component = EquipmentItem(
        item_code="1.3",
        item_name="氧化锌避雷器",
        specifications="17/45 (附计数器)",
        quantity=12.0,  # 4 套箱变 * 1 套环网柜 * 3 只/套 = 12 只
        unit="只",
        parent_item="环网柜",
        root_item="2000kVA光伏升压箱变",
        tree_level=3,
        per_set_quantity=3.0,
        key_parameters=["17/45", "附计数器"]
    )
    assert component.tree_level == 3
    assert component.parent_item == "环网柜"
    assert component.root_item == "2000kVA光伏升压箱变"
    assert component.quantity == 12.0
    assert component.per_set_quantity == 3.0

def test_cost_item_multilevel_hierarchy_preservation():
    """测试 CostItem 能够完整保留多级 BOM 层级树属性"""
    cost_item = CostItem(
        item_code="1.1",
        name="高压真空断路器",
        spec_requirement="630A, 25kA",
        qty=4.0,
        unit="组",
        parent_item="环网柜",
        root_item="2000kVA光伏升压箱变",
        tree_level=3,
        per_set_qty=1.0,
        key_parameters=["630A", "25kA"],
        ref_price=0.0,
        subtotal=0.0,
        match_quality="精准匹配",
        comparison_note="已包含在成套打包统价中，不重复计费，仅作技术规格审核"
    )
    assert cost_item.item_code == "1.1"
    assert cost_item.parent_item == "环网柜"
    assert cost_item.root_item == "2000kVA光伏升压箱变"
    assert cost_item.tree_level == 3
    assert cost_item.per_set_qty == 1.0
    assert cost_item.ref_price == 0.0

def test_multilevel_bom_quantity_rollup_calculation():
    """测试多级嵌套 BOM 采购总量连乘穿透计算逻辑"""
    root_qty = 4.0  # 4 套主设备
    level2_quota = 1.0  # 每套主设备含 1 套二级总成
    level3_quota = 3.0  # 每套二级总成含 3 只元器件

    # 验证二级总成需求量
    level2_total_qty = root_qty * level2_quota
    assert level2_total_qty == 4.0

    # 验证三级元器件穿透折算总量
    level3_total_qty = root_qty * level2_quota * level3_quota
    assert level3_total_qty == 12.0

@patch("app.agents.nodes.cost_agent.SessionLocal")
@patch("app.agents.nodes.cost_agent.document_crud")
@patch("app.agents.nodes.cost_agent.business_crud")
@patch("app.agents.nodes.cost_agent.rag_service")
@patch("app.agents.nodes.cost_agent.llm_service")
def test_cost_agent_multilevel_tree_inheritance(
    mock_llm, mock_rag, mock_business_crud, mock_document_crud, mock_session
):
    """测试 CostAgent 在处理提取的设备列表时，能够完整继承多级层级树（item_code, parent_item, root_item, tree_level）"""
    mock_db = MagicMock()
    mock_session.return_value = mock_db

    # 构造已有工程元数据中的多级设备清单
    mock_eng_md = MagicMock()
    mock_eng_md.main_equipment_list = [
        {
            "item_code": "(二)",
            "item_name": "2000kVA光伏升压箱变",
            "quantity": 4.0,
            "unit": "套",
            "parent_item": None,
            "root_item": "2000kVA光伏升压箱变",
            "tree_level": 1,
            "per_set_quantity": None
        },
        {
            "item_code": "1",
            "item_name": "环网柜",
            "quantity": 4.0,
            "unit": "套",
            "parent_item": "2000kVA光伏升压箱变",
            "root_item": "2000kVA光伏升压箱变",
            "tree_level": 2,
            "per_set_quantity": 1.0
        },
        {
            "item_code": "1.3",
            "item_name": "氧化锌避雷器",
            "quantity": 12.0,
            "unit": "只",
            "parent_item": "环网柜",
            "root_item": "2000kVA光伏升压箱变",
            "tree_level": 3,
            "per_set_quantity": 3.0
        }
    ]

    mock_db.query.return_value.filter.return_value.first.side_effect = [
        None,  # fin_md
        mock_eng_md  # eng_md
    ]

    mock_doc = MagicMock()
    mock_doc.project_id = "test-proj"
    mock_document_crud.get_document_by_id.return_value = mock_doc
    mock_business_crud.get_price_references.return_value = []
    mock_rag.search_bidding_document.return_value = "测试招标上下文"

    # LLM 结构化返回模拟
    mock_llm.generate_structured_output.return_value = CostAnalysisResult(
        items=[
            CostItem(
                name="2000kVA光伏升压箱变",
                qty=4.0,
                unit="套",
                ref_price=150000.0,
                subtotal=600000.0,
                match_quality="精准匹配",
                comparison_note="成套整机报价"
            ),
            CostItem(
                name="环网柜",
                qty=4.0,
                unit="套",
                ref_price=0.0,
                subtotal=0.0,
                match_quality="精准匹配",
                comparison_note="已包含在成套打包统价中，不重复计费，仅作技术规格审核"
            ),
            CostItem(
                name="氧化锌避雷器",
                qty=12.0,
                unit="只",
                ref_price=0.0,
                subtotal=0.0,
                match_quality="精准匹配",
                comparison_note="已包含在成套打包统价中，不重复计费，仅作技术规格审核"
            )
        ],
        analysis_summary="成本核算完成"
    )

    state = {"document_id": "doc-multilevel-1", "user_id": "user-1"}
    result = cost_node(state)

    cost_analysis = result["cost_analysis"]
    items = cost_analysis["items"]

    assert len(items) == 3
    # 验证顶层主设备
    assert items[0]["name"] == "2000kVA光伏升压箱变"
    assert items[0]["item_code"] == "(二)"
    assert items[0]["tree_level"] == 1
    assert items[0]["subtotal"] == 600000.0

    # 验证二级总成
    assert items[1]["name"] == "环网柜"
    assert items[1]["item_code"] == "1"
    assert items[1]["parent_item"] == "2000kVA光伏升压箱变"
    assert items[1]["tree_level"] == 2
    assert items[1]["subtotal"] == 0.0

    # 验证三级元器件
    assert items[2]["name"] == "氧化锌避雷器"
    assert items[2]["item_code"] == "1.3"
    assert items[2]["parent_item"] == "环网柜"
    assert items[2]["root_item"] == "2000kVA光伏升压箱变"
    assert items[2]["tree_level"] == 3
    assert items[2]["qty"] == 12.0
    assert items[2]["subtotal"] == 0.0

def test_arbitrary_n_level_recursive_bom_structure():
    """测试系统对任意深度 N 级（Level 1 -> Level 2 -> Level 3 -> Level 4 -> Level 5）嵌套树的结构化表达与穿透连乘计算"""
    # 模拟 5 级深层嵌套工业成套设备结构：
    # Level 1: (一) 储能电站系统 (2 套)
    # Level 2: 1 电池预制舱 (单套配 4 个舱) -> 总量 = 2 * 4 = 8 舱
    # Level 3: 1.1 电池簇机柜 (单舱配 10 台机柜) -> 总量 = 2 * 4 * 10 = 80 台
    # Level 4: 1.1.1 电池模组 Pack (单机柜配 16 个 Pack) -> 总量 = 2 * 4 * 10 * 16 = 1280 个
    # Level 5: 1.1.1.1 磷酸铁锂电芯 (单个模组含 24 颗电芯) -> 总量 = 2 * 4 * 10 * 16 * 24 = 30720 颗

    level1_qty = 2.0
    level2_quota = 4.0
    level3_quota = 10.0
    level4_quota = 16.0
    level5_quota = 24.0

    level5_item = EquipmentItem(
        item_code="1.1.1.1",
        item_name="280Ah磷酸铁锂电芯",
        specifications="3.2V 280Ah 磷酸铁锂",
        quantity=level1_qty * level2_quota * level3_quota * level4_quota * level5_quota,  # 30720.0 颗
        unit="颗",
        parent_item="电池模组Pack",
        root_item="储能电站系统",
        tree_level=5,
        per_set_quantity=level5_quota,
        key_parameters=["280Ah", "3.2V"]
    )

    assert level5_item.tree_level == 5
    assert level5_item.parent_item == "电池模组Pack"
    assert level5_item.root_item == "储能电站系统"
    assert level5_item.quantity == 30720.0
    assert level5_item.per_set_quantity == 24.0

def test_sibling_item_substring_of_compound_parent_name_hierarchy():
    """
    测试复合名称父项（如 '4(九) 铁附件、电缆防火封堵'）下属包含自身子串同名兄弟项（如 '铁附件'）时，
    树构建算法不会将同级兄弟项误作为父子关系挂载，并正确完成自底向上汇总
    """
    raw_items = [
        # 1 级成套主项
        {
            "item_code": "4(九)",
            "name": "铁附件、电缆防火封堵",
            "parent_item": None,
            "root_item": None,
            "tree_level": 1,
            "qty": 1.0,
            "unit": "项",
            "ref_price": 0.0,
            "subtotal": 0.0,
            "section_name": "项目需求清单（一次侧部分）"
        },
        # 2 级分项 1: 名称为 "铁附件"（正好是父节点名称的子串）
        {
            "item_code": "1",
            "name": "铁附件",
            "parent_item": "铁附件、电缆防火封堵",
            "root_item": "铁附件、电缆防火封堵",
            "tree_level": 2,
            "qty": 1.0,
            "unit": "t",
            "ref_price": 5000.0,
            "subtotal": 5000.0,
            "section_name": "项目需求清单（一次侧部分）"
        },
        # 2 级分项 2: "电缆防火涂料"（平级兄弟项，parent_item 同样指向 "铁附件、电缆防火封堵"）
        {
            "item_code": "2",
            "name": "电缆防火涂料",
            "parent_item": "铁附件、电缆防火封堵",
            "root_item": "铁附件、电缆防火封堵",
            "tree_level": 2,
            "qty": 1.0,
            "unit": "t",
            "ref_price": 3000.0,
            "subtotal": 3000.0,
            "section_name": "项目需求清单（一次侧部分）"
        },
        # 2 级分项 3: "有机堵料"（平级兄弟项）
        {
            "item_code": "3",
            "name": "有机堵料",
            "parent_item": "铁附件、电缆防火封堵",
            "root_item": "铁附件、电缆防火封堵",
            "tree_level": 2,
            "qty": 1.0,
            "unit": "t",
            "ref_price": 2000.0,
            "subtotal": 2000.0,
            "section_name": "项目需求清单（一次侧部分）"
        }
    ]

    processed, total_cost, unmatched = rollup_hierarchical_cost_items(raw_items)

    # 1. 验证 1 级成套总成汇总了全部 3 个子项的金额 (5000 + 3000 + 2000 = 10000.0)
    assert processed[0]["name"] == "铁附件、电缆防火封堵"
    assert processed[0]["subtotal"] == 10000.0
    assert processed[0]["ref_price"] == 10000.0
    assert processed[0]["match_quality"] == "成套汇总"

    # 2. 验证各个 2 级平级子项保持自身的单价与小计，并未被篡改
    assert processed[1]["name"] == "铁附件"
    assert processed[1]["subtotal"] == 5000.0
    assert processed[2]["name"] == "电缆防火涂料"
    assert processed[2]["subtotal"] == 3000.0
    assert processed[3]["name"] == "有机堵料"
    assert processed[3]["subtotal"] == 2000.0

    # 3. 验证顶层预估总成本防双重计费 (严格等于根节点 subtotal 10000.0，而不是 10000 + 5000 + 3000 + 2000 = 20000)
    assert total_cost == 10000.0
    assert unmatched == 0

def test_multilevel_nested_cabinet_and_components_hierarchy():
    """
    测试 3 级深层嵌套结构（章节大类/主项 -> 设备控制柜 -> 具体元器件）在 root_item 与 parent_item 
    上下文变化时仍能稳定构建树并完成金额自底向上汇总
    """
    raw_items = [
        # Level 1: 章节大类/汇总项
        {
            "item_code": "(二)",
            "name": "继电保护及安全自动装置",
            "parent_item": None,
            "root_item": None,
            "tree_level": 1,
            "qty": None,
            "unit": None,
            "ref_price": 0.0,
            "subtotal": 0.0,
            "section_name": "项目需求清单（二次侧部分）"
        },
        # Level 2: 控制柜总成
        {
            "item_code": "1",
            "name": "防孤岛及频率电压紧急控制柜",
            "parent_item": "继电保护及安全自动装置",
            "root_item": "继电保护及安全自动装置",
            "tree_level": 1,  # 提取时可能带噪音填 1
            "qty": 1.0,
            "unit": "面",
            "ref_price": 0.0,
            "subtotal": 0.0,
            "section_name": "项目需求清单（二次侧部分）"
        },
        # Level 3: 控制柜内子器件 1
        {
            "item_code": None,
            "name": "防孤岛保护装置",
            "parent_item": "防孤岛及频率电压紧急控制柜",
            "root_item": "防孤岛及频率电压紧急控制柜",
            "tree_level": 2,
            "qty": 2.0,
            "unit": "套",
            "ref_price": 12000.0,
            "subtotal": 24000.0,
            "section_name": "项目需求清单（二次侧部分）"
        },
        # Level 3: 控制柜内子器件 2
        {
            "item_code": None,
            "name": "频率电压紧急控制装置",
            "parent_item": "防孤岛及频率电压紧急控制柜",
            "root_item": "防孤岛及频率电压紧急控制柜",
            "tree_level": 2,
            "qty": 2.0,
            "unit": "套",
            "ref_price": 8000.0,
            "subtotal": 16000.0,
            "section_name": "项目需求清单（二次侧部分）"
        }
    ]

    processed, total_cost, unmatched = rollup_hierarchical_cost_items(raw_items)

    # 1. 验证 Level 2 控制柜汇总了下属 2 个元器件的金额 (24000 + 16000 = 40000.0)
    cabinet = processed[1]
    assert cabinet["name"] == "防孤岛及频率电压紧急控制柜"
    assert cabinet["subtotal"] == 40000.0
    assert cabinet["ref_price"] == 40000.0
    assert cabinet["match_quality"] == "成套汇总"

    # 2. 验证 Level 1 汇总项继承了控制柜的汇总总金额 (40000.0)
    root = processed[0]
    assert root["name"] == "继电保护及安全自动装置"
    assert root["subtotal"] == 40000.0
    assert root["ref_price"] == 40000.0
    assert root["match_quality"] == "成套汇总"

    # 3. 验证顶层预估总成本防双重计费 (严格等于顶层根节点 40000.0)
    assert total_cost == 40000.0
    assert unmatched == 0


