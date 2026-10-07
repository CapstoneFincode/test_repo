"""Minimal OpenAI-compatible BAZE adapter; no tools, retries, or fallback model."""

import time
from typing import Any

import httpx

from .config import GATEWAY_BASE_URL, Settings
from .prompts import PROMPT_VERSION, build_prompt
from .schemas import EmailInput


class GatewayError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class Gateway:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def summarize(self, email: EmailInput) -> dict[str, Any]:
        # Enforce the switch here as well as in the HTTP endpoint.
        reasons = self.settings.blocked_reasons()
        if reasons:
            raise GatewayError(503, " ".join(reasons))

        payload = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": build_prompt(email)}],
            "stream": False,
            "temperature": 0,
            "max_tokens": self.settings.max_output_tokens,
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(self.settings.timeout_seconds, connect=10),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{GATEWAY_BASE_URL}/chat/completions/",
                    headers={"Authorization": f"Bearer {self.settings.api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise GatewayError(504, "모델 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from None
        except httpx.RequestError:
            raise GatewayError(502, "모델 서버에 연결하지 못했습니다.") from None

        # Never echo upstream error bodies, credentials, or email content.
        if response.status_code in (401, 403):
            raise GatewayError(502, "BAZE 인증 또는 모델 접근 권한을 확인해 주세요.")
        if response.status_code == 429:
            raise GatewayError(429, "BAZE 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.")
        if response.status_code in (400, 404):
            raise GatewayError(502, "BAZE 모델 ID와 요청 설정을 확인해 주세요.")
        if response.status_code != 200:
            raise GatewayError(502, "모델 서버에서 요청을 처리하지 못했습니다.")

        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                raise GatewayError(502, "출력 토큰 한도에 도달했습니다. 본문을 줄이거나 서버의 출력 예산을 조정해 주세요.")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("No text content")
            raw_usage = data.get("usage") or {}
            # Only expose numeric usage, never arbitrary upstream fields.
            usage = {
                key: raw_usage[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(raw_usage, dict) and type(raw_usage.get(key)) is int
            }
        except (ValueError, KeyError, IndexError, TypeError):
            raise GatewayError(502, "사용 가능한 텍스트 요약을 받지 못했습니다.") from None

        return {
            "summary": content,
            "model": self.settings.model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": usage or None,
            "prompt_version": PROMPT_VERSION,
        }
