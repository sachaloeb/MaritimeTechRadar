"""Pydantic models for startups.yaml and scoring.yaml, with human-readable validation."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from radar.paths import CONFIGS_DIR

# ── Startups config ──────────────────────────────────────────────────────────


class StartupEntry(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]*$")
    urls: list[str] = Field(min_length=1)
    notes: str = ""

    @field_validator("urls")
    @classmethod
    def urls_must_not_contain_pipe(cls, v: list[str]) -> list[str]:
        for url in v:
            if "|" in url:
                raise ValueError(
                    f"URL must not contain pipe character '|' (used as list delimiter): {url}"
                )
        return v


class StartupsConfig(BaseModel):
    startups: list[StartupEntry] = Field(default_factory=list)


# ── Scoring config ───────────────────────────────────────────────────────────


class CriterionConfig(BaseModel):
    weight: float = Field(ge=0.0, le=1.0)
    saturation: int = Field(ge=1)
    keywords: list[str] = Field(default_factory=list)
    derived_from: str | None = None


class RingsConfig(BaseModel):
    pilot_ready: int = 70
    promising: int = 50
    early: int = 30


class QuadrantConfig(BaseModel):
    label: str
    keywords: list[str] = Field(min_length=1)


class ScoringConfig(BaseModel):
    criteria: dict[str, CriterionConfig]
    rings: RingsConfig = Field(default_factory=RingsConfig)
    quadrants: dict[str, QuadrantConfig]
    denylist: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_weights_sum_to_one(self) -> "ScoringConfig":
        total = sum(c.weight for c in self.criteria.values())
        if abs(total - 1.0) > 0.001:
            weight_detail = {k: c.weight for k, c in self.criteria.items()}
            raise ValueError(
                f"Criterion weights must sum to 1.0, got {total:.4f}. "
                f"Current weights: {weight_detail}"
            )
        return self


# ── Loaders ──────────────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping in {path}, got {type(data).__name__}"
        )
    return data


def load_startups_config(path: Path | None = None) -> StartupsConfig:
    path = path or CONFIGS_DIR / "startups.yaml"
    return StartupsConfig(**_load_yaml(path))


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    path = path or CONFIGS_DIR / "scoring.yaml"
    return ScoringConfig(**_load_yaml(path))
