import json

from app.services.business import business_mode_is_pcdn
from app.services.pcdn.adapters.registry import get_pcdn_adapter


def adapter_for_config(server_config):
    return get_pcdn_adapter(getattr(server_config, "pcdn_provider", "mock"))


def pcdn_status(server_config):
    adapter = adapter_for_config(server_config)
    health = adapter.health()
    return {
        "business_mode": getattr(server_config, "business_mode", "storage_share"),
        "pcdn_enabled": business_mode_is_pcdn(getattr(server_config, "business_mode", "")),
        "provider": adapter.provider_name,
        "adapter": health,
        "resources": adapter.list_resources(),
    }


def list_tasks(server_config):
    adapter = adapter_for_config(server_config)
    return [adapter.get_task("mock-task-demo")]


def create_task(server_config, payload):
    adapter = adapter_for_config(server_config)
    return adapter.create_task(payload or {})


def sync_usage(server_config):
    adapter = adapter_for_config(server_config)
    metrics = adapter.sync_usage()
    return {
        "provider": adapter.provider_name,
        "metrics": metrics,
        "sync_log": {
            "provider": adapter.provider_name,
            "sync_type": "usage",
            "status": "ok",
            "message": "mock PCDN usage synced",
            "raw_summary_json": json.dumps({"metric_count": len(metrics)}, ensure_ascii=False),
        },
    }


def build_settlements_from_metrics(metrics):
    settlements = []
    for item in metrics or []:
        traffic = float(item.get("traffic_gb") or 0)
        bandwidth = float(item.get("bandwidth_mbps") or 0)
        online = float(item.get("online_minutes") or 0)
        hit_rate = float(item.get("cache_hit_rate") or 0)
        score = round(traffic * 1.0 + bandwidth * 0.2 + online * 0.05 + hit_rate * 10, 4)
        amount = round(score * 0.01, 4)
        settlements.append({
            "provider": item.get("provider") or "mock",
            "vendor_task_id": item.get("vendor_task_id") or "",
            "node_address": item.get("node_address") or "",
            "metric_window": f"{item.get('started_at') or ''} - {item.get('ended_at') or ''}".strip(),
            "contribution_score": score,
            "amount": amount,
            "status": "settled",
        })
    return settlements


def run_settlement(server_config):
    adapter = adapter_for_config(server_config)
    metrics = adapter.sync_usage()
    return {
        "provider": adapter.provider_name,
        "settlements": build_settlements_from_metrics(metrics),
    }
