"""FR-CFG-02: pydantic schema for all config files.

Fail-fast on start: invalid config → ValueError with a clear message.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class WeightsConfig(BaseModel):
    F: float = Field(ge=0, le=1)
    Q: float = Field(ge=0, le=1)
    T: float = Field(ge=0, le=1)
    FM: float = Field(default=0.0, ge=0, le=1)
    SR: float = Field(default=0.0, ge=0, le=1)
    AC: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "WeightsConfig":
        total = self.F + self.Q + self.T + self.FM + self.SR + self.AC
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"weights must sum to 1.0, got {total:.4f}")
        return self


class NormalizationConfig(BaseModel):
    winsor: list[float] = Field(default=[0.01, 0.99])
    method: str = Field(default="percentile")
    sector_neutral: bool = Field(default=True)
    min_sector_n: int = Field(default=5, ge=1)

    @field_validator("winsor")
    @classmethod
    def winsor_valid(cls, v: list[float]) -> list[float]:
        if len(v) != 2 or not (0 <= v[0] < v[1] <= 1):
            raise ValueError("winsor must be [lo, hi] with 0 <= lo < hi <= 1")
        return v


class ModelConfig(BaseModel):
    model_version: str
    weights: WeightsConfig
    w_min: float = Field(default=0.05, ge=0, le=1)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)

    # stochastic/actuarial blocks are optional (v1.0), so allow extra keys
    model_config = {"extra": "allow"}


class ScreenGatesConfig(BaseModel):
    min_adv_idr: float = Field(default=0, ge=0)
    min_listing_days: int = Field(default=0, ge=0)
    exclude_status: list[str] = Field(default_factory=list)
    min_data_confidence: float = Field(default=0.0, ge=0, le=1)


class ScreenFilterConfig(BaseModel):
    metric: str
    op: str
    value: Any
    sectors_except: list[str] = Field(default_factory=list)


class ScreenConfig(BaseModel):
    name: str
    universe: str = "all"
    gates: ScreenGatesConfig = Field(default_factory=ScreenGatesConfig)
    filters: list[ScreenFilterConfig] = Field(default_factory=list)
    rank_by: str = "caqs"
    top_n: int = Field(default=15, ge=1)


class ScreensConfig(BaseModel):
    screens: list[ScreenConfig] = Field(default_factory=list)


class AlertRuleConfig(BaseModel):
    id: str
    category: str
    scope: Any
    condition: str
    severity: str = "medium"
    cooldown_hours: int = Field(default=24, ge=0)


class AlertsConfig(BaseModel):
    alerts: list[AlertRuleConfig] = Field(default_factory=list)


def validate_model_config(raw: dict[str, Any]) -> ModelConfig:
    """Parse and validate model.yaml; raises ValueError on bad config."""
    return ModelConfig.model_validate(raw)


def validate_screens_config(raw: dict[str, Any]) -> ScreensConfig:
    return ScreensConfig.model_validate(raw)


def validate_alerts_config(raw: dict[str, Any]) -> AlertsConfig:
    return AlertsConfig.model_validate(raw)
