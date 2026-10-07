"""Server-only configuration. Nothing here initiates a network request."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    access_password: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    live_calls_enabled: bool = False
    max_output_tokens: int = 2048
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            api_key=os.environ.get("BAZE_API_KEY", "").strip(),
            access_password=os.environ.get("LAB_ACCESS_PASSWORD", ""),
            model=os.environ.get("BAZE_MODEL", DEFAULT_MODEL).strip(),
            live_calls_enabled=os.environ.get("LLM_CALLS_ENABLED", "false").lower() == "true",
        )

    def blocked_reasons(self) -> list[str]:
        reasons = []
        if not self.live_calls_enabled:
            reasons.append("실제 모델 호출이 비활성화되어 있습니다.")
        if not self.api_key:
            reasons.append("서버에 BAZE_API_KEY를 설정해 주세요.")
        if not self.model:
            reasons.append("서버에 BAZE_MODEL을 설정해 주세요.")
        return reasons
