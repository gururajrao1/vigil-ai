"""Agentic synthetic patient-post generator (Forge).

Pipeline per record:
  scenario  -> generate -> judge(medical, realism, hallucination, pii) -> score
            -> repair (if below threshold) -> re-score -> build output

Uses the local LLM (Ollama) when available for realistic prose, and ALWAYS falls
back to deterministic templates + rule-based judges so it runs offline with no keys.
Synthetic output is clearly fictional and can be used to stress-test the PV pipeline
or as training data — it is never written into the live signal vaults automatically.
"""
from __future__ import annotations

import json
import random
import uuid
from typing import Dict, List

from .. import llm
from ..config import settings
from ..nlp.pii import scrub

_EMOTIONS = ["worried", "frustrated", "calm", "scared", "hopeful", "angry", "confused"]
_STYLES = ["casual forum post", "short tweet", "detailed reddit post", "brief complaint"]
_WRITINGS = {
    "casual forum post": "Started {drug} for my {cond} about a week ago and I've been getting {sym}. "
                         "Not sure if it's the meds but the timing lines up. Anyone else experience this?",
    "short tweet": "day 4 on {drug} for {cond} and the {sym} is real 😩 anyone else??",
    "detailed reddit post": "I (34F) was prescribed {drug} for {cond}. Within a few days I developed {sym}. "
                            "I stopped the medication and it started improving. Posting in case it helps someone.",
    "brief complaint": "{drug} gave me {sym}. Stopped taking it. Be careful.",
}

_FORBIDDEN = ["synthetic", "as an ai", "language model", "fictional", "generated", "openai"]


def _make_scenario(req: dict, rng: random.Random) -> dict:
    llm_scn = None
    # Use full LLM chain (Ollama → Gemini → OpenRouter), not Ollama-only.
    if settings.use_llm:
        llm_scn = llm.generate_json(
            "Create a brief fictional patient scenario as JSON with keys: age (int), "
            "gender, emotion, timeline_days (int), writing_style. "
            f"Context: drug={req['drug']}, condition={req['condition']}, "
            f"platform={req['platform']}, region={req.get('region')}.",
            system="You design realistic but fictional patient scenarios. JSON only.",
            temperature=0.7,
        )
    scn = {
        "age": rng.randint(19, 72),
        "gender": rng.choice(["female", "male", "non-binary"]),
        "emotion": rng.choice(_EMOTIONS),
        "timeline_days": rng.randint(1, 21),
        "writing_style": rng.choice(_STYLES),
    }
    if isinstance(llm_scn, dict):
        scn.update({k: llm_scn[k] for k in scn if k in llm_scn})
    return scn


def _generate_post(req: dict, scn: dict, rng: random.Random) -> dict:
    drug, cond, sym = req["drug"], req["condition"], req["symptom"]
    if settings.use_llm:
        text = llm.generate(
            f"Write ONE realistic {scn['writing_style']} from a {scn['age']}yo {scn['gender']} "
            f"patient ({scn['emotion']}) describing taking {drug} for {cond} and experiencing "
            f"{sym}. First person, natural, no names or contact info, 1-3 sentences. "
            f"Do NOT mention that this is synthetic or AI-generated.",
            system="You write authentic-sounding patient social media posts. Output the post only.",
            temperature=0.8,
        )
        if text and len(text) > 25:
            return {"text": text.strip(), "source": "llm"}
    # deterministic fallback
    template = _WRITINGS.get(scn["writing_style"], _WRITINGS["casual forum post"])
    return {"text": template.format(drug=drug, cond=cond, sym=sym), "source": "deterministic"}


def _judge(text: str, req: dict) -> Dict[str, float]:
    low = text.lower()
    # PII score: 100 if clean, penalized per PII type found
    _, pii = scrub(text)
    pii_score = max(0.0, 100.0 - 25.0 * len(pii))
    # hallucination/cleanliness: penalize forbidden meta phrases + impossible length
    halluc = 100.0
    if any(f in low for f in _FORBIDDEN):
        halluc -= 50.0
    if len(text) > 800:
        halluc -= 20.0
    halluc = max(0.0, halluc)
    # medical validity: must mention the drug and the symptom
    med = 100.0
    if req["drug"].split()[0].lower() not in low:
        med -= 40.0
    if req["symptom"].lower() not in low and not any(w in low for w in req["symptom"].split()):
        med -= 40.0
    med = max(0.0, med)
    # realism: length + first person + not too templated
    realism = 60.0
    if any(p in low for p in ["i ", "my ", "me ", "i'm", "ive", "i've"]):
        realism += 20.0
    if 40 <= len(text) <= 400:
        realism += 20.0
    realism = min(100.0, realism)
    return {"medical": round(med, 1), "realism": round(realism, 1),
            "hallucination": round(halluc, 1), "pii": round(pii_score, 1)}


def _quality(scores: Dict[str, float]) -> float:
    return round(
        0.30 * scores["medical"] + 0.30 * scores["realism"]
        + 0.25 * scores["hallucination"] + 0.15 * scores["pii"], 1)


def _repair(text: str, req: dict, scn: dict, rng: random.Random) -> dict:
    """One repair attempt: strip PII/meta and re-anchor drug+symptom."""
    cleaned, _ = scrub(text)
    low = cleaned.lower()
    for f in _FORBIDDEN:
        cleaned = cleaned.replace(f, "").replace(f.title(), "")
    if req["drug"].split()[0].lower() not in low or req["symptom"].lower() not in low:
        cleaned = _WRITINGS["casual forum post"].format(
            drug=req["drug"], cond=req["condition"], sym=req["symptom"])
    return {"text": cleaned.strip(), "source": "repaired"}


# Reuse the corpus AE map to pick a plausible symptom when none is provided.
_DEFAULT_SYMPTOMS = {
    "isotretinoin": "depression", "metformin": "diarrhea", "atorvastatin": "muscle pain",
    "sertraline": "insomnia", "ibuprofen": "stomach pain", "warfarin": "bleeding",
    "semaglutide": "nausea", "paracetamol": "nausea",
}


def generate_batch(drug: str, condition: str, platform: str = "reddit",
                   region: str = "Global", language: str = "English",
                   symptom: str | None = None, records: int = 5,
                   seed: int | None = None) -> dict:
    rng = random.Random(seed)
    batch_id = uuid.uuid4().hex[:12]
    drug_l = (drug or "").strip().lower()
    sym = symptom or _DEFAULT_SYMPTOMS.get(drug_l, "nausea")
    req_base = {"drug": drug, "condition": condition, "platform": platform,
                "region": region, "language": language, "symptom": sym}

    out: List[dict] = []
    for _ in range(max(1, min(records, 10))):
        scn = _make_scenario(req_base, rng)
        gen = _generate_post(req_base, scn, rng)
        scores = _judge(gen["text"], req_base)
        quality = _quality(scores)
        repaired = False
        if quality < settings.forge_quality_threshold and settings.forge_max_repair > 0:
            fixed = _repair(gen["text"], req_base, scn, rng)
            fixed_scores = _judge(fixed["text"], req_base)
            if _quality(fixed_scores) > quality:
                gen, scores, quality, repaired = fixed, fixed_scores, _quality(fixed_scores), True

        out.append({
            "batch_id": batch_id,
            "drug": drug, "condition": condition, "platform": platform,
            "region": region, "language": language,
            "post_text": gen["text"],
            "structured": {"suspect_drug": drug, "reaction": sym, "condition": condition},
            "scenario": scn,
            "scores": scores,
            "quality_score": quality,
            "export_ready": quality >= settings.forge_quality_threshold,
            "repaired": repaired,
            "source": gen["source"],
        })

    ready = sum(1 for r in out if r["export_ready"])
    backend = llm.active_backend()
    return {
        "batch_id": batch_id,
        "requested": records,
        "generated": len(out),
        "export_ready": ready,
        "avg_quality": round(sum(r["quality_score"] for r in out) / len(out), 1) if out else 0,
        "llm": backend != "deterministic",
        "llm_backend": backend,
        "records": out,
    }
