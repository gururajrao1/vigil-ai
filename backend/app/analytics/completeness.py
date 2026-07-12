"""UMC vigiGrade-style report completeness scoring (social-listening surrogate).

Real **vigiGrade** (Bergvall, Norén & Lindquist, 2014) grades every Individual Case
Safety Report (ICSR) on how well *documented* it is, independent of whether the
association is real. It is a **multiplicative penalty score in [0, 1]**: start at a
perfect 1.0 and, for every key clinical dimension that is MISSING from the report,
multiply the running score by a documented penalty factor. A case with time-to-onset,
indication, outcome, dose, patient age/sex, etc. all present scores near 1.0; a bare
"drug X caused event Y" case scores low. The average vigiGrade of a data source is a
headline data-quality metric at the WHO-UMC.

We cannot compute the *true* vigiGrade — social-listening posts do not carry the full
structured ICSR fields (no reporter qualification, exact dose regimen, verified
patient demographics, etc.). Instead we compute a clearly-labelled **surrogate**:
the same multiplicative-penalty machinery applied to the dimensions we CAN actually
assess from a scrubbed patient post — entity richness, indication, a time-to-onset
cue, outcome/seriousness language, de-/re-challenge cues, patient descriptors,
dose mention, free-text length, known country, and expressed sentiment/severity.

Deterministic, offline, pure-Python. Temporal / dechallenge / rechallenge cue phrase
lists are reused from :mod:`app.analytics.causality` so the two overlays stay
consistent.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .causality import _DECHALLENGE, _RECHALLENGE, _TEMPORAL

# --------------------------------------------------------------------------- #
# vigiGrade-style dimension penalty table.
#
# Each entry: (key, label, penalty, description). ``penalty`` is the multiplicative
# deduction applied to the running score when the dimension is MISSING (i.e. the
# score is multiplied by ``1 - penalty``). Penalties are curated so that a richly
# documented post lands ~0.8-1.0 and a bare one ~0.1-0.3, mirroring the spread of
# the true vigiGrade. ``entities_present`` carries the heaviest penalty because a
# report with no identifiable drug + event is barely a report at all.
# --------------------------------------------------------------------------- #
DIMENSIONS: List[tuple] = [
    ("entities_present", "Drug + event identifiable", 0.60,
     "At least one drug/product AND one non-negated symptom/event were extracted."),
    ("indication", "Indication / condition", 0.15,
     "The condition the product was taken for is stated (why it was used)."),
    ("time_to_onset", "Time-to-onset cue", 0.22,
     "A temporal relationship between exposure and the event is described "
     "(e.g. 'within hours', 'day 3', 'soon after starting')."),
    ("outcome_seriousness", "Outcome / seriousness", 0.20,
     "The outcome or seriousness of the event is described "
     "(e.g. hospitalisation, 'severe', 'unbearable', resolution)."),
    ("dechallenge", "Dechallenge cue", 0.15,
     "The effect of stopping the product is described (positive dechallenge)."),
    ("rechallenge", "Rechallenge cue", 0.12,
     "The effect of re-taking the product is described (positive rechallenge)."),
    ("patient_descriptors", "Patient descriptors (age/sex)", 0.10,
     "Patient age and/or sex is discernible from the text."),
    ("dose", "Dose / regimen", 0.10,
     "A dose or regimen is mentioned (e.g. '20 mg', 'two tablets daily')."),
    ("free_text", "Sufficient free text", 0.12,
     "The narrative is long enough to carry clinical detail (>= 12 words)."),
    ("country_known", "Country known", 0.10,
     "The report is geolocated to a country (supports regional follow-up)."),
    ("sentiment_severity", "Sentiment / severity signal", 0.10,
     "The post carries a clear negative-experience sentiment for the reaction."),
]

_DIM_INDEX = {key: (label, penalty, desc) for key, label, penalty, desc in DIMENSIONS}

# Well-documented threshold on the mean completeness of a signal's supporting posts.
WELL_DOCUMENTED_THRESHOLD = 0.5

# --------------------------------------------------------------------------- #
# Language cues for the dimensions not already covered by the causality lists.
# --------------------------------------------------------------------------- #
_SERIOUSNESS = [
    "hospital", "hospitalised", "hospitalized", "emergency", "er ", "icu",
    "life-threatening", "life threatening", "died", "death", "fatal", "disabled",
    "disability", "severe", "serious", "unbearable", "excruciating", "worst",
    "terrible", "awful", "horrible", "hit me hard", "rushed", "collapsed",
    "permanent", "never again", "affecting me", "couldn't", "could not",
]

# Age: "34F", "34 yo", "45-year-old", "aged 60", "I'm 27". Sex/gender terms.
_AGE_RE = re.compile(
    r"\b(\d{1,2}\s*(?:yo|y/o|yrs?|years?[\s-]*old)|\d{1,2}\s*[mf]\b|aged\s+\d{1,2}"
    r"|\b(?:i['’]?m|i am)\s+\d{1,2}\b)",
    re.IGNORECASE,
)
_SEX_RE = re.compile(
    r"\b(male|female|woman|women|man|men|boy|girl|mother|father|son|daughter|"
    r"my (?:wife|husband|mum|mom|dad))\b",
    re.IGNORECASE,
)
# Dose: "20 mg", "500mcg", "two tablets", "1 pill", "10 units", "2 puffs".
_DOSE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:mg|mcg|µg|ug|g|ml|iu|units?)"
    r"|\d+\s*(?:tablets?|tabs?|pills?|caps?|capsules?|puffs?|doses?|shots?|injections?)"
    r"|(?:one|two|three|half a?)\s+(?:tablets?|pills?|doses?))\b",
    re.IGNORECASE,
)


def _has_any(text: str, phrases: List[str]) -> bool:
    return any(p in text for p in phrases)


# --------------------------------------------------------------------------- #
# Dimension extraction from a stored post.
# --------------------------------------------------------------------------- #
def dimensions_for_post(
    *,
    text: str,
    entities: Optional[dict] = None,
    negation: Optional[dict] = None,
    sentiment: Optional[dict] = None,
    country: Optional[str] = None,
) -> Dict[str, bool]:
    """Derive the assessable vigiGrade-style dimensions from one post's stored data.

    ``entities`` is the ProcessedPost entity JSON ({"drugs":[...],"symptoms":[...],
    "conditions":[...]}); ``negation`` maps normalized symptom -> is_negated;
    ``sentiment`` is {"label","score"}; ``country`` is the ISO country name.
    """
    entities = entities or {}
    negation = negation or {}
    sentiment = sentiment or {}
    t = (text or "").lower()
    words = t.split()

    drugs = entities.get("drugs") or []
    symptoms = entities.get("symptoms") or []
    conditions = entities.get("conditions") or []
    non_negated_symptoms = [
        s for s in symptoms if not negation.get(s.get("normalized", ""), False)
    ]

    label = (sentiment.get("label") or "").upper()

    return {
        "entities_present": bool(drugs) and bool(non_negated_symptoms),
        "indication": bool(conditions) or " for my " in f" {t} " or " for a " in f" {t} ",
        "time_to_onset": _has_any(t, _TEMPORAL)
            or bool(re.search(r"\bday\s*\d+\b", t))
            or "since i started" in t or "ever since" in t,
        "outcome_seriousness": _has_any(t, _SERIOUSNESS),
        "dechallenge": _has_any(t, _DECHALLENGE),
        "rechallenge": _has_any(t, _RECHALLENGE),
        "patient_descriptors": bool(_AGE_RE.search(t)) or bool(_SEX_RE.search(t)),
        "dose": bool(_DOSE_RE.search(t)),
        "free_text": len(words) >= 12,
        "country_known": bool(country),
        "sentiment_severity": label == "NEGATIVE",
    }


# --------------------------------------------------------------------------- #
# Scoring.
# --------------------------------------------------------------------------- #
def score_post(post_features: Dict[str, bool]) -> dict:
    """vigiGrade-style multiplicative completeness score for a single post.

    ``post_features`` is a {dimension_key: bool} mapping (as produced by
    :func:`dimensions_for_post`). Returns the score in [0, 1] plus the present /
    missing dimension keys and the full per-dimension boolean map.
    """
    score = 1.0
    present: List[str] = []
    missing: List[str] = []
    dims: Dict[str, bool] = {}
    for key, _label, penalty, _desc in DIMENSIONS:
        ok = bool(post_features.get(key, False))
        dims[key] = ok
        if ok:
            present.append(key)
        else:
            missing.append(key)
            score *= (1.0 - penalty)
    return {
        "score": round(score, 3),
        "present": present,
        "missing": missing,
        "dimensions": dims,
    }


def grade_label(score: float) -> str:
    """Human-readable documentation-quality band for a completeness score."""
    if score >= WELL_DOCUMENTED_THRESHOLD:
        return "well-documented"
    if score >= 0.3:
        return "partially documented"
    return "poorly documented"


def score_signal(supporting_post_features: List[Dict[str, bool]]) -> dict:
    """Aggregate completeness across a signal's supporting posts.

    ``supporting_post_features`` = list of {dimension_key: bool} maps, one per
    supporting post. Returns the mean completeness, a ``well_documented`` flag
    (mean >= threshold), counts, the best/worst supporting post (by score, carrying
    its index so the caller can map back to a post id) and per-dimension coverage
    (the fraction of supporting posts in which each dimension is present).
    """
    n = len(supporting_post_features)
    if n == 0:
        return {
            "mean_completeness": 0.0,
            "well_documented": False,
            "grade": grade_label(0.0),
            "n_posts": 0,
            "best": None,
            "worst": None,
            "dimension_coverage": {key: 0.0 for key, *_ in DIMENSIONS},
        }

    scored = [score_post(f) for f in supporting_post_features]
    scores = [s["score"] for s in scored]
    mean = sum(scores) / n

    best_i = max(range(n), key=lambda i: scores[i])
    worst_i = min(range(n), key=lambda i: scores[i])

    coverage = {
        key: round(
            sum(1 for f in supporting_post_features if f.get(key, False)) / n, 3
        )
        for key, *_ in DIMENSIONS
    }

    def _post_summary(i: int) -> dict:
        return {
            "index": i,
            "score": scored[i]["score"],
            "present": scored[i]["present"],
            "missing": scored[i]["missing"],
        }

    return {
        "mean_completeness": round(mean, 3),
        "well_documented": mean >= WELL_DOCUMENTED_THRESHOLD,
        "grade": grade_label(mean),
        "n_posts": n,
        "best": _post_summary(best_i),
        "worst": _post_summary(worst_i),
        "dimension_coverage": coverage,
    }


def reference() -> dict:
    """Dimension + penalty table description (for the /api/completeness reference)."""
    return {
        "method": "UMC vigiGrade-style completeness (multiplicative penalty score)",
        "well_documented_threshold": WELL_DOCUMENTED_THRESHOLD,
        "dimensions": [
            {"key": key, "label": label, "penalty": penalty, "description": desc}
            for key, label, penalty, desc in DIMENSIONS
        ],
        "note": "Documentation-quality surrogate adapted to social-listening fields: "
                "the true vigiGrade requires structured ICSR data not present in "
                "patient posts. Score starts at 1.0 and is multiplied by (1 - penalty) "
                "for every missing dimension.",
    }
