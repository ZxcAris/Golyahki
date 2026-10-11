"""Validated, portable appearance preferences for Golyahki and its vocabulary cards."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Appearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accent: str = "#a9b7ff"
    uiFont: str = "Segoe UI"
    uiFontSize: int = Field(default=15, ge=12, le=20)
    cardFont: str = "Segoe UI"
    cardFontSize: int = Field(default=16, ge=13, le=24)
    cardWidth: int = Field(default=520, ge=360, le=840)
    cardBackground: str = "#20242e"
    cardBackgroundEnd: str = "#181c25"
    cardGradient: bool = False
    cardText: str = "#e8ebf3"
    cardMuted: str = "#a4adbf"
    cardAccent: str = "#b7c3ff"
    cardBorder: str = "#363d4e"
    cardRadius: int = Field(default=18, ge=0, le=32)
    cardSpacing: int = Field(default=14, ge=8, le=24)
    cardLineHeight: float = Field(default=1.35, ge=1.1, le=1.8)
    overlayDim: int = Field(default=28, ge=0, le=80)

    @field_validator("accent", "cardBackground", "cardBackgroundEnd", "cardText",
                     "cardMuted", "cardAccent", "cardBorder")
    @classmethod
    def color(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Укажите цвет в формате #RRGGBB.")
        return value.lower()

    @field_validator("uiFont", "cardFont")
    @classmethod
    def font(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 80 or any(c in value for c in '\r\n"\'{}<>;\\'):
            raise ValueError("Выберите корректное название шрифта.")
        return value


def load_appearance(value) -> Appearance:
    """Recover valid stored preferences even if a single old setting is malformed."""
    if not isinstance(value, dict):
        return Appearance()
    result = Appearance().model_dump()
    for name, setting in value.items():
        if name not in result:
            continue
        try:
            candidate = Appearance.model_validate({**result, name: setting})
        except ValueError:
            continue
        result = candidate.model_dump()
    return Appearance.model_validate(result)
