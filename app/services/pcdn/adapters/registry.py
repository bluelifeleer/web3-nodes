from app.services.business import normalize_pcdn_provider
from app.services.pcdn.adapters.mock import MockPcdnAdapter


def get_pcdn_adapter(provider="mock"):
    normalized = normalize_pcdn_provider(provider)
    if normalized == "mock":
        return MockPcdnAdapter()
    return MockPcdnAdapter()
