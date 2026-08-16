"""Disproportionality math over ``omop_signal_summary`` (PRR / ROR + 95% CI).

Builds a 2×2 contingency table for a target drug against every co-reported
adverse event using Haldane–Anscombe (+0.5) continuity correction, matching
VigilAI signal-detection invariants (Evans PRR, van Puijenbroek ROR, Yates χ²).
"""
from __future__ import annotations

import logging
import math
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LOGGER = logging.getLogger("vigilai.api.statistics")

CORRECTION = 0.5  # Haldane–Anscombe
_Z = 1.96         # 95% normal quantile


class ContingencyTable(BaseModel):
    a: float = Field(description="Target drug + specific AE")
    b: float = Field(description="Target drug + other AEs")
    c: float = Field(description="Other drugs + specific AE")
    d: float = Field(description="Other drugs + other AEs")


class AeDisproportionality(BaseModel):
    condition_concept_id: int
    condition_name: Optional[str] = None
    meddra_pt: Optional[str] = None
    exposure_count: int = 0
    contingency: ContingencyTable
    prr: float
    prr_ci_low: float
    prr_ci_high: float
    ror: float
    ror_ci_low: float
    ror_ci_high: float
    chi_square: float
    strength: str
    sdr_flag: bool = False


class DrugDisproportionalityReport(BaseModel):
    drug_concept_id: int
    drug_total_exposures: int = 0
    grand_total: int = 0
    adverse_events: List[AeDisproportionality] = Field(default_factory=list)
    source: str = "omop_signal_summary"
    notes: List[str] = Field(default_factory=list)


def _chi_square_yates(a: float, b: float, c: float, d: float) -> float:
    n = a + b + c + d
    if n <= 0:
        return 0.0
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    if min(row1, row2, col1, col2) <= 0:
        return 0.0

    def term(observed: float, expected: float) -> float:
        if expected <= 0:
            return 0.0
        return (abs(observed - expected) - 0.5) ** 2 / expected

    ea = row1 * col1 / n
    eb = row1 * col2 / n
    ec = row2 * col1 / n
    ed = row2 * col2 / n
    return round(term(a, ea) + term(b, eb) + term(c, ec) + term(d, ed), 3)


def _prr_ci(a: float, b: float, c: float, d: float) -> tuple[float, float, float]:
    prr = (a / (a + b)) / (c / (c + d))
    se = math.sqrt(max(1e-9, 1 / a - 1 / (a + b) + 1 / c - 1 / (c + d)))
    ln = math.log(max(prr, 1e-12))
    return (
        round(prr, 3),
        round(math.exp(ln - _Z * se), 3),
        round(math.exp(ln + _Z * se), 3),
    )


def _ror_ci(a: float, b: float, c: float, d: float) -> tuple[float, float, float]:
    ror = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    ln = math.log(max(ror, 1e-12))
    return (
        round(ror, 3),
        round(math.exp(ln - _Z * se), 3),
        round(math.exp(ln + _Z * se), 3),
    )


def _strength(prr: float, chi2: float, count: int) -> str:
    if prr >= 2 and chi2 >= 4 and count >= 3:
        return "STRONG"
    if prr >= 1.5 and count >= 2:
        return "MODERATE"
    return "WEAK"


def _is_sdr(prr_low: float, chi2: float, count: int) -> bool:
    return bool(prr_low >= 1.0 and chi2 >= 4 and count >= 3)


def compute_pair_metrics(
    a_raw: float,
    b_raw: float,
    c_raw: float,
    d_raw: float,
) -> dict[str, Any]:
    """PRR/ROR/χ² for one 2×2 table with Haldane–Anscombe correction."""
    a = float(a_raw)
    b = float(b_raw)
    c = float(c_raw)
    d = float(d_raw)
    aa, bb, cc, dd = a + CORRECTION, b + CORRECTION, c + CORRECTION, d + CORRECTION
    prr, prr_lo, prr_hi = _prr_ci(aa, bb, cc, dd)
    ror, ror_lo, ror_hi = _ror_ci(aa, bb, cc, dd)
    chi2 = _chi_square_yates(a, b, c, d)
    strength = _strength(prr, chi2, int(a))
    return {
        "contingency": ContingencyTable(a=a, b=b, c=c, d=d),
        "prr": prr,
        "prr_ci_low": prr_lo,
        "prr_ci_high": prr_hi,
        "ror": ror,
        "ror_ci_low": ror_lo,
        "ror_ci_high": ror_hi,
        "chi_square": chi2,
        "strength": strength,
        "sdr_flag": _is_sdr(prr_lo, chi2, int(a)),
    }


async def _fetch_summary_rows(session: AsyncSession) -> List[dict[str, Any]]:
    """Load drug×condition exposure counts from the matview (or staging fallback)."""
    try:
        result = await session.execute(
            text(
                """
                SELECT drug_concept_id, condition_concept_id, exposure_count
                FROM omop_signal_summary
                WHERE drug_concept_id IS NOT NULL
                  AND condition_concept_id IS NOT NULL
                  AND exposure_count > 0
                """
            )
        )
        rows = [dict(r) for r in result.mappings().all()]
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        LOGGER.info("omop_signal_summary unavailable (%s) — staging fallback", exc)

    # Fallback: rebuild counts from OMOP staging tables
    try:
        result = await session.execute(
            text(
                """
                SELECT
                    COALESCE(de.drug_concept_id_int, 0) AS drug_concept_id,
                    COALESCE(co.condition_concept_id_int, 0) AS condition_concept_id,
                    COUNT(DISTINCT de.person_id) AS exposure_count
                FROM omop_drug_exposure AS de
                INNER JOIN omop_condition_occurrence AS co
                    ON co.person_id = de.person_id
                WHERE COALESCE(de.drug_concept_id_int, 0) <> 0
                  AND COALESCE(co.condition_concept_id_int, 0) <> 0
                GROUP BY 1, 2
                """
            )
        )
        return [dict(r) for r in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Staging disproportionality fallback failed: %s", exc)
        return []


async def _condition_names(
    session: AsyncSession, concept_ids: Sequence[int]
) -> dict[int, str]:
    if not concept_ids:
        return {}
    unique_ids = list({int(c) for c in concept_ids})
    try:
        from sqlalchemy import bindparam

        stmt = text(
            """
            SELECT concept_id, concept_name
            FROM omop_concept
            WHERE concept_id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True))
        result = await session.execute(stmt, {"ids": unique_ids})
        return {int(r["concept_id"]): str(r["concept_name"]) for r in result.mappings()}
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("Bulk concept name lookup failed (%s); per-id fallback", exc)
        out: dict[int, str] = {}
        for cid in unique_ids:
            try:
                result = await session.execute(
                    text(
                        "SELECT concept_name FROM omop_concept WHERE concept_id = :cid"
                    ),
                    {"cid": cid},
                )
                name = result.scalar_one_or_none()
                if name:
                    out[int(cid)] = str(name)
            except Exception:
                continue
        return out


async def calculate_prr_ror(
    drug_concept_id: int,
    session: AsyncSession,
    *,
    min_count: int = 1,
) -> DrugDisproportionalityReport:
    """Compute PRR/ROR for every AE co-reported with ``drug_concept_id``.

    Contingsency cells (unique-patient exposure counts from the matview):

    * **A** — target drug + specific AE
    * **B** — target drug + all other AEs
    * **C** — all other drugs + specific AE
    * **D** — all other drugs + all other AEs
    """
    notes: List[str] = []
    target = int(drug_concept_id)
    rows = await _fetch_summary_rows(session)
    source = "omop_signal_summary"

    if not rows:
        notes.append(
            "No rows in omop_signal_summary / staging — run Phase 2 ETL "
            "(``python -m app.etl_pipeline.run_pipeline``) or FAERS sync."
        )
        return DrugDisproportionalityReport(
            drug_concept_id=target,
            adverse_events=[],
            source="empty",
            notes=notes,
        )

    # Detect fallback source heuristically
    if any("drug_concept_id" in r for r in rows):
        # already set
        pass

    grand_total = sum(int(r["exposure_count"] or 0) for r in rows)
    drug_rows = [r for r in rows if int(r["drug_concept_id"]) == target]
    if not drug_rows:
        notes.append(
            f"Drug concept_id={target} has no co-reported AEs in the summary view."
        )
        return DrugDisproportionalityReport(
            drug_concept_id=target,
            grand_total=grand_total,
            adverse_events=[],
            source=source,
            notes=notes,
        )

    drug_total = sum(int(r["exposure_count"] or 0) for r in drug_rows)

    # Pre-aggregate AE totals across all drugs
    ae_totals: dict[int, int] = {}
    for r in rows:
        cid = int(r["condition_concept_id"])
        ae_totals[cid] = ae_totals.get(cid, 0) + int(r["exposure_count"] or 0)

    names = await _condition_names(
        session, [int(r["condition_concept_id"]) for r in drug_rows]
    )

    events: List[AeDisproportionality] = []
    for r in drug_rows:
        cond_id = int(r["condition_concept_id"])
        a = float(int(r["exposure_count"] or 0))
        if a < min_count:
            continue
        b = float(drug_total) - a
        c = float(ae_totals.get(cond_id, 0)) - a
        d = float(grand_total) - a - b - c
        # Guard negative drift from overlapping person double-counts
        b = max(0.0, b)
        c = max(0.0, c)
        d = max(0.0, d)

        metrics = compute_pair_metrics(a, b, c, d)
        label = names.get(cond_id)
        events.append(
            AeDisproportionality(
                condition_concept_id=cond_id,
                condition_name=label,
                meddra_pt=label,
                exposure_count=int(a),
                contingency=metrics["contingency"],
                prr=metrics["prr"],
                prr_ci_low=metrics["prr_ci_low"],
                prr_ci_high=metrics["prr_ci_high"],
                ror=metrics["ror"],
                ror_ci_low=metrics["ror_ci_low"],
                ror_ci_high=metrics["ror_ci_high"],
                chi_square=metrics["chi_square"],
                strength=metrics["strength"],
                sdr_flag=metrics["sdr_flag"],
            )
        )

    events.sort(key=lambda e: (e.prr, e.exposure_count, e.ror), reverse=True)

    if not events:
        notes.append("No AE pairs met the minimum exposure count.")

    return DrugDisproportionalityReport(
        drug_concept_id=target,
        drug_total_exposures=drug_total,
        grand_total=grand_total,
        adverse_events=events,
        source=source,
        notes=notes,
    )
