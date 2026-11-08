from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Format(StrEnum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKE = "strike"
    SPOILER = "spoiler"
    CODE = "code"


class ButtonType(StrEnum):
    URL = "url"
    CALLBACK = "callback"
    COPY_TEXT = "copy_text"
    SWITCH_INLINE = "switch_inline"


class ButtonSpec(BaseModel):
    text: str
    type: ButtonType = ButtonType.URL
    value: str = ""


class Segment(BaseModel):
    text: str = ""
    formats: set[Format] = Field(default_factory=set)
    link_url: str | None = None
    block: Literal["p", "quote", "pre"] = "p"
    lang: str | None = None
    buttons: list[ButtonSpec] = Field(default_factory=list)


class Draft(BaseModel):
    segments: list[Segment] = Field(default_factory=list)
    photo: str | None = None
    inline_buttons: list[list[ButtonSpec]] = Field(default_factory=list)

    @property
    def is_rich(self) -> bool:
        return any(segment.buttons for segment in self.segments)

    @property
    def has_content(self) -> bool:
        return bool(self.segments) or self.photo is not None
