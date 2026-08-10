"""Pharmacogenomic (PGx) risk overlay — CPIC / PharmGKB curated surrogate.

When a detected (drug -> event) safety signal corresponds to a well-established,
clinically actionable pharmacogenomic association, we flag it as "genomically
explainable" and attach the responsible gene / variant and the CPIC guidance.

This is a curated, OFFLINE drop-in table (no external API, no key). It is faithful
to publicly documented CPIC guidelines and PharmGKB clinical annotations but is a
teaching/demo surrogate, not a substitute for a clinical PGx decision-support system.

Matching is deliberately precise: a drug alone does not flag PGx — the signal's
reaction must also match the gene-associated toxicity (by surface term, MedDRA PT,
or System Organ Class family), so we don't over-call (e.g. codeine->headache).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..nlp.lexicons import normalize_drug

# --------------------------------------------------------------------------- #
# Curated CPIC / PharmGKB associations.
#   drugs      : generic names this entry applies to (lowercase)
#   gene       : responsible gene
#   allele     : the actionable risk allele / diplotype
#   phenotype  : the at-risk phenotype
#   reactions  : normalized reaction surface forms + MedDRA PTs (lowercase) that
#                this PGx risk manifests as
#   socs       : System Organ Class codes that also qualify (family fallback)
#   recommendation / level / source : CPIC guidance summary + evidence level
# --------------------------------------------------------------------------- #
PGX_TABLE: List[dict] = [
    {
        "id": "abacavir_hlab5701",
        "drugs": ["abacavir"],
        "gene": "HLA-B", "allele": "HLA-B*57:01", "phenotype": "HLA-B*57:01 positive",
        "reactions": {"hypersensitivity", "allergic reaction", "anaphylaxis", "rash",
                      "skin rash", "fever", "drug hypersensitivity"},
        "socs": {"IMMUN", "SKIN"},
        "recommendation": "Do NOT prescribe abacavir to HLA-B*57:01-positive patients — "
                          "high risk of a potentially fatal hypersensitivity reaction.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "carbamazepine_hlab1502",
        "drugs": ["carbamazepine", "oxcarbazepine", "phenytoin", "fosphenytoin"],
        "gene": "HLA-B", "allele": "HLA-B*15:02 (also HLA-A*31:01)",
        "phenotype": "HLA-B*15:02 positive",
        "reactions": {"rash", "skin rash", "peeling skin", "itching", "hives", "urticaria",
                      "blisters", "stevens-johnson syndrome", "sjs", "ten", "dress",
                      "swollen lips", "swollen face", "mouth ulcers"},
        "socs": {"SKIN", "IMMUN"},
        "recommendation": "Avoid carbamazepine/oxcarbazepine in HLA-B*15:02 carriers — "
                          "markedly increased risk of Stevens-Johnson syndrome / TEN.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "allopurinol_hlab5801",
        "drugs": ["allopurinol"],
        "gene": "HLA-B", "allele": "HLA-B*58:01", "phenotype": "HLA-B*58:01 positive",
        "reactions": {"rash", "skin rash", "peeling skin", "itching", "hives", "urticaria",
                      "blisters", "stevens-johnson syndrome", "sjs", "dress",
                      "severe cutaneous adverse reaction"},
        "socs": {"SKIN", "IMMUN"},
        "recommendation": "Consider an alternative to allopurinol in HLA-B*58:01 carriers — "
                          "elevated risk of severe cutaneous adverse reactions (SCAR/SJS).",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "fluoropyrimidine_dpyd",
        "drugs": ["fluorouracil", "5-fluorouracil", "capecitabine", "tegafur"],
        "gene": "DPYD", "allele": "DPYD decreased/no-function variants",
        "phenotype": "DPYD intermediate / poor metabolizer",
        "reactions": {"diarrhea", "diarrhoea", "mouth ulcers", "nausea", "vomiting",
                      "bleeding", "bruising", "fatigue", "fever", "mucositis",
                      "neutropenia", "myelosuppression"},
        "socs": {"GI", "BLOOD"},
        "recommendation": "Reduce starting dose (or avoid) in DPYD poor/intermediate "
                          "metabolizers — risk of severe, potentially fatal fluoropyrimidine toxicity.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "thiopurine_tpmt_nudt15",
        "drugs": ["azathioprine", "mercaptopurine", "6-mercaptopurine", "thioguanine"],
        "gene": "TPMT / NUDT15", "allele": "TPMT/NUDT15 no-function alleles",
        "phenotype": "TPMT/NUDT15 intermediate / poor metabolizer",
        "reactions": {"bleeding", "bruising", "fatigue", "fever", "infection",
                      "mouth ulcers", "neutropenia", "myelosuppression", "hair loss", "alopecia"},
        "socs": {"BLOOD"},
        "recommendation": "Substantially reduce thiopurine dose in TPMT/NUDT15 poor "
                          "metabolizers — high risk of life-threatening myelosuppression.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "codeine_cyp2d6",
        "drugs": ["codeine", "tramadol"],
        "gene": "CYP2D6", "allele": "CYP2D6 ultrarapid / poor metabolizer",
        "phenotype": "CYP2D6 ultrarapid (toxicity) or poor (poor analgesia) metabolizer",
        "reactions": {"drowsiness", "somnolence", "sedation", "shortness of breath",
                      "difficulty breathing", "dyspnea", "breathlessness", "nausea",
                      "vomiting", "dizziness", "confusion"},
        "socs": {"RESP", "NERV"},
        "recommendation": "Avoid codeine/tramadol in CYP2D6 ultrarapid metabolizers "
                          "(risk of opioid toxicity / respiratory depression) and in poor "
                          "metabolizers (inadequate analgesia).",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "warfarin_cyp2c9_vkorc1",
        "drugs": ["warfarin", "acenocoumarol"],
        "gene": "CYP2C9 / VKORC1", "allele": "CYP2C9 *2/*3 + VKORC1 -1639G>A",
        "phenotype": "CYP2C9/VKORC1 high-sensitivity genotype",
        "reactions": {"bleeding", "bruising", "nosebleed", "blood in urine",
                      "blood in stool", "gum bleeding", "haemorrhage", "hemorrhage"},
        "socs": {"BLOOD"},
        "recommendation": "Use genotype-guided warfarin dosing — CYP2C9/VKORC1 variants "
                          "lower dose requirement and raise bleeding risk.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "simvastatin_slco1b1",
        "drugs": ["simvastatin", "atorvastatin"],
        "gene": "SLCO1B1", "allele": "SLCO1B1 c.521T>C (*5)",
        "phenotype": "SLCO1B1 decreased-function",
        "reactions": {"muscle pain", "myalgia", "muscle weakness", "muscle cramps",
                      "dark urine", "rhabdomyolysis", "myopathy"},
        "socs": {"MUSC"},
        "recommendation": "Prefer a lower dose or alternative statin in SLCO1B1 "
                          "decreased-function carriers — increased myopathy/rhabdomyolysis risk.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "clopidogrel_cyp2c19",
        "drugs": ["clopidogrel"],
        "gene": "CYP2C19", "allele": "CYP2C19 loss-of-function (*2/*3)",
        "phenotype": "CYP2C19 intermediate / poor metabolizer",
        "reactions": {"chest pain", "stroke", "thrombosis", "irregular heartbeat",
                      "arrhythmia", "clot"},
        "socs": {"CARD", "VASC"},
        "recommendation": "Consider prasugrel/ticagrelor in CYP2C19 poor metabolizers — "
                          "clopidogrel is under-activated, raising thrombotic risk.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "ssri_cyp2d6",
        "drugs": ["paroxetine", "fluoxetine", "amitriptyline", "nortriptyline"],
        "gene": "CYP2D6", "allele": "CYP2D6 poor / ultrarapid metabolizer",
        "phenotype": "CYP2D6 non-normal metabolizer",
        "reactions": {"nausea", "dizziness", "drowsiness", "somnolence", "tremor",
                      "insomnia", "dry mouth", "sweating"},
        "socs": {"NERV", "PSYCH"},
        "recommendation": "Adjust dose or select an alternative antidepressant based on "
                          "CYP2D6 phenotype to balance efficacy and tolerability.",
        "level": "CPIC Level A/B", "source": "CPIC / PharmGKB",
    },
    {
        "id": "ondansetron_cyp2d6",
        "drugs": ["ondansetron", "tropisetron"],
        "gene": "CYP2D6", "allele": "CYP2D6 ultrarapid metabolizer (gene duplication)",
        "phenotype": "CYP2D6 ultrarapid metabolizer",
        "reactions": {"vomiting", "nausea", "drug ineffective", "lack of efficacy",
                      "treatment failure", "retching"},
        "socs": {"GI"},
        "recommendation": "Select an alternative antiemetic not metabolised by CYP2D6 in "
                          "ultrarapid metabolizers — ondansetron is cleared too fast to "
                          "control emesis reliably.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "ppi_cyp2c19",
        "drugs": ["omeprazole", "esomeprazole", "lansoprazole", "pantoprazole", "dexlansoprazole"],
        "gene": "CYP2C19", "allele": "CYP2C19 loss-of-function or increased-function alleles",
        "phenotype": "CYP2C19 poor / rapid / ultrarapid metabolizer",
        "reactions": {"drug ineffective", "lack of efficacy", "treatment failure",
                      "heartburn", "reflux", "diarrhea", "diarrhoea", "headache"},
        "socs": {"GI"},
        "recommendation": "Increase dose in CYP2C19 rapid/ultrarapid metabolizers (risk of "
                          "therapeutic failure); consider dose reduction on chronic therapy "
                          "in poor metabolizers.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "voriconazole_cyp2c19",
        "drugs": ["voriconazole"],
        "gene": "CYP2C19", "allele": "CYP2C19 poor / ultrarapid metabolizer",
        "phenotype": "CYP2C19 non-normal metabolizer",
        "reactions": {"visual disturbance", "blurred vision", "hallucination",
                      "confusion", "hepatic injury", "liver damage", "abnormal liver function",
                      "drug ineffective", "treatment failure"},
        "socs": {"NERV", "HEPAT", "EYE"},
        "recommendation": "Choose an alternative azole in CYP2C19 ultrarapid metabolizers "
                          "(subtherapeutic exposure) and in poor metabolizers (toxic exposure, "
                          "hepatic and visual adverse events).",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
    {
        "id": "tacrolimus_cyp3a5",
        "drugs": ["tacrolimus"],
        "gene": "CYP3A5", "allele": "CYP3A5 *1 (expresser)",
        "phenotype": "CYP3A5 normal / intermediate metabolizer (expresser)",
        "reactions": {"drug ineffective", "lack of efficacy", "treatment failure",
                      "transplant rejection", "rejection", "kidney injury",
                      "renal impairment", "tremor"},
        "socs": {"RENAL", "IMMUN"},
        "recommendation": "Increase the starting dose in CYP3A5 expressers — standard dosing "
                          "gives subtherapeutic trough concentrations and rejection risk. "
                          "Guide with therapeutic drug monitoring.",
        "level": "CPIC Level A", "source": "CPIC / PharmGKB",
    },
]

# drug (generic) -> entries index
_INDEX: Dict[str, List[dict]] = {}
for _e in PGX_TABLE:
    for _d in _e["drugs"]:
        _INDEX.setdefault(_d, []).append(_e)


def _reaction_matches(entry: dict, symptom: str, pt: Optional[str], soc: Optional[str]) -> bool:
    reactions = entry["reactions"]
    if symptom and symptom.lower() in reactions:
        return True
    if pt and pt.lower() in reactions:
        return True
    if soc and soc in entry.get("socs", set()):
        return True
    return False


def match(drug: str, symptom: str, pt: Optional[str] = None,
          soc: Optional[str] = None) -> Optional[dict]:
    """Return a PGx annotation for a (drug, event) pair, or None.

    ``drug`` may be a brand/casual mention (normalized to generic here). ``symptom``
    is the normalized reaction surface; ``pt``/``soc`` are the MedDRA-style Preferred
    Term and System Organ Class code (optional, improve recall).
    """
    generic = (normalize_drug(drug) or "").strip().lower()
    entries = _INDEX.get(generic)
    if not entries:
        return None
    for entry in entries:
        if _reaction_matches(entry, symptom, pt, soc):
            return {
                "pgx_actionable": True,
                "gene": entry["gene"],
                "allele": entry["allele"],
                "phenotype": entry["phenotype"],
                "recommendation": entry["recommendation"],
                "level": entry["level"],
                "source": entry["source"],
                "matched_reaction": (symptom or pt or "").lower(),
            }
    return None


def reference_table() -> dict:
    """Public reference view of the PGx knowledge base (for a reference UI)."""
    return {
        "count": len(PGX_TABLE),
        "note": "Curated CPIC/PharmGKB associations (offline surrogate; not clinical "
                "decision support). A signal is flagged PGx-actionable only when the "
                "drug AND its reaction match a documented gene-associated toxicity.",
        "associations": [
            {
                "drugs": e["drugs"], "gene": e["gene"], "allele": e["allele"],
                "phenotype": e["phenotype"], "recommendation": e["recommendation"],
                "level": e["level"], "source": e["source"],
            }
            for e in PGX_TABLE
        ],
    }
