"""Sentiment analysis via VADER (offline, no key)."""
from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()

# Boost clinical negatives that VADER underweights.
_CLINICAL_NEG = [
    "side effect", "adverse", "reaction", "worse", "hospital", "emergency",
    "rash", "vomiting", "seizure", "bleeding", "allergic",
    # Device-vigilance cues (MAUDE / FSNs are often dry but still adverse reports)
    "malfunction", "device failure", "injury", "death", "recall",
    "field safety notice", "overinfusion", "underinfusion",
]


def analyze_sentiment(text: str) -> dict:
    if not text:
        return {"label": "NEUTRAL", "score": 0.0, "model": "vader"}
    scores = _analyzer.polarity_scores(text)
    compound = scores["compound"]

    lower = text.lower()
    if any(term in lower for term in _CLINICAL_NEG):
        compound -= 0.15  # nudge toward negative for clinical harm language

    if compound <= -0.05:
        label = "NEGATIVE"
    elif compound >= 0.35:
        label = "POSITIVE"
    else:
        label = "NEUTRAL"

    return {"label": label, "score": round(compound, 4), "model": "vader"}
