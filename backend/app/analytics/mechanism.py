"""Mechanistic plausibility scoring — curated offline pharmacology knowledge base.

Turns WHO-UMC's qualitative "biological plausibility" (a Bradford Hill viewpoint)
into a computed signal dimension: does the drug's molecular target / mechanism of
action plausibly explain the observed adverse event?

Each entry links a drug class to its key target/MoA and the adverse events that
mechanism is expected to produce. `assess(drug, event, pt, soc)` returns whether the
detected (drug -> event) pair is mechanistically plausible, with the target/MoA and a
plain-English explanation.

Curated, OFFLINE (no external API, no key). Faithful to well-documented pharmacology
(the kind surfaced by Open Targets / ChEMBL target-safety data) but a teaching/demo
surrogate, not a curated regulatory knowledge base.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..nlp.lexicons import normalize_drug

# --------------------------------------------------------------------------- #
# Curated mechanism -> adverse-event knowledge base.
#   drugs       : generic names this MoA entry applies to (lowercase)
#   target      : molecular target / mechanism of action (short)
#   explanation : plain-English "why this event is mechanistically expected"
#   reactions   : normalized reaction surface forms + MedDRA PTs (lowercase)
#   socs        : System Organ Class codes that also qualify (family fallback)
#   confidence  : high | medium | low  (strength of the mechanistic link)
# --------------------------------------------------------------------------- #
MECHANISM_TABLE: List[dict] = [
    {
        "id": "statin_hmgcoa",
        "drugs": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
                  "lovastatin", "fluvastatin", "pitavastatin"],
        "target": "HMG-CoA reductase inhibition",
        "explanation": "Statins inhibit HMG-CoA reductase, depleting mevalonate-pathway "
                       "products in myocytes; this impairs muscle-cell energetics and "
                       "membrane integrity, a well-established cause of myopathy.",
        "reactions": {"myalgia", "muscle pain", "myopathy", "rhabdomyolysis",
                      "muscle weakness", "muscle cramp", "cramp", "back pain"},
        "socs": {"MUSC"}, "confidence": "high",
    },
    {
        "id": "nsaid_cox",
        "drugs": ["ibuprofen", "naproxen", "diclofenac", "meloxicam", "celecoxib",
                  "ketorolac", "indomethacin", "loxoprofen", "etoricoxib", "aceclofenac",
                  "aspirin"],
        "target": "Cyclooxygenase (COX-1/COX-2) inhibition",
        "explanation": "COX inhibition reduces cytoprotective gastric prostaglandins, "
                       "promoting mucosal injury, ulceration and GI bleeding; COX-2 "
                       "selectivity also shifts the thrombotic balance.",
        "reactions": {"gastrointestinal bleeding", "gi bleeding", "gastrointestinal haemorrhage",
                      "haemorrhage", "hemorrhage", "peptic ulcer", "gastric ulcer", "ulcer",
                      "dyspepsia", "abdominal pain", "gastritis", "nausea", "melena",
                      "gi perforation", "perforation", "oedema", "renal impairment"},
        "socs": {"GI"}, "confidence": "high",
    },
    {
        "id": "anticoagulant",
        "drugs": ["warfarin", "rivaroxaban", "apixaban", "dabigatran", "edoxaban",
                  "heparin", "enoxaparin", "acenocoumarol", "phenprocoumon"],
        "target": "Anticoagulation (Factor Xa / thrombin / VKORC1)",
        "explanation": "By impairing clotting-factor activity these agents directly reduce "
                       "haemostatic capacity, so haemorrhage is the on-target, mechanistically "
                       "expected adverse effect.",
        "reactions": {"haemorrhage", "hemorrhage", "bleeding", "bruising", "epistaxis",
                      "nosebleed", "haematoma", "blood in urine", "blood in stool",
                      "gum bleeding", "gastrointestinal bleeding"},
        "socs": {"BLOOD", "VASC"}, "confidence": "high",
    },
    {
        "id": "herg_qt",
        "drugs": ["amiodarone", "sotalol", "haloperidol", "citalopram", "escitalopram",
                  "ondansetron", "azithromycin", "moxifloxacin", "methadone", "quetiapine",
                  "domperidone", "erythromycin"],
        "target": "hERG (KCNH2) potassium-channel blockade",
        "explanation": "Blockade of the hERG cardiac potassium channel delays "
                       "repolarisation, prolonging the QT interval and predisposing to "
                       "torsade de pointes and related arrhythmias.",
        "reactions": {"qt prolongation", "prolonged qt", "torsade", "torsades de pointes",
                      "arrhythmia", "irregular heartbeat", "palpitations", "ventricular tachycardia",
                      "syncope", "fainting", "cardiac arrest", "sudden death"},
        "socs": {"CARD"}, "confidence": "high",
    },
    {
        "id": "serotonergic",
        "drugs": ["sertraline", "paroxetine", "fluoxetine", "citalopram", "escitalopram",
                  "fluvoxamine", "venlafaxine", "duloxetine", "tramadol", "sumatriptan",
                  "rizatriptan", "linezolid"],
        "target": "Serotonergic activity (5-HT reuptake / agonism)",
        "explanation": "Excess synaptic serotonin from reuptake inhibition or agonism can "
                       "produce a hyperserotonergic state (agitation, tremor, clonus, "
                       "hyperthermia) — the basis of serotonin syndrome.",
        "reactions": {"serotonin syndrome", "agitation", "tremor", "hyperthermia", "clonus",
                      "restlessness", "insomnia", "nausea", "sweating", "confusion"},
        "socs": {"PSYCH"}, "confidence": "medium",
    },
    {
        "id": "d2_antagonist",
        "drugs": ["haloperidol", "risperidone", "olanzapine", "quetiapine", "aripiprazole",
                  "metoclopramide", "prochlorperazine", "chlorpromazine", "paliperidone",
                  "fluphenazine"],
        "target": "Dopamine D2-receptor antagonism",
        "explanation": "Blockade of nigrostriatal D2 receptors produces extrapyramidal motor "
                       "effects (dystonia, parkinsonism, tardive dyskinesia); tuberoinfundibular "
                       "blockade raises prolactin.",
        "reactions": {"tardive dyskinesia", "dystonia", "extrapyramidal", "parkinsonism",
                      "tremor", "akathisia", "restlessness", "involuntary movements",
                      "muscle spasms", "galactorrhoea", "hyperprolactinaemia"},
        "socs": {"NERV"}, "confidence": "high",
    },
    {
        "id": "glp1",
        "drugs": ["semaglutide", "liraglutide", "dulaglutide", "exenatide", "tirzepatide",
                  "lixisenatide"],
        "target": "GLP-1 receptor agonism",
        "explanation": "GLP-1 agonism slows gastric emptying and acts on central appetite "
                       "and vagal pathways, so nausea, vomiting and diarrhoea are direct "
                       "on-target effects; pancreatic stimulation underlies pancreatitis risk.",
        "reactions": {"nausea", "vomiting", "diarrhoea", "diarrhea", "abdominal pain",
                      "pancreatitis", "decreased appetite", "constipation", "dyspepsia"},
        "socs": {"GI"}, "confidence": "high",
    },
    {
        "id": "sglt2",
        "drugs": ["dapagliflozin", "empagliflozin", "canagliflozin", "ertugliflozin"],
        "target": "SGLT2 inhibition (glucosuria)",
        "explanation": "Induced glucosuria creates a sugar-rich genitourinary environment "
                       "(mycotic/UTI risk) and shifts metabolism toward ketogenesis, "
                       "underlying euglycaemic diabetic ketoacidosis.",
        "reactions": {"genital infection", "mycotic infection", "urinary tract infection",
                      "uti", "ketoacidosis", "dka", "dehydration", "thirst", "polyuria"},
        "socs": set(), "confidence": "medium",
    },
    {
        "id": "opioid_mu",
        "drugs": ["morphine", "oxycodone", "codeine", "tramadol", "fentanyl", "hydrocodone",
                  "hydromorphone", "oxymorphone", "methadone", "buprenorphine", "tapentadol"],
        "target": "Mu-opioid receptor agonism",
        "explanation": "Mu-opioid agonism depresses brainstem respiratory drive and CNS "
                       "arousal and slows gut motility — the mechanistic basis of respiratory "
                       "depression, sedation and constipation.",
        "reactions": {"respiratory depression", "difficulty breathing", "shortness of breath",
                      "somnolence", "sedation", "drowsiness", "constipation", "nausea",
                      "dizziness", "overdose"},
        "socs": {"RESP"}, "confidence": "high",
    },
    {
        "id": "beta_blocker",
        "drugs": ["metoprolol", "atenolol", "propranolol", "bisoprolol", "carvedilol",
                  "nebivolol", "labetalol"],
        "target": "Beta-adrenergic receptor antagonism",
        "explanation": "Beta-1 blockade lowers heart rate and contractility (bradycardia, "
                       "hypotension, fatigue); beta-2 blockade can precipitate bronchospasm.",
        "reactions": {"bradycardia", "hypotension", "fatigue", "dizziness", "bronchospasm",
                      "cold extremities", "syncope", "shortness of breath"},
        "socs": {"CARD"}, "confidence": "high",
    },
    {
        "id": "ace_inhibitor",
        "drugs": ["lisinopril", "enalapril", "ramipril", "captopril", "perindopril",
                  "benazepril", "quinapril"],
        "target": "ACE inhibition (bradykinin accumulation)",
        "explanation": "ACE inhibition raises bradykinin, which sensitises airway sensory "
                       "nerves (dry cough) and increases vascular permeability (angioedema); "
                       "reduced aldosterone raises potassium.",
        "reactions": {"cough", "dry cough", "angioedema", "angioneurotic oedema",
                      "hyperkalaemia", "swelling", "throat swelling"},
        "socs": {"RESP"}, "confidence": "high",
    },
    {
        "id": "anticholinergic",
        "drugs": ["oxybutynin", "tolterodine", "amitriptyline", "nortriptyline",
                  "diphenhydramine", "hyoscine", "scopolamine", "solifenacin"],
        "target": "Muscarinic (M) receptor antagonism",
        "explanation": "Antimuscarinic action reduces secretions and smooth-muscle tone, "
                       "causing dry mouth, constipation, urinary retention and blurred vision.",
        "reactions": {"dry mouth", "constipation", "urinary retention", "blurred vision",
                      "confusion", "tachycardia"},
        "socs": {"GI"}, "confidence": "medium",
    },
    {
        "id": "corticosteroid",
        "drugs": ["prednisone", "prednisolone", "dexamethasone", "methylprednisolone",
                  "hydrocortisone", "betamethasone", "budesonide"],
        "target": "Glucocorticoid receptor agonism",
        "explanation": "Glucocorticoid signalling drives gluconeogenesis (hyperglycaemia), "
                       "bone resorption (osteoporosis), immune suppression (infection) and "
                       "CNS effects (mood change, insomnia).",
        "reactions": {"hyperglycaemia", "osteoporosis", "weight gain", "mood changes",
                      "insomnia", "infection", "cushingoid", "hypertension"},
        "socs": set(), "confidence": "medium",
    },
    {
        "id": "aminoglycoside",
        "drugs": ["gentamicin", "amikacin", "tobramycin", "streptomycin", "neomycin"],
        "target": "Aminoglycoside cochlear/renal accumulation",
        "explanation": "Aminoglycosides accumulate in cochlear hair cells and renal proximal "
                       "tubules, producing dose-related ototoxicity and nephrotoxicity.",
        "reactions": {"hearing loss", "ototoxicity", "tinnitus", "deafness", "vertigo",
                      "nephrotoxicity", "renal impairment", "renal failure"},
        "socs": {"NERV"}, "confidence": "high",
    },
    {
        "id": "retinoid",
        "drugs": ["isotretinoin", "acitretin", "tretinoin", "alitretinoin"],
        "target": "Retinoic-acid receptor agonism",
        "explanation": "Retinoid signalling is a potent morphogen (teratogenic) and reduces "
                       "sebaceous/epithelial activity, causing mucocutaneous dryness; a direct "
                       "mechanistic link to depression is not established.",
        "reactions": {"teratogenicity", "birth defect", "fetal harm", "dry skin", "cheilitis",
                      "dry lips", "mucocutaneous", "dry eyes", "epistaxis"},
        "socs": {"PREG"}, "confidence": "medium",
    },
    {
        "id": "fluoroquinolone",
        "drugs": ["ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin",
                  "norfloxacin", "gemifloxacin"],
        "target": "Fluoroquinolone connective-tissue / mitochondrial toxicity",
        "explanation": "Fluoroquinolones chelate matrix metal ions and impair tenocyte "
                       "collagen and mitochondrial function, linking them to tendinopathy, "
                       "tendon rupture and peripheral neuropathy.",
        "reactions": {"tendon rupture", "tendinitis", "tendon pain", "peripheral neuropathy",
                      "tingling", "numbness", "paraesthesia", "muscle weakness"},
        "socs": {"MUSC", "NERV"}, "confidence": "medium",
    },
    {
        "id": "antifolate",
        "drugs": ["methotrexate", "pemetrexed", "trimethoprim"],
        "target": "Dihydrofolate reductase inhibition (antifolate)",
        "explanation": "Antifolate action halts DNA synthesis in rapidly dividing cells, "
                       "hitting bone marrow (myelosuppression), gut mucosa (mucositis) and "
                       "liver (hepatotoxicity).",
        "reactions": {"myelosuppression", "neutropenia", "anaemia", "thrombocytopenia",
                      "hepatotoxicity", "liver damage", "hepatic injury", "mucositis",
                      "stomatitis", "pancytopenia"},
        "socs": {"BLOOD", "HEPB"}, "confidence": "high",
    },
    {
        "id": "aromatic_anticonvulsant",
        "drugs": ["carbamazepine", "oxcarbazepine", "phenytoin", "lamotrigine"],
        "target": "Aromatic anticonvulsant (reactive-metabolite / immune + ADH effects)",
        "explanation": "Reactive arene-oxide metabolites drive immune-mediated severe "
                       "cutaneous reactions (HLA-restricted), while ADH-like action can cause "
                       "hyponatraemia.",
        "reactions": {"rash", "stevens-johnson syndrome", "sjs", "toxic epidermal necrolysis",
                      "ten", "dress", "hyponatraemia", "blisters", "peeling skin"},
        "socs": {"SKIN"}, "confidence": "medium",
    },
]

# drug (generic) -> entries
_INDEX: Dict[str, List[dict]] = {}
for _e in MECHANISM_TABLE:
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


def assess(drug: str, symptom: str, pt: Optional[str] = None,
           soc: Optional[str] = None) -> Optional[dict]:
    """Assess mechanistic plausibility for a (drug, event) pair.

    Returns None when the drug's pharmacology is not in our knowledge base.
    When the drug IS known:
      * plausible=True  -> the event is an on-target / expected effect of the MoA
      * plausible=False -> the drug's mechanism is known but does not explain THIS event
    """
    generic = (normalize_drug(drug) or "").strip().lower()
    entries = _INDEX.get(generic)
    if not entries:
        return None

    for entry in entries:
        if _reaction_matches(entry, symptom, pt, soc):
            return {
                "plausible": True,
                "target_or_moa": entry["target"],
                "mechanism_explanation": entry["explanation"],
                "confidence": entry["confidence"],
                "source": "Curated pharmacology KB (Open Targets/ChEMBL-style surrogate)",
                "drug": generic,
            }

    primary = entries[0]
    return {
        "plausible": False,
        "target_or_moa": primary["target"],
        "mechanism_explanation": f"{drug.title()} acts via {primary['target']}, which is not "
                                 f"an established mechanistic cause of this event — the "
                                 f"association may be idiosyncratic or confounded.",
        "confidence": "low",
        "source": "Curated pharmacology KB (Open Targets/ChEMBL-style surrogate)",
        "drug": generic,
    }


def reference_table() -> dict:
    """Public reference view of the mechanism knowledge base."""
    return {
        "count": len(MECHANISM_TABLE),
        "note": "Curated drug mechanism-of-action -> adverse-event knowledge base "
                "(offline Open Targets/ChEMBL-style surrogate). Used to compute Bradford "
                "Hill 'biological plausibility' for each signal.",
        "mechanisms": [
            {"target": e["target"], "drugs": e["drugs"],
             "explanation": e["explanation"], "confidence": e["confidence"]}
            for e in MECHANISM_TABLE
        ],
    }
