"""SIDER 4.1-style in-label baseline → OMOP expected drug↔AE pairs.

Maps package-insert side effects to CONCEPT + ``omop_drug_condition_baseline``
with ``is_expected_baseline=TRUE`` so Detect / dashboards can filter known
label AEs. Offline-first: bundled TSV surrogate when SIDER download is unavailable.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from ..db.omop_concept_seed import upsert_concept
from ..db.omop_models import DrugConditionBaseline

logger = logging.getLogger("vigilai.etl.sider")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "etl"
SIDER_TSV = DATA_DIR / "sider_4_1_meddra_all_se_surrogate.tsv"


def _ensure_surrogate_tsv() -> Path:
    """Write a compact SIDER-shaped TSV if missing (offline teaching pack)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SIDER_TSV.exists():
        return SIDER_TSV
    # Columns inspired by SIDER meddra_all_se.tsv:
    # stitch_id_flat, stitch_id_stereo, umls_cui_label, meddra_concept_type,
    # umls_cui_meddra, side_effect_name, drug_name
    rows = [
        ["CID100002771", "CID000002771", "C0012833", "PT", "C0012833", "Dizziness", "metformin"],
        ["CID100002771", "CID000002771", "C0027497", "PT", "C0027497", "Nausea", "metformin"],
        ["CID100002771", "CID000002771", "C0011991", "PT", "C0011991", "Diarrhoea", "metformin"],
        ["CID100003444", "CID000003444", "C0018681", "PT", "C0018681", "Headache", "sitagliptin"],
        ["CID100003444", "CID000003444", "C0015672", "PT", "C0015672", "Fatigue", "sitagliptin"],
        ["CID100000083", "CID000000083", "C0018681", "PT", "C0018681", "Headache", "empagliflozin"],
        ["CID100000083", "CID000000083", "C0042963", "PT", "C0042963", "Urinary tract infection", "empagliflozin"],
        ["CID100000083", "CID000000083", "C0011991", "PT", "C0011991", "Diarrhoea", "empagliflozin"],
        ["CID100004905", "CID000004905", "C0027497", "PT", "C0027497", "Nausea", "semaglutide"],
        ["CID100004905", "CID000004905", "C0011991", "PT", "C0011991", "Diarrhoea", "semaglutide"],
        ["CID100004905", "CID000004905", "C0042963", "PT", "C0042963", "Vomiting", "semaglutide"],
        ["CID100002446", "CID000002446", "C0019080", "PT", "C0019080", "Haemorrhage", "warfarin"],
        ["CID100002446", "CID000002446", "C0014867", "PT", "C0014867", "Gastrointestinal haemorrhage", "warfarin"],
        ["CID100000937", "CID000000937", "C0018681", "PT", "C0018681", "Headache", "isotretinoin"],
        ["CID100000937", "CID000000937", "C0015230", "PT", "C0015230", "Dry skin", "isotretinoin"],
        ["CID100000937", "CID000000937", "C0011570", "PT", "C0011570", "Depression", "isotretinoin"],
    ]
    with SIDER_TSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow([
            "stitch_id_flat",
            "stitch_id_stereo",
            "umls_cui_label",
            "meddra_concept_type",
            "umls_cui_meddra",
            "side_effect_name",
            "drug_name",
        ])
        w.writerows(rows)
    return SIDER_TSV


def _read_sider_rows(path: Path) -> List[Tuple[str, str, str]]:
    """Return (drug_name, side_effect, umls_cui) triples."""
    out: List[Tuple[str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            try:
                drug = (row.get("drug_name") or "").strip().lower()
                se = (row.get("side_effect_name") or "").strip()
                cui = (row.get("umls_cui_meddra") or row.get("umls_cui_label") or "").strip()
                concept_type = (row.get("meddra_concept_type") or "PT").strip().upper()
                if concept_type and concept_type != "PT":
                    continue  # prefer Preferred Terms
                if drug and se:
                    out.append((drug, se, cui))
            except Exception as exc:  # noqa: BLE001
                logger.debug("SIDER row skip: %s", exc)
    return out


def ingest_sider_baseline(
    db: Session,
    *,
    project_id: Optional[int] = None,
    force_fixture: bool = False,
    tsv_path: Optional[Path] = None,
) -> dict:
    """Load SIDER-style TSV into CONCEPT + omop_drug_condition_baseline."""
    path = tsv_path or _ensure_surrogate_tsv()
    if force_fixture and tsv_path is None:
        path = _ensure_surrogate_tsv()

    pairs = _read_sider_rows(path)
    inserted = 0
    skipped = 0
    for drug, se, cui in pairs:
        try:
            drug_c = upsert_concept(
                db,
                concept_code=f"SIDER:{drug.upper()[:40]}",
                concept_name=drug.title(),
                domain_id="Drug",
                vocabulary_id="SIDER",
                concept_class_id="Ingredient",
            )
            cond_c = upsert_concept(
                db,
                concept_code=cui or f"SIDER_SE:{se.upper()[:40]}",
                concept_name=se,
                domain_id="Condition",
                vocabulary_id="MedDRA",
                concept_class_id="PT",
            )
            existing = (
                db.query(DrugConditionBaseline)
                .filter(
                    DrugConditionBaseline.drug_source_value == drug,
                    DrugConditionBaseline.condition_source_value == se.lower(),
                    DrugConditionBaseline.source == "SIDER 4.1",
                )
                .first()
            )
            if existing:
                existing.is_expected_baseline = True
                skipped += 1
                continue
            db.add(
                DrugConditionBaseline(
                    drug_concept_id=drug_c.concept_id,
                    condition_concept_id=cond_c.concept_id,
                    drug_source_value=drug,
                    condition_source_value=se.lower(),
                    is_expected_baseline=True,
                    source="SIDER 4.1",
                    project_id=project_id,
                )
            )
            inserted += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            skipped += 1
            logger.warning("SIDER pair dropped %s/%s: %s", drug, se, exc)

    return {
        "mode": "surrogate_tsv" if "surrogate" in path.name else "tsv",
        "path": str(path),
        "pairs_read": len(pairs),
        "baselines_inserted": inserted,
        "skipped": skipped,
        "is_expected_baseline": True,
    }
