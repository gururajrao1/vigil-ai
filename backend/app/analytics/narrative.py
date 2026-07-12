"""Per-signal plain-English narrative + causality rationale.

Uses the local LLM (Ollama) when available for a fluent regulatory-style summary,
and ALWAYS falls back to a deterministic template built from the signal's own
statistics so the explanation is present offline with zero keys. The narrative is
grounded strictly in the computed evidence (no free invention).
"""
from __future__ import annotations

from .. import llm

_SYSTEM = (
    "You are a pharmacovigilance analyst. Write a concise, factual safety-signal "
    "summary for a regulator. Use ONLY the provided statistics and evidence. Do not "
    "invent numbers. 3-4 sentences. Neutral clinical tone."
)


def _template(sig: dict) -> str:
    drug = sig.get("drug", "the drug")
    pt = (sig.get("meddra") or {}).get("pt") or sig.get("symptom", "the reaction")
    prr = sig.get("prr")
    ror = sig.get("ror")
    chi = sig.get("chi_square")
    n = sig.get("post_count")
    strength = sig.get("strength", "WEAK")
    who = sig.get("who_umc", "Unassessable")
    sev = sig.get("severity", "Low")
    fda = sig.get("fda_evidence") or {}
    spike = sig.get("spike_flag")

    parts = [
        f"A {strength.lower()} disproportionality signal was detected between "
        f"{drug} and {pt} from social-listening data "
        f"(PRR={prr}, ROR={ror}, \u03c7\u00b2={chi}, n={n} reports)."
    ]
    parts.append(
        f"Deterministic WHO-UMC assessment graded causality as {who} with an "
        f"overall severity of {sev}."
    )
    if fda.get("available"):
        src = "openFDA FAERS" if fda.get("source") == "openfda" else "reference knowledge base"
        parts.append(
            f"External evidence from {src} corroborates the association "
            f"(~{fda.get('report_count', 0)} supporting reports)."
        )
    else:
        parts.append("No corroborating openFDA record was retrieved for this pair.")
    if spike:
        parts.append("Reporting volume is currently spiking, warranting prompt review.")
    return " ".join(parts)


def build_narrative(sig: dict, allow_llm: bool = True) -> dict:
    """Return {text, source}. Never raises.

    When ``allow_llm`` is False, returns the instant deterministic template (used
    during bulk ingest). When True, tries the local LLM first and falls back to the
    template — used for on-demand narrative generation from the API.
    """
    fallback = _template(sig)
    if not allow_llm:
        return {"text": fallback, "source": "deterministic"}
    prompt = (
        "Summarize this drug safety signal for a regulator using only these facts:\n"
        f"- Drug: {sig.get('drug')}\n"
        f"- Reaction (MedDRA PT): {(sig.get('meddra') or {}).get('pt') or sig.get('symptom')}\n"
        f"- System Organ Class: {(sig.get('meddra') or {}).get('soc')}\n"
        f"- PRR={sig.get('prr')}, ROR={sig.get('ror')}, chi2={sig.get('chi_square')}, "
        f"reports={sig.get('post_count')}, strength={sig.get('strength')}\n"
        f"- WHO-UMC causality: {sig.get('who_umc')} (score {sig.get('who_umc_score')})\n"
        f"- Severity: {sig.get('severity')}\n"
        f"- openFDA: {sig.get('fda_evidence')}\n"
        f"- Spiking: {sig.get('spike_flag')}\n"
    )
    text = llm.generate(prompt, system=_SYSTEM, temperature=0.2)
    if text and len(text) > 40:
        return {"text": text.strip(), "source": "llm"}
    return {"text": fallback, "source": "deterministic"}
