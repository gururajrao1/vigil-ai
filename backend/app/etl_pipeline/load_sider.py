"""SIDER 4.1 in-label baseline → ``omop_drug_condition_baseline``.

Loads ``meddra_all_label_se.tsv`` / ``meddra_all_se.tsv`` (or a VigilAI surrogate),
maps STITCH/UMLS drug identifiers and MedDRA Preferred Terms to ``omop_concept``
BIGINT IDs, and upserts pairs with ``is_expected_baseline = TRUE`` (in-label /
``is_in_label`` safety baseline for disproportionality filtering).

Usage::

    python -m app.etl_pipeline.load_sider --sider-tsv /data/meddra_all_label_se.tsv
    python -m app.etl_pipeline.load_sider   # offline surrogate TSV
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db.pg_url import create_async_engine_normalized

LOGGER = logging.getLogger("vigilai.etl.load_sider")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "etl"
SURROGATE_TSV = DATA_DIR / "sider_4_1_meddra_all_se_surrogate.tsv"

# SIDER official column layout (meddra_all_label_se.tsv / meddra_all_se.tsv)
# stitch_flat, stitch_stereo, umls_label, meddra_type, umls_meddra, side_effect_name
# Optional VigilAI extension: drug_name as 7th column for offline teaching packs.


def _configure_logging(verbose: bool = False) -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.propagate = False


def _stable_concept_id(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _normalize(name: str) -> str:
    return " ".join(name.lower().split())


def ensure_surrogate_tsv(path: Path = SURROGATE_TSV) -> Path:
    """Write a compact SIDER 4.1-shaped TSV when no download is available."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
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
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow([
            "stitch_id_flat",
            "stitch_id_stereo",
            "umls_cui_label",
            "meddra_concept_type",
            "umls_cui_meddra",
            "side_effect_name",
            "drug_name",
        ])
        writer.writerows(rows)
    LOGGER.info("Wrote SIDER surrogate TSV → %s", path)
    return path


def _row_get(row: dict, *keys: str) -> str:
    for key in keys:
        if key in row and row[key] is not None:
            val = str(row[key]).strip()
            if val:
                return val
        # headerless positional fallbacks already normalized by DictReader
    return ""


def read_sider_pairs(path: Path) -> List[dict[str, str]]:
    """Parse SIDER TSV into drug/AE pairing dicts (PT rows only)."""
    pairs: List[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        has_header = "side_effect" in sample.lower() or "stitch" in sample.lower()
        if has_header:
            reader: Iterable[dict] = csv.DictReader(fh, delimiter="\t")
        else:
            # Official SIDER files are often headerless
            fieldnames = [
                "stitch_id_flat",
                "stitch_id_stereo",
                "umls_cui_label",
                "meddra_concept_type",
                "umls_cui_meddra",
                "side_effect_name",
                "drug_name",
            ]
            reader = csv.DictReader(fh, delimiter="\t", fieldnames=fieldnames)

        for idx, row in enumerate(reader, start=1):
            try:
                meddra_type = _row_get(
                    row, "meddra_concept_type", "meddra_type"
                ).upper() or "PT"
                if meddra_type not in {"PT", "PREF", "PREFERRED", ""}:
                    continue
                se = _row_get(row, "side_effect_name", "side_effect", "pt_name")
                if not se:
                    continue
                stitch = _row_get(row, "stitch_id_flat", "stitch_flat", "STITCH")
                umls_ae = _row_get(row, "umls_cui_meddra", "umls_cui_label", "umls_cui")
                drug_name = _row_get(row, "drug_name", "drug", "ingredient")
                if not drug_name and stitch:
                    drug_name = stitch.lower()
                if not drug_name:
                    LOGGER.debug("SIDER row %d missing drug identifier — skipped", idx)
                    continue
                pairs.append({
                    "drug_name": _normalize(drug_name),
                    "drug_display": drug_name,
                    "stitch_id": stitch,
                    "side_effect": se,
                    "umls_cui": umls_ae,
                })
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Malformed SIDER row %d skipped: %s", idx, exc)
    LOGGER.info("Parsed %d PT in-label pairs from %s", len(pairs), path)
    return pairs


async def _ensure_baseline_schema(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS omop_drug_condition_baseline (
                id SERIAL PRIMARY KEY,
                drug_concept_id BIGINT,
                condition_concept_id BIGINT,
                drug_source_value VARCHAR(256),
                condition_source_value VARCHAR(256),
                is_expected_baseline BOOLEAN NOT NULL DEFAULT TRUE,
                source VARCHAR(64) NOT NULL DEFAULT 'SIDER 4.1',
                project_id INTEGER,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            )
            """
        )
    )
    # Logical alias column for callers that expect is_in_label
    try:
        await conn.execute(
            text(
                """
                ALTER TABLE omop_drug_condition_baseline
                ADD COLUMN IF NOT EXISTS is_in_label BOOLEAN
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE omop_drug_condition_baseline
                SET is_in_label = is_expected_baseline
                WHERE is_in_label IS NULL
                """
            )
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("is_in_label column ensure: %s", exc)

    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_omop_baseline_drug_ae_source
            ON omop_drug_condition_baseline (
                drug_source_value, condition_source_value, source
            )
            """
        )
    )


async def _resolve_or_create_concept(
    conn: AsyncConnection,
    *,
    cache: Dict[Tuple[str, str], int],
    vocabulary_id: str,
    concept_code: str,
    concept_name: str,
    domain_id: str,
    concept_class_id: str,
) -> int:
    key = (vocabulary_id.lower(), _normalize(concept_name))
    if key in cache:
        return cache[key]
    code_key = (vocabulary_id.lower(), concept_code.strip().lower())
    # Prefer existing Athena/MedDRA/RxNorm match by name
    result = await conn.execute(
        text(
            """
            SELECT concept_id FROM omop_concept
            WHERE LOWER(vocabulary_id) = LOWER(:vocab)
              AND LOWER(concept_name) = LOWER(:name)
            LIMIT 1
            """
        ),
        {"vocab": vocabulary_id, "name": concept_name},
    )
    found = result.scalar_one_or_none()
    if found is not None:
        cid = int(found)
        cache[key] = cid
        return cid

    result = await conn.execute(
        text(
            """
            SELECT concept_id FROM omop_concept
            WHERE LOWER(concept_name) = LOWER(:name)
              AND vocabulary_id IN ('RxNorm', 'RxNorm Extension', 'MedDRA', 'SNOMED', 'SIDER')
            ORDER BY CASE vocabulary_id
                WHEN 'RxNorm' THEN 1
                WHEN 'MedDRA' THEN 1
                ELSE 2
            END
            LIMIT 1
            """
        ),
        {"name": concept_name},
    )
    found = result.scalar_one_or_none()
    if found is not None:
        cid = int(found)
        cache[key] = cid
        return cid

    cid = _stable_concept_id(vocabulary_id, concept_code or concept_name)
    await conn.execute(
        text(
            """
            INSERT INTO omop_concept (
                concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
                standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
            ) VALUES (
                :concept_id, :concept_name, :domain_id, :vocabulary_id, :concept_class_id,
                'S', :concept_code, DATE '1970-01-01', DATE '2099-12-31', NULL
            )
            ON CONFLICT (concept_id) DO NOTHING
            """
        ),
        {
            "concept_id": cid,
            "concept_name": concept_name[:255],
            "domain_id": domain_id,
            "vocabulary_id": vocabulary_id,
            "concept_class_id": concept_class_id,
            "concept_code": (concept_code or concept_name)[:50],
        },
    )
    cache[key] = cid
    cache[code_key] = cid
    return cid


async def load_sider(
    *,
    sider_tsv: Optional[Path] = None,
    database_url: Optional[str] = None,
    project_id: Optional[int] = None,
    force_fixture: bool = False,
    batch_size: int = 1_000,
) -> dict[str, Any]:
    load_dotenv()
    raw = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise EnvironmentError("DATABASE_URL is required for SIDER load")

    if force_fixture or sider_tsv is None:
        path = ensure_surrogate_tsv()
    else:
        path = Path(sider_tsv)
        if not path.is_file():
            LOGGER.warning("SIDER TSV not found at %s — using surrogate", path)
            path = ensure_surrogate_tsv()

    pairs = read_sider_pairs(path)
    engine: AsyncEngine = create_async_engine_normalized(raw)
    inserted = updated = skipped = 0
    cache: Dict[Tuple[str, str], int] = {}

    try:
        async with engine.begin() as conn:
            await _ensure_baseline_schema(conn)

        for start in range(0, len(pairs), batch_size):
            chunk = pairs[start : start + batch_size]
            async with engine.begin() as conn:
                for pair in chunk:
                    try:
                        drug_code = pair["stitch_id"] or f"SIDER:{pair['drug_name'].upper()[:40]}"
                        drug_cid = await _resolve_or_create_concept(
                            conn,
                            cache=cache,
                            vocabulary_id="SIDER",
                            concept_code=drug_code[:50],
                            concept_name=pair["drug_display"] or pair["drug_name"],
                            domain_id="Drug",
                            concept_class_id="Ingredient",
                        )
                        ae_code = pair["umls_cui"] or f"SIDER_SE:{pair['side_effect'].upper()[:40]}"
                        cond_cid = await _resolve_or_create_concept(
                            conn,
                            cache=cache,
                            vocabulary_id="MedDRA",
                            concept_code=ae_code[:50],
                            concept_name=pair["side_effect"],
                            domain_id="Condition",
                            concept_class_id="PT",
                        )
                        result = await conn.execute(
                            text(
                                """
                                INSERT INTO omop_drug_condition_baseline (
                                    drug_concept_id, condition_concept_id,
                                    drug_source_value, condition_source_value,
                                    is_expected_baseline, is_in_label,
                                    source, project_id, created_at
                                ) VALUES (
                                    :drug_concept_id, :condition_concept_id,
                                    :drug_source_value, :condition_source_value,
                                    TRUE, TRUE,
                                    'SIDER 4.1', :project_id, NOW()
                                )
                                ON CONFLICT (drug_source_value, condition_source_value, source)
                                DO UPDATE SET
                                    is_expected_baseline = TRUE,
                                    is_in_label = TRUE,
                                    drug_concept_id = EXCLUDED.drug_concept_id,
                                    condition_concept_id = EXCLUDED.condition_concept_id
                                RETURNING (xmax = 0) AS inserted
                                """
                            ),
                            {
                                "drug_concept_id": drug_cid,
                                "condition_concept_id": cond_cid,
                                "drug_source_value": pair["drug_name"][:256],
                                "condition_source_value": _normalize(pair["side_effect"])[:256],
                                "project_id": project_id,
                            },
                        )
                        row = result.first()
                        if row and bool(row[0]):
                            inserted += 1
                        else:
                            updated += 1
                    except Exception as exc:  # noqa: BLE001
                        skipped += 1
                        LOGGER.warning(
                            "SIDER pair dropped %s / %s: %s",
                            pair.get("drug_name"),
                            pair.get("side_effect"),
                            exc,
                        )
            LOGGER.info(
                "SIDER batch %d–%d — inserted=%d updated=%d skipped=%d",
                start,
                start + len(chunk) - 1,
                inserted,
                updated,
                skipped,
            )

        return {
            "source_path": str(path),
            "pairs_parsed": len(pairs),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "is_in_label": True,
            "is_expected_baseline": True,
        }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load SIDER 4.1 in-label AE baselines into OMOP"
    )
    parser.add_argument(
        "--sider-tsv",
        type=Path,
        default=None,
        help="Path to meddra_all_label_se.tsv / meddra_all_se.tsv",
    )
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--force-fixture", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)
    try:
        result = asyncio.run(
            load_sider(
                sider_tsv=args.sider_tsv,
                database_url=args.database_url,
                project_id=args.project_id,
                force_fixture=args.force_fixture,
                batch_size=args.batch_size,
            )
        )
        LOGGER.info("SIDER load complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("load_sider failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
