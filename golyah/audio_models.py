"""Legacy audio references retained for lossless imports and saved records."""
from typing import Literal
from pydantic import BaseModel, Field


class AudioClip(BaseModel):
    filename: str = Field(pattern=r'^golyahki_[a-f0-9]{64}\.(wav|ogg|mp3)$')
    text: str
    source: Literal['windows', 'wiktionary']
    voice: str = ''
    rate: int = 0
    credit: str = ''
    url: str = ''
