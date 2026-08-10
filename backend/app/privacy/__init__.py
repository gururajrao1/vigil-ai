"""Privacy hygiene: PII/PHI scrubbing, pseudonymous author hashing, content dedupe."""
from .hygiene import (
    HygieneResult,
    author_hash,
    content_hash,
    hygiene_pipeline,
    scrub_text,
)

__all__ = [
    "HygieneResult",
    "author_hash",
    "content_hash",
    "hygiene_pipeline",
    "scrub_text",
]
