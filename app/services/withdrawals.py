from decimal import Decimal, InvalidOperation


VALID_WITHDRAWAL_STATUSES = {"pending", "approved", "rejected", "paid"}
MIN_WITHDRAWAL_AMOUNT = Decimal("0.000001")
VALID_REVIEW_TARGET_STATUSES = {"approved", "rejected", "paid"}
VALID_STATUS_TRANSITIONS = {
    "pending": {"approved", "rejected"},
    "approved": {"paid", "rejected"},
    "rejected": set(),
    "paid": set(),
}


def parse_withdrawal_amount(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None, "提现金额格式错误"
    if not value.is_finite():
        return None, "提现金额格式错误"
    if value <= 0:
        return None, "提现金额必须大于0"
    if value < MIN_WITHDRAWAL_AMOUNT:
        return None, "提现金额不能小于0.000001"
    return value.quantize(MIN_WITHDRAWAL_AMOUNT), "ok"


def validate_withdrawal_amount(amount):
    value, message = parse_withdrawal_amount(amount)
    if value is None:
        return False, message
    return True, "ok"


def format_withdrawal_amount(amount):
    return format(amount, "f")


def validate_review_status(status):
    if status not in VALID_WITHDRAWAL_STATUSES:
        return False, "提现状态无效"
    return True, "ok"


def validate_status_transition(current_status, target_status):
    current = str(current_status or "").strip().lower()
    target = str(target_status or "").strip().lower()
    ok, message = validate_review_status(target)
    if not ok:
        return False, message
    if target not in VALID_REVIEW_TARGET_STATUSES:
        return False, f"不能将提现审核为 {target}"
    if current not in VALID_WITHDRAWAL_STATUSES:
        return False, "当前提现状态无效"
    if target not in VALID_STATUS_TRANSITIONS[current]:
        return False, f"提现状态不可从 {current} 变更为 {target}"
    return True, "ok"
