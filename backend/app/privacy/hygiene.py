"""Automated de-identification + deduplication before DB storage.

Pipeline (mandatory for every ingest record):

1. PII/PHI stripping — Presidio + regex (names → ``[REDACTED_NAME]``, etc.)
2. Pseudonymous author hashing — ``HMAC-SHA256(username, SYSTEM_SALT)``
   Raw handles MUST NEVER be persisted.
3. Content-hash deduplication — ``SHA256(normalize_text(raw_text))``
   Within a 30-day window, duplicates increment ``duplicate_count`` without
   inflating the unique post denominator N.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..nlp.content_dedupe import normalize_content, post_content_signature
from ..nlp.pii import scrub as _pii_scrub

logger = logging.getLogger("vigilai.privacy")

# Map Presidio / regex type labels → standardized redaction tokens
_TOKEN_MAP = {
    "PERSON": "[REDACTED_NAME]",
    "NAME": "[REDACTED_NAME]",
    "LOCATION": "[REDACTED_LOCATION]",
    "LOC": "[REDACTED_LOCATION]",
    "GPE": "[REDACTED_LOCATION]",
    "PHONE_NUMBER": "[REDACTED_PHONE]",
    "PHONE": "[REDACTED_PHONE]",
    "EMAIL_ADDRESS": "[REDACTED_EMAIL]",
    "EMAIL": "[REDACTED_EMAIL]",
    "DATE_TIME": "[REDACTED_DOB]",
    "DATE": "[REDACTED_DOB]",
    "DOB": "[REDACTED_DOB]",
    "US_SSN": "[REDACTED_ID]",
    "SSN": "[REDACTED_ID]",
    "IBAN_CODE": "[REDACTED_ID]",
    "CREDIT_CARD": "[REDACTED_ID]",
    "AADHAAR": "[REDACTED_ID]",
    "PAN": "[REDACTED_ID]",
    "NINO": "[REDACTED_ID]",
    "URL": "[REDACTED_URL]",
    "HANDLE": "[REDACTED_HANDLE]",
}

_ANGLE_PII = re.compile(
    r"<(PERSON|LOCATION|PHONE_NUMBER|EMAIL_ADDRESS|DATE_TIME|US_SSN|"
    r"CREDIT_CARD|IBAN_CODE|NRP|URL)>"
)


@dataclass
class HygieneResult:
    """Outcome of the privacy hygiene pass for one record."""

    scrubbed_text: str
    scrubbed_title: str
    pii_types: List[str] = field(default_factory=list)
    author_hash: str = ""
    content_hash: str = ""
    is_duplicate: bool = False
    master_raw_id: Optional[int] = None
    action: str = "accept"  # accept | suppress_duplicate | skip_empty
    tokens_applied: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scrubbed_text": self.scrubbed_text,
            "scrubbed_title": self.scrubbed_title,
            "pii_types": self.pii_types,
            "author_hash": self.author_hash,
            "content_hash": self.content_hash,
            "is_duplicate": self.is_duplicate,
            "master_raw_id": self.master_raw_id,
            "action": self.action,
            "tokens_applied": self.tokens_applied,
        }


def scrub_text(text: str, *, use_presidio: bool | None = None) -> tuple[str, List[str], List[str]]:
    """Scrub PII/PHI and rewrite angle-bracket markers to standardized tokens."""
    cleaned, found = _pii_scrub(text or "", use_presidio=use_presidio)
    tokens: List[str] = []

    def _repl(m: re.Match) -> str:
        label = m.group(1).upper()
        tok = _TOKEN_MAP.get(label, f"[REDACTED_{label}]")
        if tok not in tokens:
            tokens.append(tok)
        return tok

    cleaned = _ANGLE_PII.sub(_repl, cleaned)
    # Also normalize common Presidio <TYPE> leftovers that scrub may leave
    for label, tok in _TOKEN_MAP.items():
        angle = f"<{label}>"
        if angle in cleaned:
            cleaned = cleaned.replace(angle, tok)
            if tok not in tokens:
                tokens.append(tok)
    return cleaned, list(found or []), tokens


def author_hash(username: Optional[str], *, salt: Optional[str] = None) -> str:
    """Pseudonymous HMAC-SHA256 of a raw handle. Empty → empty."""
    raw = (username or "").strip()
    if not raw:
        return ""
    # Already look like a hex digest? Keep as-is (connectors may pre-hash).
    if re.fullmatch(r"[0-9a-f]{32,64}", raw.lower()):
        return raw.lower()
    key = (salt or settings.system_salt or "vigilai").encode("utf-8")
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def content_hash(title: str = "", body: str = "") -> str:
    """SHA-256 of normalized clinical narrative (title + body)."""
    return post_content_signature({"title": title or "", "body": body or ""})


def _lookup_duplicate(
    db: Optional[Session],
    chash: str,
    *,
    project_id: Optional[int] = None,
    window_days: Optional[int] = None,
) -> Optional[int]:
    """Return master raw_post id if content_hash seen within the dedupe window."""
    if not db or not chash:
        return None
    from ..models import RawPost

    days = window_days if window_days is not None else settings.dedupe_window_days
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(days)))
    q = (
        db.query(RawPost.id)
        .filter(
            RawPost.content_hash == chash,
            RawPost.ingested_at >= cutoff,
        )
        .order_by(RawPost.id.asc())
    )
    if project_id is not None:
        from sqlalchemy import or_

        q = q.filter(or_(
            RawPost.project_id == project_id,
            RawPost.project_id.is_(None),
            RawPost.project_id == 0,
        ))
    row = q.first()
    return int(row[0]) if row else None


def _bump_duplicate_count(db: Session, master_id: int) -> None:
    from ..models import RawPost

    row = db.get(RawPost, master_id)
    if row is None:
        return
    row.duplicate_count = int(row.duplicate_count or 0) + 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.debug("duplicate_count bump failed for raw_id=%s", master_id, exc_info=True)


def hygiene_pipeline(
    record: Dict[str, Any],
    *,
    db: Optional[Session] = None,
    project_id: Optional[int] = None,
    use_presidio: bool | None = None,
    bump_duplicate: bool = True,
) -> HygieneResult:
    """Full privacy hygiene pass for one ingest dict.

    Mutates a *copy* of fields into the result; does not write new RawPost rows.
    On duplicate within the window, increments ``duplicate_count`` on the master.
    """
    title = record.get("title") or ""
    body = record.get("body") or record.get("text") or ""
    author = record.get("author") or record.get("username") or record.get("author_hash") or ""

    scrubbed_title, pii_t, tokens_t = scrub_text(title, use_presidio=use_presidio)
    scrubbed_body, pii_b, tokens_b = scrub_text(body, use_presidio=use_presidio)
    pii_types = sorted(set(pii_t) | set(pii_b))
    tokens = sorted(set(tokens_t) | set(tokens_b))

    ahash = author_hash(str(author) if author else "")
    chash = content_hash(scrubbed_title, scrubbed_body)

    if not chash and not normalize_content(scrubbed_body) and not normalize_content(scrubbed_title):
        return HygieneResult(
            scrubbed_text=scrubbed_body,
            scrubbed_title=scrubbed_title,
            pii_types=pii_types,
            author_hash=ahash,
            content_hash="",
            action="skip_empty",
            tokens_applied=tokens,
        )

    master_id = _lookup_duplicate(db, chash, project_id=project_id)
    if master_id is not None:
        if bump_duplicate and db is not None:
            _bump_duplicate_count(db, master_id)
        return HygieneResult(
            scrubbed_text=scrubbed_body,
            scrubbed_title=scrubbed_title,
            pii_types=pii_types,
            author_hash=ahash,
            content_hash=chash,
            is_duplicate=True,
            master_raw_id=master_id,
            action="suppress_duplicate",
            tokens_applied=tokens,
        )

    return HygieneResult(
        scrubbed_text=scrubbed_body,
        scrubbed_title=scrubbed_title,
        pii_types=pii_types,
        author_hash=ahash,
        content_hash=chash,
        action="accept",
        tokens_applied=tokens,
    )


def apply_hygiene_to_ingest_dict(
    record: Dict[str, Any],
    *,
    db: Optional[Session] = None,
    project_id: Optional[int] = None,
) -> tuple[Dict[str, Any], HygieneResult]:
    """Return a sanitized ingest dict ready for RawPost insert + hygiene result."""
    result = hygiene_pipeline(record, db=db, project_id=project_id)
    out = dict(record)
    out["title"] = result.scrubbed_title
    out["body"] = result.scrubbed_text
    out["author"] = result.author_hash  # pipeline stores as author_hash
    out["author_hash"] = result.author_hash
    out["content_hash"] = result.content_hash
    out["pii_found"] = result.pii_types
    out.pop("username", None)
    return out, result
