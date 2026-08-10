"""Clinical note parser adapter (cTAKES / SemEHR–inspired, offline).

Handles MIMIC-IV–style discharge summary text: section splitting + entity
extraction via VigilAI NLP. No licensed UMLS Metathesaurus required —
uses open MedDRA-style / ontology surrogates.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import IngestAdapter

# Common MIMIC / discharge summary section headers
_SECTION_RE = re.compile(
    r"(?mi)^("
    r"chief complaint|history of present illness|hpi|"
    r"past medical history|pmh|medications? on admission|"
    r"allergies|physical exam|hospital course|"
    r"discharge medications?|discharge diagnosis|discharge condition|"
    r"brief hospital course|pertinent results"
    r")\s*:?\s*$"
)


def split_clinical_sections(text: str) -> Dict[str, str]:
    """Split a discharge summary into named sections (best-effort)."""
    lines = (text or "").splitlines()
    sections: Dict[str, List[str]] = {"_preamble": []}
    current = "_preamble"
    for line in lines:
        m = _SECTION_RE.match(line.strip())
        if m:
            current = m.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "".join(v).strip()}


def parse_clinical_note(
    text: str,
    *,
    note_id: str = "note-0",
    use_transformer: bool = False,
) -> Dict[str, Any]:
    """Parse one clinical note → ingest-ready dict + section/entity audit."""
    from ...nlp.entities import extract_entities

    sections = split_clinical_sections(text)
    # Prefer medications + hospital course + discharge diagnosis for AE mining
    focus_keys = (
        "discharge medications", "medications on admission", "medications",
        "hospital course", "brief hospital course", "discharge diagnosis",
        "history of present illness", "hpi", "chief complaint",
    )
    focus_parts = [sections[k] for k in focus_keys if k in sections]
    focus_text = "\n\n".join(focus_parts) if focus_parts else text
    ents = extract_entities(focus_text, use_transformer=use_transformer)
    return {
        "external_id": f"clinical_note:{note_id}",
        "platform": "clinical_note",
        "product_type": "drug",
        "title": (sections.get("chief complaint") or "Clinical note")[:200],
        "body": focus_text[:8000],
        "author": f"note:{note_id}",
        "region": "GLOBAL",
        "sections": list(sections.keys()),
        "entities_preview": {
            "n_drugs": len(ents.get("drugs") or []),
            "n_symptoms": len(ents.get("symptoms") or []),
            "n_conditions": len(ents.get("conditions") or []),
        },
    }


class ClinicalNotesAdapter(IngestAdapter):
    """Adapter for MIMIC-IV–style discharge summaries / clinical narratives."""

    name = "clinical_notes"

    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        notes: Optional[List[Dict[str, Any]]] = kwargs.get("notes")
        texts: Optional[List[str]] = kwargs.get("texts")
        use_transformer = bool(kwargs.get("use_transformer", False))
        out: List[Dict[str, Any]] = []

        if notes:
            for i, n in enumerate(notes):
                text = n.get("text") or n.get("body") or ""
                note_id = str(n.get("id") or n.get("note_id") or i)
                if text.strip():
                    out.append(parse_clinical_note(
                        text, note_id=note_id, use_transformer=use_transformer
                    ))
        elif texts:
            for i, text in enumerate(texts):
                if (text or "").strip():
                    out.append(parse_clinical_note(
                        text, note_id=str(i), use_transformer=use_transformer
                    ))
        else:
            # Offline demo fixture — synthetic discharge summary
            demo = (
                "Chief Complaint:\nNausea and dizziness after starting Accutane.\n\n"
                "Past Medical History:\nAcne vulgaris. No diabetes.\n\n"
                "Medications on Admission:\nIsotretinoin 40 mg daily. Ibuprofen PRN.\n\n"
                "Hospital Course:\nPatient reports severe headache and mood changes. "
                "Denies chest pain. Discontinued isotretinoin.\n\n"
                "Discharge Diagnosis:\nDrug-induced depression; headache.\n"
            )
            out.append(parse_clinical_note(demo, note_id="demo-mimic-style"))
        return out
