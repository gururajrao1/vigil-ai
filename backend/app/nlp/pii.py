"""Layered, worldwide PII scrubbing.

Layer 1 (always on, offline): regex for globally-common identifiers plus
country-specific IDs (US SSN, UK NINO, EU/IBAN, credit cards, India Aadhaar/PAN/UPI),
emails, phones (E.164/international), URLs, @handles.

Layer 2 (optional): Microsoft Presidio NER for names/locations/organizations in
many locales, enabled via USE_PRESIDIO. Loaded lazily; if Presidio/spaCy are not
installed it is skipped silently.

All text is scrubbed before it is ever stored or displayed.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import List, Tuple

from ..config import settings

logger = logging.getLogger("vigilai.pii")

# --------------------------------------------------------------------------- #
# Layer 1: regex (worldwide + country-specific)
# --------------------------------------------------------------------------- #
_PATTERNS = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "URL": re.compile(r"https?://\S+|www\.\S+"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "UK_NINO": re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "UPI": re.compile(r"\b[\w.-]{2,}@(?:okhdfcbank|oksbi|okaxis|okicici|paytm|ybl|upi)\b"),
    "PHONE": re.compile(
        r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(\d{2,4}\)[-.\s]?)?"
        r"(?:\d[-.\s]?){9,12}\d(?!\d)"
    ),
    "HANDLE": re.compile(r"(?<!\w)@\w{2,}"),
}

_REPLACE = {
    "EMAIL": "[EMAIL]", "URL": "[URL]", "CREDIT_CARD": "[CARD]", "IBAN": "[IBAN]",
    "US_SSN": "[SSN]", "UK_NINO": "[NINO]", "AADHAAR": "[AADHAAR]", "PAN": "[PAN]",
    "UPI": "[UPI]", "PHONE": "[PHONE]", "HANDLE": "[USER]",
}

# Order matters: greedy/specific patterns before generic ones.
_ORDER = ["URL", "EMAIL", "UPI", "CREDIT_CARD", "IBAN", "US_SSN", "UK_NINO",
          "AADHAAR", "PAN", "PHONE", "HANDLE"]

# --------------------------------------------------------------------------- #
# Layer 2: Presidio (optional, multi-locale NER)
# --------------------------------------------------------------------------- #
_ANALYZER = None
_ANONYMIZER = None
_PRESIDIO_TRIED = False
_LOCK = threading.Lock()

# Entity types Presidio should redact (names/locations/etc). We avoid medical
# false positives by only anonymizing person/location/org identifiers.
_PRESIDIO_ENTITIES = ["PERSON", "LOCATION", "NRP", "ORGANIZATION"]

# Medical allow-list: never let Presidio redact known drug/brand/symptom/condition
# terms (it loves to tag brand names like "Voltaren" as a PERSON, which would
# delete the drug before NER runs).
_MEDICAL_ALLOW: set[str] = set()


def _medical_allow() -> set[str]:
    global _MEDICAL_ALLOW
    if _MEDICAL_ALLOW:
        return _MEDICAL_ALLOW
    try:
        from .lexicons import BRAND_TO_GENERIC, CONDITIONS, GENERIC_DRUGS, SYMPTOMS

        terms = set(GENERIC_DRUGS) | set(BRAND_TO_GENERIC) | set(SYMPTOMS) | set(CONDITIONS)
        words = set()
        for t in terms:
            words.add(t.lower())
            for w in t.split():
                if len(w) > 2:
                    words.add(w.lower())
        _MEDICAL_ALLOW = words
    except Exception:
        _MEDICAL_ALLOW = set()
    return _MEDICAL_ALLOW


def _presidio():
    global _ANALYZER, _ANONYMIZER, _PRESIDIO_TRIED
    if not settings.use_presidio:
        return None, None
    if _PRESIDIO_TRIED:
        return _ANALYZER, _ANONYMIZER
    with _LOCK:
        if _PRESIDIO_TRIED:
            return _ANALYZER, _ANONYMIZER
        _PRESIDIO_TRIED = True
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine

            # Use the small spaCy model we ship (default Presidio expects the large one).
            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            })
            _ANALYZER = AnalyzerEngine(nlp_engine=provider.create_engine())
            _ANONYMIZER = AnonymizerEngine()
            logger.info("Presidio PII engine ready (en_core_web_sm).")
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("Presidio unavailable, using regex-only PII: %s", exc)
            _ANALYZER = None
            _ANONYMIZER = None
    return _ANALYZER, _ANONYMIZER


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in re.sub(r"\D", "", digits)]
    if len(nums) < 13:
        return False
    total, parity = 0, len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def scrub(text: str, use_presidio: bool | None = None) -> Tuple[str, List[str]]:
    """Return (scrubbed_text, sorted_list_of_pii_types_found).

    ``use_presidio`` controls the (CPU-heavy) Presidio NER layer:
      * None  -> follow the ``USE_PRESIDIO`` setting (default on).
      * True  -> force Presidio name/location redaction on.
      * False -> regex-only (instant); used for bulk ingest of synthetic corpora
                 that contain no free-text names, keeping the always-on regex layer.
    """
    if not text:
        return "", []
    found: List[str] = []
    out = text

    for label in _ORDER:
        pattern = _PATTERNS[label]
        if label == "CREDIT_CARD":
            # Only redact plausible card numbers (Luhn) to avoid nuking dosages/IDs.
            def _repl(m):
                return _REPLACE["CREDIT_CARD"] if _luhn_ok(m.group(0)) else m.group(0)
            new = pattern.sub(_repl, out)
            if new != out:
                found.append(label)
                out = new
            continue
        if pattern.search(out):
            found.append(label)
            out = pattern.sub(_REPLACE[label], out)

    # Layer 2: Presidio names/locations (skippable for fast bulk ingest)
    analyzer, anonymizer = (None, None) if use_presidio is False else _presidio()
    if analyzer and anonymizer:
        try:
            results = analyzer.analyze(text=out, language="en", entities=_PRESIDIO_ENTITIES)
            allow = _medical_allow()
            # Drop any detection whose span text is a medical term (or too short),
            # and require a reasonable confidence to reduce false positives.
            filtered = []
            for r in results:
                span = out[r.start:r.end].strip().lower()
                if not span or len(span) < 3:
                    continue
                if span in allow or any(w in allow for w in span.split()):
                    continue
                if getattr(r, "score", 1.0) < 0.6:
                    continue
                filtered.append(r)
            if filtered:
                from presidio_anonymizer.entities import OperatorConfig

                operators = {
                    e: OperatorConfig("replace", {"new_value": f"[{e}]"})
                    for e in _PRESIDIO_ENTITIES
                }
                out = anonymizer.anonymize(text=out, analyzer_results=filtered,
                                           operators=operators).text
                found.extend(sorted({r.entity_type for r in filtered}))
        except Exception as exc:  # pragma: no cover
            logger.debug("Presidio anonymization failed: %s", exc)

    return out, sorted(set(found))
