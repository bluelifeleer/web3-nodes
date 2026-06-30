import os


STORAGE_SHARE_MODE = "storage_share"
PCDN_PARTNER_MODE = "pcdn_partner"
SUPPORTED_BUSINESS_MODES = {STORAGE_SHARE_MODE, PCDN_PARTNER_MODE}


def normalize_business_mode(value=""):
    raw = str(value or "").split("#", 1)[0].strip().lower().replace("-", "_")
    if raw in ("pcdn", "pcdn_partner", "partner_pcdn"):
        return PCDN_PARTNER_MODE
    if raw in SUPPORTED_BUSINESS_MODES:
        return raw
    return STORAGE_SHARE_MODE


def normalize_pcdn_provider(value=""):
    raw = str(value or "").split("#", 1)[0].strip().lower().replace("_", "-")
    return raw or "mock"


def current_business_mode(environ=os.environ):
    return normalize_business_mode(environ.get("BUSINESS_MODE", STORAGE_SHARE_MODE))


def current_pcdn_provider(environ=os.environ):
    return normalize_pcdn_provider(environ.get("PCDN_PROVIDER", "mock"))


def business_mode_is_pcdn(mode):
    return normalize_business_mode(mode) == PCDN_PARTNER_MODE
