VALID_WITHDRAWAL_STATUSES = {"pending", "approved", "rejected", "paid"}


def validate_withdrawal_amount(amount):
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False, "提现金额格式错误"
    if value <= 0:
        return False, "提现金额必须大于0"
    return True, "ok"


def validate_review_status(status):
    if status not in VALID_WITHDRAWAL_STATUSES:
        return False, "提现状态无效"
    return True, "ok"
