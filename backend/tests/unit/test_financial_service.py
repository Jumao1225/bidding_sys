from app.services.metadata.financial_service import (
    FinancialSchema,
    MoneyAmount,
    reconcile_core_financial_amounts,
)


def test_reconcile_core_financial_amounts_should_keep_budget_and_limit_separate():
    """明确采购预算与最高限价不同时，应按各自原文金额覆盖模型混填结果。"""
    result = FinancialSchema(
        budget=MoneyAmount(amount=1181380.0),
        max_price_limit=MoneyAmount(amount=1181380.0),
    )
    context = """
    预算金额：1181380元
    最高限价：1181380元
    本项目采购预算为¥1350000.00元。投标总价不得超过采购预算。
    """

    reconciled = reconcile_core_financial_amounts(result, context)

    assert reconciled.budget is not None
    assert reconciled.budget.amount == 1350000.0
    assert reconciled.max_price_limit is not None
    assert reconciled.max_price_limit.amount == 1181380.0


def test_reconcile_core_financial_amounts_should_not_infer_limit_from_budget():
    """原文只有采购预算时，不得推导或伪造最高投标限价。"""
    result = FinancialSchema()

    reconciled = reconcile_core_financial_amounts(result, "本项目采购预算为 1350000 元。")

    assert reconciled.budget is not None
    assert reconciled.budget.amount == 1350000.0
    assert reconciled.max_price_limit is None


def test_reconcile_core_financial_amounts_should_keep_model_value_for_invalid_amount():
    """原文金额无法解析时，应保留模型已有值，避免错误覆盖。"""
    result = FinancialSchema(budget=MoneyAmount(amount=980000.0))

    reconciled = reconcile_core_financial_amounts(result, "本项目采购预算为人民币若干元。")

    assert reconciled.budget is not None
    assert reconciled.budget.amount == 980000.0
