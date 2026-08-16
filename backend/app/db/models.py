"""VigilAI Phase 1 — OMOP CDM v5.4 SQLAlchemy 2.0 ORM models.

Maps 1:1 to ``schemas/omop_v5_4_ddl.sql``:

* ``concept``
* ``person``
* ``drug_exposure`` (RANGE-partitioned by ``drug_exposure_start_date``)
* ``condition_occurrence`` (RANGE-partitioned by ``condition_start_date``)

All concept / entity identifiers are ``BigInteger`` so RxNorm Extension and
Athena-scale IDs never overflow PostgreSQL ``INTEGER``.

Foreign-key constraints are intentionally omitted on the partitioned clinical
tables: PostgreSQL requires the partition key in unique/PK constraints that
other tables would reference, and application joins use ``person_id`` /
``*_concept_id`` as logical keys. Use the DDL script as the source of truth
for physical constraints.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OmopBase(DeclarativeBase):
    """Declarative base for Phase 1 OMOP CDM tables (unprefixed CDM names)."""


class Concept(OmopBase):
    """OMOP CONCEPT — vocabulary row (drug, condition, gender, …)."""

    __tablename__ = "concept"
    __table_args__ = (
        Index("idx_concept_concept_name", "concept_name"),
        Index("idx_concept_domain_id", "domain_id"),
        Index("idx_concept_vocabulary_id", "vocabulary_id"),
        Index("idx_concept_concept_code", "concept_code"),
        Index("idx_concept_std_class", "standard_concept", "concept_class_id"),
    )

    concept_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    concept_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain_id: Mapped[str] = mapped_column(String(20), nullable=False)
    vocabulary_id: Mapped[str] = mapped_column(String(20), nullable=False)
    concept_class_id: Mapped[str] = mapped_column(String(20), nullable=False)
    standard_concept: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    concept_code: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    invalid_reason: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    def __repr__(self) -> str:
        return (
            f"Concept(concept_id={self.concept_id!r}, "
            f"vocabulary_id={self.vocabulary_id!r}, concept_code={self.concept_code!r})"
        )


class Person(OmopBase):
    """OMOP PERSON — one row per subject (BIGINT person_id)."""

    __tablename__ = "person"
    __table_args__ = (
        Index("idx_person_gender_concept_id", "gender_concept_id"),
        Index("idx_person_race_concept_id", "race_concept_id"),
        Index("idx_person_ethnicity_concept_id", "ethnicity_concept_id"),
        Index("idx_person_location_id", "location_id"),
        Index("idx_person_person_source_value", "person_source_value"),
    )

    person_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    gender_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    year_of_birth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    month_of_birth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day_of_birth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    birth_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    race_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ethnicity_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    location_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    provider_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    care_site_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    person_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gender_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gender_source_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    race_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    race_source_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ethnicity_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ethnicity_source_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"Person(person_id={self.person_id!r}, gender_concept_id={self.gender_concept_id!r})"


class DrugExposure(OmopBase):
    """OMOP DRUG_EXPOSURE — RANGE-partitioned by ``drug_exposure_start_date``."""

    __tablename__ = "drug_exposure"
    __table_args__ = (
        PrimaryKeyConstraint(
            "drug_exposure_id",
            "drug_exposure_start_date",
            name="xpk_drug_exposure",
        ),
        Index("idx_drug_exposure_person_id", "person_id"),
        Index("idx_drug_exposure_drug_concept_id", "drug_concept_id"),
        Index("idx_drug_exposure_start_date", "drug_exposure_start_date"),
        Index("idx_drug_exposure_person_drug", "person_id", "drug_concept_id"),
        Index("idx_drug_exposure_type_concept_id", "drug_type_concept_id"),
        {
            "info": {
                "postgresql_partition_by": "RANGE (drug_exposure_start_date)",
            }
        },
    )

    drug_exposure_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    person_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    drug_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    drug_exposure_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    drug_exposure_start_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    drug_exposure_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    drug_exposure_end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    verbatim_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    drug_type_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stop_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    refills: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    days_supply: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sig: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    route_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    lot_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    provider_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    visit_occurrence_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    visit_detail_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    drug_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    drug_source_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    route_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dose_unit_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return (
            f"DrugExposure(drug_exposure_id={self.drug_exposure_id!r}, "
            f"person_id={self.person_id!r}, drug_concept_id={self.drug_concept_id!r})"
        )


class ConditionOccurrence(OmopBase):
    """OMOP CONDITION_OCCURRENCE — RANGE-partitioned by ``condition_start_date``."""

    __tablename__ = "condition_occurrence"
    __table_args__ = (
        PrimaryKeyConstraint(
            "condition_occurrence_id",
            "condition_start_date",
            name="xpk_condition_occurrence",
        ),
        Index("idx_condition_occurrence_person_id", "person_id"),
        Index("idx_condition_occurrence_concept_id", "condition_concept_id"),
        Index("idx_condition_occurrence_start_date", "condition_start_date"),
        Index(
            "idx_condition_occurrence_person_condition",
            "person_id",
            "condition_concept_id",
        ),
        Index("idx_condition_occurrence_type_concept_id", "condition_type_concept_id"),
        {
            "info": {
                "postgresql_partition_by": "RANGE (condition_start_date)",
            }
        },
    )

    condition_occurrence_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    person_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    condition_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    condition_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    condition_start_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    condition_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    condition_end_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    condition_type_concept_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    condition_status_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stop_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    provider_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    visit_occurrence_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    visit_detail_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    condition_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    condition_source_concept_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    condition_status_source_value: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return (
            f"ConditionOccurrence(condition_occurrence_id={self.condition_occurrence_id!r}, "
            f"person_id={self.person_id!r}, condition_concept_id={self.condition_concept_id!r})"
        )


__all__ = [
    "OmopBase",
    "Concept",
    "Person",
    "DrugExposure",
    "ConditionOccurrence",
]
