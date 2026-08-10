"""GVP Module IX Signal Lifecycle Management.

Defines the governed signal-management workflow (status transitions, priority scoring,
audit trail) aligned with EMA's GVP Module IX signal management guidance.

Priority score formula (composite, normalized 0-100):
  raw = disproportionality_strength × seriousness_weight × novelty_weight
        × velocity_weight × maxsprt_weight
  normalized to 0-100 against theoretical max (3×4×3×2×1.5 = 108).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Valid lifecycle states and the transitions each state permits.
# GVP Module IX workflow: New → Under Evaluation → Validated → Prioritized
#                                → Assessed → Closed (or Rejected at any stage)
# ---------------------------------------------------------------------------
LIFECYCLE_STATES: list[str] = [
    "new",
    "under_evaluation",
    "validated",
    "prioritized",
    "assessed",
    "closed",
    "rejected",
]

# Maps each state to the set of states it may legally advance to.
LIFECYCLE_TRANSITIONS: dict[str, list[str]] = {
    "new":              ["under_evaluation", "rejected"],
    "under_evaluation": ["validated", "rejected"],
    "validated":        ["prioritized", "rejected"],
    "prioritized":      ["assessed", "rejected"],
    "assessed":         ["closed", "rejected"],
    "closed":           [],          # terminal — no further transitions
    "rejected":         [],          # terminal
}

# Human-readable labels for UI display (plain language + GVP term).
STATE_LABELS: dict[str, str] = {
    "new":              "Inbox",
    "under_evaluation": "Looking into it",
    "validated":        "Looks real",
    "prioritized":      "High priority",
    "assessed":         "Written up",
    "closed":           "Done",
    "rejected":         "Not a concern",
}

# ---------------------------------------------------------------------------
# Priority score component weights
# ---------------------------------------------------------------------------
_STRENGTH_W: dict[str, float] = {"STRONG": 3.0, "MODERATE": 2.0, "WEAK": 1.0}
_SEVERITY_W: dict[str, float] = {"Critical": 4.0, "High": 3.0, "Medium": 2.0, "Low": 1.0}
_NOVELTY_W: dict[str, float]  = {
    "novel": 3.0, "unknown": 2.0, "in_label": 1.0, "boxed": 0.5, "not_applicable": 1.5,
}
_VELOCITY_W = {"spiking": 2.0, "trending": 1.5, "stable": 1.0}

# Theoretical max raw score → normalise to 0-100.
_RAW_MAX: float = 3.0 * 4.0 * 3.0 * 2.0 * 1.5  # 108.0


def compute_priority(signal_dict: dict) -> float:
    """Return composite priority score normalised to 0-100.

    Parameters
    ----------
    signal_dict:
        A signal serialised by ``signal_to_dict`` (helpers.py), containing keys:
        ``strength``, ``severity``, ``label_novelty``, ``spike_flag``,
        ``trend_score``, ``maxsprt_crossed``.
    """
    strength = (signal_dict.get("strength") or "WEAK").upper()
    severity = signal_dict.get("severity") or "Low"
    novelty  = (signal_dict.get("label_novelty") or "unknown").lower()
    spike    = bool(signal_dict.get("spike_flag", False))
    trend    = float(signal_dict.get("trend_score") or 0.0)
    maxsprt  = bool(signal_dict.get("maxsprt_crossed", False))

    ds_w  = _STRENGTH_W.get(strength, 1.0)
    ser_w = _SEVERITY_W.get(severity, 1.0)
    nov_w = _NOVELTY_W.get(novelty, 2.0)

    # Velocity: spiking > trending (positive slope) > stable.
    if spike:
        vel_w = _VELOCITY_W["spiking"]
    elif trend > 0:
        vel_w = _VELOCITY_W["trending"]
    else:
        vel_w = _VELOCITY_W["stable"]

    msp_w = 1.5 if maxsprt else 1.0

    raw   = ds_w * ser_w * nov_w * vel_w * msp_w
    score = min(100.0, round(raw / _RAW_MAX * 100.0, 1))
    return score


def valid_next_states(current: str) -> list[str]:
    """Return the list of states ``current`` may legally transition to."""
    return list(LIFECYCLE_TRANSITIONS.get(current, []))


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Return True when the from→to transition is allowed by GVP Module IX workflow."""
    return to_state in LIFECYCLE_TRANSITIONS.get(from_state, [])


# Prompt / EMA-style aliases ↔ persisted snake_case states
GVP_ALIAS_TO_STATE: dict[str, str] = {
    "detection": "new",
    "validation": "under_evaluation",
    "confirmation": "validated",
    "prioritization": "prioritized",
    "assessment": "assessed",
    "regulatory_action": "assessed",  # action notes live on assessed→closed
    "closed": "closed",
    "rejected": "rejected",
    # pass-through of native states
    "new": "new",
    "under_evaluation": "under_evaluation",
    "validated": "validated",
    "prioritized": "prioritized",
    "assessed": "assessed",
}

STATE_TO_GVP_ALIAS: dict[str, str] = {
    "new": "DETECTION",
    "under_evaluation": "VALIDATION",
    "validated": "CONFIRMATION",
    "prioritized": "PRIORITIZATION",
    "assessed": "ASSESSMENT",
    "closed": "CLOSED",
    "rejected": "REJECTED",
}


def normalize_lifecycle_status(raw: str | None) -> str:
    """Map GVP alias or native status to persisted lifecycle_status."""
    key = (raw or "new").strip().lower().replace(" ", "_")
    return GVP_ALIAS_TO_STATE.get(key, key if key in LIFECYCLE_STATES else "new")


def gvp_alias_for(status: str | None) -> str:
    return STATE_TO_GVP_ALIAS.get((status or "new").lower(), "DETECTION")
