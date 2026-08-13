"""CIOMS Form I auto-draft generator.

Generates a human-readable CIOMS I (Council for International Organizations of
Medical Sciences) Individual Case Safety Report (ICSR) for each VigilAI signal.

All patient fields are [REDACTED] per PII guardrails. Produces both an
HTML version (printable, table layout) and a plain-text fallback.

CIOMS I export from workspace extractions.
"""
from __future__ import annotations

from datetime import datetime, date
from html import escape as h


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SERIOUS_CRITERIA_MAP = {
    "Critical": ["Suspected to be life-threatening (LT)"],
    "High": ["Hospitalisation (initial or prolonged) — HP"],
    "Medium": ["Medically significant / other (OT)"],
    "Low": ["Medically significant / other (OT)"],
}

_IME_TERMS = {
    "death", "fatal", "died", "cardiac arrest", "respiratory failure",
    "anaphylaxis", "anaphylactic", "seizure", "convulsion", "stroke",
    "hepatic failure", "liver failure", "renal failure", "kidney failure",
    "agranulocytosis", "aplastic anaemia", "aplastic anemia", "sjs",
    "stevens-johnson", "toxic epidermal necrolysis", "ten",
    "pulmonary embolism", "thrombocytopenia", "pancytopenia",
    "rhabdomyolysis", "acute myocardial infarction", "myocardial infarction",
    "suicidal ideation", "suicide attempt",
}

_SERIOUSNESS_CRITERIA_LABELS = {
    "DE": "Death (DE)",
    "LT": "Life-threatening (LT)",
    "HP": "Hospitalisation (initial or prolonged) — HP",
    "DS": "Disability / Incapacity (DS)",
    "CA": "Congenital anomaly (CA)",
    "OT": "Medically significant / other (OT)",
}


def _derive_seriousness(signal: dict) -> list[str]:
    """Map signal severity + IME lexicon to CIOMS seriousness check-boxes."""
    criteria: list[str] = []
    severity = (signal.get("severity") or "").strip()
    symptom_lower = (signal.get("symptom") or "").lower()
    meddra_pt = (signal.get("meddra") or {}).get("pt", "")
    reaction_text = (symptom_lower + " " + (meddra_pt or "").lower()).strip()

    if any(t in reaction_text for t in ("death", "fatal", "died")):
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["DE"])
    if any(t in reaction_text for t in {"anaphylaxis", "anaphylactic", "cardiac arrest",
                                         "respiratory failure", "life-threatening"}):
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["LT"])
    elif severity == "Critical" and not criteria:
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["LT"])

    if any(t in reaction_text for t in {"hospitalisation", "hospitalization", "admitted",
                                         "emergency", "icu"}):
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["HP"])
    elif severity == "High" and not criteria:
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["HP"])

    # IME (Important Medical Event) lexicon check
    if any(t in reaction_text for t in _IME_TERMS) and not criteria:
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["OT"])

    if not criteria:
        criteria.append(_SERIOUSNESS_CRITERIA_LABELS["OT"])

    return criteria


def _outcome(signal: dict) -> str:
    factors = signal.get("who_umc_factors") or []
    if isinstance(factors, list) and any("dechallenge" in str(f).lower() for f in factors):
        return "Recovered / Resolved"
    return "Unknown"


def _onset_date(signal: dict) -> str:
    ep = signal.get("earliest_post_at")
    if ep:
        try:
            return ep[:10]
        except Exception:
            return str(ep)
    return "Unknown"


def _action_taken(signal: dict) -> str:
    factors = signal.get("who_umc_factors") or []
    if isinstance(factors, list) and any("dechallenge" in str(f).lower() for f in factors):
        return "Drug withdrawn"
    return "Unknown"


def _clean_narrative(signal: dict) -> str:
    """Return the narrative, truncated for CIOMS box and PII-safe."""
    raw = signal.get("narrative") or ""
    if not raw:
        prr = signal.get("prr") or "n/a"
        ror = signal.get("ror") or "n/a"
        cnt = signal.get("post_count") or 0
        raw = (
            f"Signal detected by VigilAI from aggregated social-media posts. "
            f"Product: {signal.get('drug', 'Unknown')}. "
            f"Event: {signal.get('symptom', 'Unknown')}. "
            f"Post count: {cnt}. PRR={prr}, ROR={ror}. "
            f"WHO-UMC causality: {signal.get('who_umc', 'Unassessable')}. "
            f"Severity: {signal.get('severity', 'Unknown')}."
        )
    # Cap length for the form box
    if len(raw) > 2000:
        raw = raw[:1997] + "..."
    return raw


def _report_id(signal: dict) -> str:
    return f"VIGILAI-CIOMS-{signal.get('id', 'NA')}"


# ---------------------------------------------------------------------------
# HTML generator
# ---------------------------------------------------------------------------

_CELL_STYLE = (
    "border:1px solid #555;padding:4px 6px;vertical-align:top;"
    "font-family:Arial,sans-serif;font-size:11px;"
)
_HEADER_STYLE = (
    "border:1px solid #555;padding:4px 6px;vertical-align:top;"
    "font-family:Arial,sans-serif;font-size:11px;"
    "background:#dce6f1;font-weight:bold;"
)
_SECTION_STYLE = (
    "border:1px solid #555;padding:4px 6px;"
    "font-family:Arial,sans-serif;font-size:11px;"
    "background:#1f3864;color:#ffffff;font-weight:bold;"
)
_LABEL_STYLE = (
    "font-family:Arial,sans-serif;font-size:10px;"
    "color:#444;display:block;margin-bottom:1px;"
)
_VALUE_STYLE = (
    "font-family:Arial,sans-serif;font-size:11px;"
    "font-weight:bold;color:#111;"
)


def _row(label: str, value: str, cols: int = 1) -> str:
    colspan = f' colspan="{cols}"' if cols > 1 else ""
    return (
        f'<tr>'
        f'<td style="{_HEADER_STYLE}">{h(label)}</td>'
        f'<td style="{_CELL_STYLE}"{colspan}>{h(str(value))}</td>'
        f'</tr>'
    )


def _section_row(title: str, cols: int = 2) -> str:
    return (
        f'<tr>'
        f'<td colspan="{cols + 1}" style="{_SECTION_STYLE}">'
        f'{h(title)}'
        f'</td>'
        f'</tr>'
    )


def generate_cioms_html(signal: dict) -> str:
    """Return a printable HTML string of the CIOMS I form for *signal*."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_id = _report_id(signal)
    drug_name = signal.get("drug") or "Unknown"
    symptom = signal.get("symptom") or "Unknown"
    meddra_pt = (signal.get("meddra") or {}).get("pt") or symptom
    meddra_soc = (signal.get("meddra") or {}).get("soc") or "Unknown"
    country = signal.get("primary_region") or signal.get("primary_country_code") or "Unknown"
    onset = _onset_date(signal)
    outcome = _outcome(signal)
    seriousness = _derive_seriousness(signal)
    action = _action_taken(signal)
    narrative = _clean_narrative(signal)
    who_umc = signal.get("who_umc") or "Unassessable"
    who_umc_score = signal.get("who_umc_score") or 0.0
    severity = signal.get("severity") or "Unknown"
    post_count = signal.get("post_count") or 0
    prr = signal.get("prr") or "n/a"
    ror = signal.get("ror") or "n/a"
    strength = signal.get("strength") or "Unknown"
    atc = signal.get("drug_atc") or "Not coded"
    indication = "Unknown — derived from social-listening context"
    if signal.get("mechanism") and isinstance(signal["mechanism"], dict):
        ind = signal["mechanism"].get("indication")
        if ind:
            indication = ind

    seriousness_html = "".join(f"<li>{h(s)}</li>" for s in seriousness)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>CIOMS I Form — {h(drug_name)} / {h(symptom)}</title>
<style>
  body {{ margin:10mm; font-family:Arial,sans-serif; font-size:11px; }}
  table {{ border-collapse:collapse; width:100%; }}
  @media print {{
    body {{ margin:10mm; }}
    .no-print {{ display:none; }}
  }}
  .disclaimer {{
    font-size:9px;color:#888;border-top:1px solid #ccc;
    padding-top:4px;margin-top:8px;
  }}
</style>
</head>
<body>

<!-- ===== Title bar ===== -->
<table style="margin-bottom:6px;">
  <tr>
    <td style="border:2px solid #1f3864;padding:6px 10px;background:#1f3864;color:#fff;
               font-size:13px;font-weight:bold;font-family:Arial,sans-serif;">
      CIOMS FORM I — INDIVIDUAL CASE SAFETY REPORT (ICSR)
    </td>
    <td style="border:2px solid #1f3864;padding:6px 10px;font-size:11px;
               font-family:Arial,sans-serif;text-align:right;vertical-align:top;">
      <span style="font-size:9px;color:#666;">Council for International Organizations<br/>of Medical Sciences</span><br/>
      <strong>Report ID:</strong> {h(report_id)}<br/>
      <strong>Date of this report:</strong> {h(now_str)}<br/>
      <strong>Type:</strong> Initial &nbsp;|&nbsp; <strong>Source:</strong> Spontaneous / social media
    </td>
  </tr>
</table>

<table>

<!-- ===== Section 1: Patient ===== -->
{_section_row("SECTION 1 — PATIENT INFORMATION", 3)}
<tr>
  <td style="{_HEADER_STYLE}">Patient initials</td>
  <td style="{_CELL_STYLE}">[REDACTED]</td>
  <td style="{_HEADER_STYLE}">Country of incidence</td>
  <td style="{_CELL_STYLE}">{h(country)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Date of birth / Age</td>
  <td style="{_CELL_STYLE}">[REDACTED — age range if available: unknown]</td>
  <td style="{_HEADER_STYLE}">Sex</td>
  <td style="{_CELL_STYLE}">Unknown</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Weight (kg)</td>
  <td style="{_CELL_STYLE}">Unknown</td>
  <td style="{_HEADER_STYLE}">Height (cm)</td>
  <td style="{_CELL_STYLE}">Unknown</td>
</tr>

<!-- ===== Section 2: Suspect drug ===== -->
{_section_row("SECTION 2 — SUSPECT DRUG(S)", 3)}
<tr>
  <td style="{_HEADER_STYLE}">Generic name</td>
  <td style="{_CELL_STYLE}">{h(drug_name)}</td>
  <td style="{_HEADER_STYLE}">Brand name</td>
  <td style="{_CELL_STYLE}">{h(drug_name.title())} (trade name not available)</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">ATC code</td>
  <td style="{_CELL_STYLE}">{h(atc)}</td>
  <td style="{_HEADER_STYLE}">Daily dose / Route</td>
  <td style="{_CELL_STYLE}">Unknown / Unknown</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Indication</td>
  <td style="{_CELL_STYLE}" colspan="3">{h(indication)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Therapy start date</td>
  <td style="{_CELL_STYLE}">{h(onset)} (earliest post date — approximation)</td>
  <td style="{_HEADER_STYLE}">Therapy stop date</td>
  <td style="{_CELL_STYLE}">Unknown</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Action taken on drug</td>
  <td style="{_CELL_STYLE}" colspan="3">{h(action)}</td>
</tr>

<!-- ===== Section 3: Concomitant drugs ===== -->
{_section_row("SECTION 3 — OTHER DRUGS / CONCOMITANT MEDICATIONS", 3)}
<tr>
  <td colspan="4" style="{_CELL_STYLE}">
    Not available from social-listening / aggregated signal data.
  </td>
</tr>

<!-- ===== Section 4: Reaction ===== -->
{_section_row("SECTION 4 — REACTION(S) / EVENT(S)", 3)}
<tr>
  <td style="{_HEADER_STYLE}">Reaction / Event term (verbatim)</td>
  <td style="{_CELL_STYLE}">{h(symptom)}</td>
  <td style="{_HEADER_STYLE}">MedDRA Preferred Term (PT)</td>
  <td style="{_CELL_STYLE}">{h(meddra_pt)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">MedDRA SOC</td>
  <td style="{_CELL_STYLE}">{h(meddra_soc)}</td>
  <td style="{_HEADER_STYLE}">Onset date</td>
  <td style="{_CELL_STYLE}">{h(onset)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Date of recovery</td>
  <td style="{_CELL_STYLE}">Unknown</td>
  <td style="{_HEADER_STYLE}">Outcome</td>
  <td style="{_CELL_STYLE}">{h(outcome)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Seriousness criteria (tick all that apply)</td>
  <td colspan="3" style="{_CELL_STYLE}">
    <ul style="margin:0;padding-left:16px;">{seriousness_html}</ul>
  </td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">WHO-UMC causality assessment</td>
  <td style="{_CELL_STYLE}">{h(who_umc)} (score: {who_umc_score:.2f})</td>
  <td style="{_HEADER_STYLE}">Signal severity tier</td>
  <td style="{_CELL_STYLE}">{h(severity)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Relevant tests / lab data</td>
  <td colspan="3" style="{_CELL_STYLE}">
    Disproportionality — PRR: {h(str(prr))}, ROR: {h(str(ror))},
    Signal strength: {h(strength)}, Post count: {post_count}.
    (Social-listening surrogate — no clinical lab data available.)
  </td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}" colspan="1">Relevant history / narrative</td>
  <td colspan="3" style="{_CELL_STYLE};white-space:pre-wrap;">{h(narrative)}</td>
</tr>

<!-- ===== Section 5: Reporter ===== -->
{_section_row("SECTION 5 — REPORTER", 3)}
<tr>
  <td style="{_HEADER_STYLE}">Reporter type</td>
  <td style="{_CELL_STYLE}">Consumer / Patient (social media / patient forum — aggregated signal)</td>
  <td style="{_HEADER_STYLE}">Healthcare professional?</td>
  <td style="{_CELL_STYLE}">No</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Reporter name</td>
  <td style="{_CELL_STYLE}">[REDACTED — anonymous post author hash]</td>
  <td style="{_HEADER_STYLE}">Country</td>
  <td style="{_CELL_STYLE}">{h(country)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Reporter source</td>
  <td colspan="3" style="{_CELL_STYLE}">
    Social media / patient forum post (aggregated VigilAI signal — not a single identified case).
    Original post(s) identified via social-listening pipeline (platform-level author hash only).
  </td>
</tr>

<!-- ===== Section 6: Report metadata ===== -->
{_section_row("SECTION 6 — REPORT ADMINISTRATIVE DATA", 3)}
<tr>
  <td style="{_HEADER_STYLE}">Report ID</td>
  <td style="{_CELL_STYLE}">{h(report_id)}</td>
  <td style="{_HEADER_STYLE}">Date of this report</td>
  <td style="{_CELL_STYLE}">{h(now_str)}</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Report type</td>
  <td style="{_CELL_STYLE}">Initial</td>
  <td style="{_HEADER_STYLE}">Report source</td>
  <td style="{_CELL_STYLE}">Spontaneous (social media aggregation)</td>
</tr>
<tr>
  <td style="{_HEADER_STYLE}">Sender / Manufacturer</td>
  <td colspan="3" style="{_CELL_STYLE}">
    VigilAI — Pharmacovigilance Signal Detection Platform
  </td>
</tr>

</table>

<p class="disclaimer">
  This CIOMS I form is auto-generated from aggregated
  social-listening data. Patient
  identifiers are fully redacted per PII guardrails. MedDRA coding is an open
  surrogate (not licensed MedDRA). WHO-UMC causality is deterministic-lexicon-based.
  VigilAI © {datetime.utcnow().year}.
</p>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Plain-text generator
# ---------------------------------------------------------------------------

def generate_cioms_text(signal: dict) -> str:
    """Return a plain-text CIOMS I form representation for *signal*."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_id = _report_id(signal)
    drug_name = signal.get("drug") or "Unknown"
    symptom = signal.get("symptom") or "Unknown"
    meddra_pt = (signal.get("meddra") or {}).get("pt") or symptom
    meddra_soc = (signal.get("meddra") or {}).get("soc") or "Unknown"
    country = signal.get("primary_region") or signal.get("primary_country_code") or "Unknown"
    onset = _onset_date(signal)
    outcome = _outcome(signal)
    seriousness = _derive_seriousness(signal)
    action = _action_taken(signal)
    narrative = _clean_narrative(signal)
    who_umc = signal.get("who_umc") or "Unassessable"
    who_umc_score = signal.get("who_umc_score") or 0.0
    severity = signal.get("severity") or "Unknown"
    post_count = signal.get("post_count") or 0
    prr = signal.get("prr") or "n/a"
    ror = signal.get("ror") or "n/a"
    strength = signal.get("strength") or "Unknown"
    atc = signal.get("drug_atc") or "Not coded"
    indication = "Unknown — derived from social-listening context"
    if signal.get("mechanism") and isinstance(signal["mechanism"], dict):
        ind = signal["mechanism"].get("indication")
        if ind:
            indication = ind

    sep = "=" * 72
    thin = "-" * 72

    lines = [
        sep,
        "CIOMS FORM I — INDIVIDUAL CASE SAFETY REPORT (ICSR)",
        "Council for International Organizations of Medical Sciences",
        sep,
        f"Report ID    : {report_id}",
        f"Report date  : {now_str}",
        f"Report type  : Initial | Source: Spontaneous / social media",
        "",
        "SECTION 1 — PATIENT INFORMATION",
        thin,
        f"Patient initials : [REDACTED]",
        f"Country          : {country}",
        f"Date of birth    : [REDACTED — age range if available: unknown]",
        f"Sex              : Unknown",
        f"Weight / Height  : Unknown / Unknown",
        "",
        "SECTION 2 — SUSPECT DRUG(S)",
        thin,
        f"Generic name   : {drug_name}",
        f"Brand name     : {drug_name.title()} (trade name not available)",
        f"ATC code       : {atc}",
        f"Daily dose     : Unknown",
        f"Route          : Unknown",
        f"Indication     : {indication}",
        f"Therapy start  : {onset} (earliest post date — approximation)",
        f"Therapy stop   : Unknown",
        f"Action taken   : {action}",
        "",
        "SECTION 3 — CONCOMITANT MEDICATIONS",
        thin,
        "Not available from social-listening / aggregated signal data.",
        "",
        "SECTION 4 — REACTION(S) / EVENT(S)",
        thin,
        f"Verbatim term    : {symptom}",
        f"MedDRA PT        : {meddra_pt}",
        f"MedDRA SOC       : {meddra_soc}",
        f"Onset date       : {onset}",
        f"Outcome          : {outcome}",
        "Seriousness      :",
    ]
    for s in seriousness:
        lines.append(f"  - {s}")
    lines += [
        f"WHO-UMC causality: {who_umc} (score: {who_umc_score:.2f})",
        f"Severity tier    : {severity}",
        f"Disproportionality: PRR={prr}, ROR={ror}, strength={strength}, posts={post_count}",
        "",
        "Narrative / description:",
        narrative,
        "",
        "SECTION 5 — REPORTER",
        thin,
        "Reporter type  : Consumer / Patient (social media / patient forum — aggregated signal)",
        "Healthcare pro : No",
        "Reporter name  : [REDACTED — anonymous post author hash]",
        f"Country        : {country}",
        "Source         : Social media / patient forum post (aggregated VigilAI signal).",
        "",
        "SECTION 6 — REPORT ADMINISTRATIVE DATA",
        thin,
        f"Report ID      : {report_id}",
        f"Date           : {now_str}",
        "Report type    : Initial",
        "Source         : Spontaneous (social media aggregation)",
        "Sender         : VigilAI — Pharmacovigilance Signal Detection Platform",
        "",
        sep,
        "PII fully redacted.",
        "MedDRA-style open coding.",
        sep,
    ]
    return "\n".join(lines)
