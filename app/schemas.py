from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=20_000)

    @field_validator("body")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("이메일 본문을 입력해 주세요.")
        # Preserve the exact attacker-controlled text for reproducible experiments.
        return value
