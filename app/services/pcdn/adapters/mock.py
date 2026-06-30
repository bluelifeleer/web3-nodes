from datetime import datetime, timedelta

from app.services.pcdn.adapters.base import PcdnAdapter


class MockPcdnAdapter(PcdnAdapter):
    provider_name = "mock"

    def list_resources(self):
        return [{
            "provider": self.provider_name,
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "status": "active",
            "cache_hit_rate": 0.91,
        }]

    def create_task(self, task):
        task_name = str(task.get("task_name") or "demo").strip() or "demo"
        resource_url = str(task.get("resource_url") or "https://mock.example.com/video.mp4").strip()
        return {
            "provider": self.provider_name,
            "vendor_task_id": f"mock-task-{task_name}",
            "task_name": task_name,
            "resource_url": resource_url,
            "domain": resource_url.split("/")[2] if "://" in resource_url else "",
            "status": "running",
        }

    def get_task(self, task_id):
        return {
            "provider": self.provider_name,
            "vendor_task_id": str(task_id or "mock-task-demo"),
            "task_name": "demo",
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "status": "running",
        }

    def sync_usage(self, since=None, until=None):
        ended_at = datetime.now().replace(microsecond=0)
        started_at = ended_at - timedelta(minutes=60)
        return [{
            "provider": self.provider_name,
            "vendor_task_id": "mock-task-demo",
            "node_address": "MOCK_NODE_A",
            "resource_url": "https://mock.example.com/video.mp4",
            "domain": "mock.example.com",
            "bandwidth_mbps": 12.5,
            "traffic_gb": 18.75,
            "online_minutes": 60,
            "cache_hit_rate": 0.91,
            "started_at": started_at.isoformat(sep=" "),
            "ended_at": ended_at.isoformat(sep=" "),
            "raw_payload_json": '{"mock":true}',
        }]

    def health(self):
        return {
            "provider": self.provider_name,
            "online": True,
            "status": "ok",
            "message": "mock adapter ready",
        }
