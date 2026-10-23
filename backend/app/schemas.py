"""Request validation for the API (Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["http", "tcp", "ping"]
    url: str | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    interval_s: int = Field(default=30, ge=5, le=3600)
    timeout_s: float = Field(default=5.0, gt=0, le=30)
    expected_status: int | None = Field(default=None, ge=100, le=599)
    enabled: bool = True

    @field_validator("name", "url", "host", mode="before")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def check_address(self) -> "TargetIn":
        if self.kind == "http":
            if not self.url or not self.url.startswith(("http://", "https://")):
                raise ValueError("http checks need a url starting with http:// or https://")
            self.host = self.port = None
        elif self.kind == "tcp":
            if not self.host or self.port is None:
                raise ValueError("tcp checks need a host and a port")
            self.url = None
            self.expected_status = None
        else:  # ping
            if not self.host:
                raise ValueError("ping checks need a host")
            self.url = None
            self.port = None
            self.expected_status = None
        if self.timeout_s >= self.interval_s:
            raise ValueError("timeout_s must be shorter than interval_s")
        return self
