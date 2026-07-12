"""FDA boxed (black-box) warning registry — curated offline surrogate.

A boxed warning is the FDA's strongest labelling caution. When a detected
(drug -> event) safety signal involves a drug that carries a boxed warning, we
flag it — and, importantly, distinguish whether the boxed warning *covers this
event*:

  * "known-serious (boxed)"       -> drug is boxed AND this event is the boxed harm
  * "boxed drug, different event" -> drug is boxed but for a DIFFERENT harm
  * "not boxed"                   -> drug carries no boxed warning

This novelty lens matters for signal prioritisation: a strong signal on a drug
that is NOT boxed for that event is far more likely to be a genuinely emerging
issue than one that merely re-confirms an existing boxed warning.

Curated, OFFLINE table (no external API, no key). Faithful to publicly
documented FDA boxed warnings but a teaching/demo surrogate, not the label.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..nlp.lexicons import normalize_drug

# --------------------------------------------------------------------------- #
# Curated FDA boxed-warning associations.
#   drugs     : generic names this entry applies to (lowercase)
#   topics    : short human labels for the boxed warning(s)
#   reactions : normalized reaction surface forms + MedDRA PTs (lowercase) that
#               the boxed harm manifests as
#   socs      : System Organ Class codes that also qualify (family fallback)
#   year      : approximate year the boxed warning was added (context only)
# --------------------------------------------------------------------------- #
BOXED_TABLE: List[dict] = [
    {
        "id": "isotretinoin",
        "drugs": ["isotretinoin"],
        "topics": ["Embryo-fetal toxicity / teratogenicity (iPLEDGE)"],
        "reactions": {"pregnancy", "birth defect", "birth defects", "teratogenicity",
                      "fetal harm", "miscarriage", "congenital malformation"},
        "socs": {"PREG"},
        "year": 1982, "source": "FDA boxed warning",
    },
    {
        "id": "nsaids",
        "drugs": ["ibuprofen", "diclofenac", "naproxen", "meloxicam", "celecoxib",
                  "ketorolac", "indomethacin", "loxoprofen", "etoricoxib", "aceclofenac"],
        "topics": ["Serious cardiovascular thrombotic events (MI, stroke)",
                   "Serious GI bleeding, ulceration & perforation"],
        "reactions": {"gastrointestinal bleeding", "gi bleeding", "gastrointestinal haemorrhage",
                      "gastrointestinal hemorrhage", "haemorrhage", "hemorrhage", "melena",
                      "peptic ulcer", "gastric ulcer", "ulcer", "gi perforation", "perforation",
                      "abdominal pain", "dyspepsia", "myocardial infarction", "heart attack",
                      "stroke", "thrombosis"},
        "socs": {"GI"},
        "year": 2005, "source": "FDA boxed warning",
    },
    {
        "id": "warfarin",
        "drugs": ["warfarin"],
        "topics": ["Major or fatal bleeding"],
        "reactions": {"bleeding", "haemorrhage", "hemorrhage", "bruising", "nosebleed",
                      "blood in urine", "blood in stool", "gum bleeding", "haematoma"},
        "socs": {"BLOOD"},
        "year": 2007, "source": "FDA boxed warning",
    },
    {
        "id": "rivaroxaban",
        "drugs": ["rivaroxaban", "apixaban", "dabigatran", "edoxaban"],
        "topics": ["Increased thrombotic risk on premature discontinuation",
                   "Spinal / epidural haematoma with neuraxial procedures"],
        "reactions": {"thrombosis", "stroke", "spinal haematoma", "spinal hematoma",
                      "epidural haematoma", "clot", "pulmonary embolism"},
        "socs": {"VASC"},
        "year": 2011, "source": "FDA boxed warning",
    },
    {
        "id": "ssri_suicidality",
        "drugs": ["sertraline", "paroxetine", "fluoxetine", "citalopram", "escitalopram",
                  "fluvoxamine", "venlafaxine", "duloxetine", "amitriptyline",
                  "nortriptyline", "imipramine", "bupropion", "mirtazapine"],
        "topics": ["Suicidal thoughts & behaviour in children / adolescents / young adults"],
        "reactions": {"suicidal ideation", "suicidal thoughts", "suicide", "self-harm",
                      "self harm", "self-injury", "depression", "worsening depression",
                      "agitation", "suicidality"},
        "socs": {"PSYCH"},
        "year": 2004, "source": "FDA boxed warning",
    },
    {
        "id": "carbamazepine",
        "drugs": ["carbamazepine"],
        "topics": ["Serious dermatologic reactions (SJS/TEN)",
                   "Aplastic anaemia & agranulocytosis"],
        "reactions": {"rash", "skin rash", "stevens-johnson syndrome", "sjs", "ten",
                      "toxic epidermal necrolysis", "dress", "peeling skin", "blisters",
                      "aplastic anaemia", "aplastic anemia", "agranulocytosis",
                      "neutropenia", "blood dyscrasia"},
        "socs": {"SKIN", "BLOOD"},
        "year": 2007, "source": "FDA boxed warning",
    },
    {
        "id": "valproate",
        "drugs": ["valproate", "valproic acid", "divalproex", "sodium valproate"],
        "topics": ["Hepatotoxicity", "Pancreatitis", "Fetal toxicity (teratogenicity)"],
        "reactions": {"hepatotoxicity", "liver damage", "liver failure", "hepatic injury",
                      "jaundice", "pancreatitis", "birth defect", "teratogenicity",
                      "neural tube defect"},
        "socs": {"HEPB", "GI", "PREG"},
        "year": 1978, "source": "FDA boxed warning",
    },
    {
        "id": "clozapine",
        "drugs": ["clozapine"],
        "topics": ["Severe neutropenia / agranulocytosis", "Seizures", "Myocarditis",
                   "Orthostatic hypotension"],
        "reactions": {"agranulocytosis", "neutropenia", "seizure", "convulsion",
                      "myocarditis", "fainting", "syncope", "orthostatic hypotension"},
        "socs": {"BLOOD", "CARD", "NERV"},
        "year": 1990, "source": "FDA boxed warning",
    },
    {
        "id": "codeine_tramadol",
        "drugs": ["codeine", "tramadol"],
        "topics": ["Life-threatening respiratory depression (esp. children/ultrarapid metabolizers)",
                   "Addiction, abuse & misuse"],
        "reactions": {"respiratory depression", "difficulty breathing", "shortness of breath",
                      "dyspnea", "breathlessness", "somnolence", "sedation", "drowsiness",
                      "overdose", "addiction", "death"},
        "socs": {"RESP"},
        "year": 2017, "source": "FDA boxed warning",
    },
    {
        "id": "fluoroquinolones",
        "drugs": ["ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin",
                  "norfloxacin", "gemifloxacin"],
        "topics": ["Tendinitis & tendon rupture", "Peripheral neuropathy",
                   "CNS effects", "Aortic aneurysm/dissection", "Myasthenia gravis exacerbation"],
        "reactions": {"tendon rupture", "tendinitis", "tendon pain", "peripheral neuropathy",
                      "tingling", "numbness", "aortic aneurysm", "aortic dissection",
                      "muscle weakness"},
        "socs": {"MUSC", "NERV"},
        "year": 2008, "source": "FDA boxed warning",
    },
    {
        "id": "antipsychotics_elderly",
        "drugs": ["quetiapine", "olanzapine", "risperidone", "aripiprazole", "haloperidol",
                  "clozapine", "ziprasidone", "paliperidone"],
        "topics": ["Increased mortality in elderly with dementia-related psychosis"],
        "reactions": {"death", "increased mortality", "sudden death"},
        "socs": set(),
        "year": 2005, "source": "FDA boxed warning",
    },
    {
        "id": "thiazolidinediones",
        "drugs": ["rosiglitazone", "pioglitazone"],
        "topics": ["Congestive heart failure"],
        "reactions": {"heart failure", "cardiac failure", "congestive heart failure",
                      "oedema", "edema", "shortness of breath", "dyspnea"},
        "socs": {"CARD"},
        "year": 2007, "source": "FDA boxed warning",
    },
    {
        "id": "metoclopramide",
        "drugs": ["metoclopramide"],
        "topics": ["Tardive dyskinesia (often irreversible)"],
        "reactions": {"tardive dyskinesia", "involuntary movements", "dystonia",
                      "muscle spasms", "restlessness"},
        "socs": {"NERV"},
        "year": 2009, "source": "FDA boxed warning",
    },
    {
        "id": "montelukast",
        "drugs": ["montelukast"],
        "topics": ["Serious neuropsychiatric events"],
        "reactions": {"depression", "suicidal ideation", "suicidal thoughts", "anxiety",
                      "agitation", "nightmares", "insomnia", "hallucinations",
                      "neuropsychiatric"},
        "socs": {"PSYCH"},
        "year": 2020, "source": "FDA boxed warning",
    },
    {
        "id": "azathioprine",
        "drugs": ["azathioprine", "mercaptopurine", "6-mercaptopurine"],
        "topics": ["Chronic immunosuppression malignancy risk (lymphoma)"],
        "reactions": {"lymphoma", "malignancy", "cancer", "skin cancer"},
        "socs": set(),
        "year": 1988, "source": "FDA boxed warning",
    },
    {
        "id": "amiodarone",
        "drugs": ["amiodarone"],
        "topics": ["Pulmonary toxicity", "Hepatotoxicity", "Proarrhythmia"],
        "reactions": {"pulmonary fibrosis", "pulmonary toxicity", "shortness of breath",
                      "liver damage", "hepatotoxicity", "arrhythmia", "irregular heartbeat"},
        "socs": {"RESP", "HEPB", "CARD"},
        "year": 1985, "source": "FDA boxed warning",
    },
    {
        "id": "methotrexate",
        "drugs": ["methotrexate"],
        "topics": ["Hepatotoxicity", "Myelosuppression", "Pulmonary toxicity",
                   "Serious infections"],
        "reactions": {"liver damage", "hepatotoxicity", "hepatic injury", "myelosuppression",
                      "neutropenia", "pulmonary fibrosis", "pneumonitis", "infection"},
        "socs": {"HEPB", "BLOOD", "RESP"},
        "year": 1988, "source": "FDA boxed warning",
    },
    {
        "id": "testosterone",
        "drugs": ["testosterone"],
        "topics": ["Venous thromboembolism", "Blood pressure increase / CV risk"],
        "reactions": {"thrombosis", "pulmonary embolism", "deep vein thrombosis", "dvt",
                      "blood clot", "stroke"},
        "socs": {"VASC"},
        "year": 2014, "source": "FDA boxed warning",
    },
    {
        "id": "opioids",
        "drugs": ["morphine", "oxycodone", "fentanyl", "hydrocodone", "hydromorphone",
                  "oxymorphone", "methadone", "buprenorphine"],
        "topics": ["Addiction, abuse & misuse", "Life-threatening respiratory depression"],
        "reactions": {"respiratory depression", "difficulty breathing", "somnolence",
                      "sedation", "overdose", "addiction", "death", "shortness of breath"},
        "socs": {"RESP"},
        "year": 2013, "source": "FDA boxed warning",
    },
]

# drug (generic) -> entry index
_INDEX: Dict[str, List[dict]] = {}
for _e in BOXED_TABLE:
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
    """Return a boxed-warning annotation for a (drug, event) pair, or None.

    None means the drug carries no FDA boxed warning in our registry. When
    present, ``covers_event`` says whether the boxed harm matches THIS event, and
    ``novelty`` classifies the signal accordingly.
    """
    generic = (normalize_drug(drug) or "").strip().lower()
    entries = _INDEX.get(generic)
    if not entries:
        return None

    topics: List[str] = []
    covers = False
    matched_reaction = ""
    for entry in entries:
        topics.extend(entry["topics"])
        if _reaction_matches(entry, symptom, pt, soc):
            covers = True
            matched_reaction = matched_reaction or (symptom or pt or "").lower()

    novelty = "known-serious (boxed)" if covers else "boxed drug, different event"
    return {
        "has_boxed": True,
        "covers_event": covers,
        "topics": sorted(set(topics)),
        "matched_reaction": matched_reaction,
        "novelty": novelty,
        "source": entries[0]["source"],
        "drug": generic,
    }


def reference_table() -> dict:
    """Public reference view of the boxed-warning knowledge base."""
    return {
        "count": len(BOXED_TABLE),
        "note": "Curated FDA boxed (black-box) warnings (offline surrogate; not the "
                "official label). A signal is flagged boxed when the drug carries a "
                "boxed warning; 'covers_event' indicates whether the boxed harm matches "
                "the detected event.",
        "warnings": [
            {"drugs": e["drugs"], "topics": e["topics"], "year": e.get("year"),
             "source": e["source"]}
            for e in BOXED_TABLE
        ],
    }
