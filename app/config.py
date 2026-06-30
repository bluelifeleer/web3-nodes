import os
from dataclasses import dataclass

from app.services.business import current_business_mode, current_pcdn_provider


@dataclass(frozen=True)
class ServerConfig:
    admin_api_token: str
    session_secret: str | None
    max_upload_bytes: int
    amap_web_key: str
    amap_security_jscode: str
    business_mode: str
    pcdn_provider: str

    @classmethod
    def from_env(cls, environ=os.environ):
        return cls(
            admin_api_token=environ.get("ADMIN_API_TOKEN", ""),
            session_secret=environ.get("SESSION_SECRET"),
            max_upload_bytes=int(environ.get("MAX_UPLOAD_MB", "100")) * 1024 * 1024,
            amap_web_key=environ.get("AMAP_WEB_KEY", "").strip(),
            amap_security_jscode=environ.get("AMAP_SECURITY_JSCODE", "").strip(),
            business_mode=current_business_mode(environ),
            pcdn_provider=current_pcdn_provider(environ),
        )
