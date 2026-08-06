"""Curated worldwide medical lexicons for lexicon-based NER.

Deterministic and offline. When USE_TRANSFORMER_NER=true, these still run as a
high-precision keyword boost on top of the transformer output.

Coverage is worldwide-first: global generic (INN) names + brand names from the
US, EU, UK, Japan, Latin America, and India. The Indian brand map is retained in
full so India stays first-class.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Generic drug names (INN, lowercase). Worldwide.
# --------------------------------------------------------------------------- #
GENERIC_DRUGS = {
    # analgesics / NSAIDs
    "paracetamol", "acetaminophen", "ibuprofen", "aspirin", "acetylsalicylic acid",
    "naproxen", "diclofenac", "celecoxib", "etoricoxib", "ketorolac", "indomethacin",
    "meloxicam", "nimesulide", "mefenamic acid",
    # opioids
    "tramadol", "morphine", "codeine", "oxycodone", "hydrocodone", "fentanyl",
    "buprenorphine", "tapentadol",
    # diabetes
    "metformin", "glimepiride", "gliclazide", "glipizide", "sitagliptin",
    "vildagliptin", "linagliptin", "empagliflozin", "dapagliflozin", "canagliflozin",
    "pioglitazone", "insulin", "liraglutide", "semaglutide", "dulaglutide",
    # cardiovascular / lipids
    "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin",
    "amlodipine", "nifedipine", "diltiazem", "verapamil", "lisinopril", "enalapril",
    "ramipril", "perindopril", "losartan", "telmisartan", "valsartan", "olmesartan",
    "candesartan", "metoprolol", "atenolol", "bisoprolol", "carvedilol", "propranolol",
    "furosemide", "torsemide", "spironolactone", "hydrochlorothiazide", "chlorthalidone",
    "digoxin", "warfarin", "clopidogrel", "ticagrelor", "prasugrel", "rivaroxaban",
    "apixaban", "dabigatran", "ezetimibe", "fenofibrate", "amiodarone", "dronedarone",
    "flecainide", "sotalol", "ivabradine",
    # antibiotics / antivirals / antifungals
    "amoxicillin", "amoxicillin clavulanate", "ampicillin", "azithromycin",
    "clarithromycin", "erythromycin", "ciprofloxacin", "levofloxacin", "moxifloxacin",
    "ofloxacin", "doxycycline", "minocycline", "cephalexin", "cefixime", "ceftriaxone",
    "cefuroxime", "clindamycin", "metronidazole", "trimethoprim", "sulfamethoxazole",
    "nitrofurantoin", "vancomycin", "linezolid", "gentamicin", "fluconazole",
    "itraconazole", "ketoconazole", "acyclovir", "valacyclovir", "oseltamivir",
    "remdesivir", "hydroxychloroquine", "chloroquine", "ivermectin",
    # GI
    "omeprazole", "esomeprazole", "pantoprazole", "lansoprazole", "rabeprazole",
    "ranitidine", "famotidine", "ondansetron", "domperidone", "metoclopramide",
    "loperamide", "sucralfate",
    # psychiatry / neurology
    "sertraline", "fluoxetine", "paroxetine", "citalopram", "escitalopram",
    "venlafaxine", "duloxetine", "mirtazapine", "bupropion", "amitriptyline",
    "nortriptyline", "clomipramine", "alprazolam", "diazepam", "lorazepam",
    "clonazepam", "zolpidem", "quetiapine", "olanzapine", "risperidone",
    "aripiprazole", "haloperidol", "clozapine", "lithium", "gabapentin",
    "pregabalin", "carbamazepine", "oxcarbazepine", "valproate", "sodium valproate",
    "lamotrigine", "levetiracetam", "phenytoin", "topiramate", "donepezil",
    "sumatriptan", "rizatriptan",
    # respiratory / allergy
    "montelukast", "salbutamol", "albuterol", "salmeterol", "formoterol",
    "budesonide", "fluticasone", "beclomethasone", "tiotropium", "ipratropium",
    "cetirizine", "levocetirizine", "loratadine", "desloratadine", "fexofenadine",
    "chlorpheniramine", "diphenhydramine",
    # endocrine / steroids
    "levothyroxine", "carbimazole", "methimazole", "prednisone", "prednisolone",
    "dexamethasone", "hydrocortisone", "methylprednisolone", "testosterone",
    "estradiol", "medroxyprogesterone",
    # urology / others
    "sildenafil", "tadalafil", "tamsulosin", "finasteride", "dutasteride",
    "oxybutynin", "allopurinol", "febuxostat", "colchicine",
    # oncology / immunosuppressants with PGx-actionable toxicity
    "fluorouracil", "5-fluorouracil", "capecitabine", "mercaptopurine",
    "6-mercaptopurine", "thioguanine", "abacavir",
    # dermatology / immunology / oncology
    "isotretinoin", "tretinoin", "adapalene", "methotrexate", "azathioprine",
    "cyclosporine", "tacrolimus", "adalimumab", "etanercept", "infliximab",
    "rituximab", "tamoxifen", "letrozole", "imatinib", "cisplatin", "carboplatin",
    "paclitaxel", "doxorubicin", "pembrolizumab", "nivolumab",
    # vaccines (multi-word generics; recognised as products so vaccine signals form)
    "covid-19 mrna vaccine", "influenza vaccine", "hpv vaccine", "mmr vaccine",
    "hepatitis b vaccine", "tdap vaccine", "pneumococcal vaccine", "zoster vaccine",
    "rotavirus vaccine",
    # misc
    "vitamin d", "folic acid", "iron", "calcium",
}

# --------------------------------------------------------------------------- #
# Brand names -> generic (worldwide + India). Used for normalization + NER.
# --------------------------------------------------------------------------- #
BRAND_TO_GENERIC = {
    # ---- India ----
    "dolo": "paracetamol", "dolo 650": "paracetamol", "dolo650": "paracetamol",
    "crocin": "paracetamol", "calpol": "paracetamol",
    "brufen": "ibuprofen", "combiflam": "ibuprofen",
    "disprin": "aspirin", "ecosprin": "aspirin",
    "glycomet": "metformin", "glucophage": "metformin",
    "amlong": "amlodipine", "rosuvas": "rosuvastatin", "storvas": "atorvastatin",
    "augmentin": "amoxicillin clavulanate", "azithral": "azithromycin",
    "cifran": "ciprofloxacin", "ciplox": "ciprofloxacin",
    "pan": "pantoprazole", "pan 40": "pantoprazole", "pantop": "pantoprazole",
    "omez": "omeprazole", "razo": "rabeprazole",
    "nexito": "escitalopram", "thyronorm": "levothyroxine", "eltroxin": "levothyroxine",
    "montair": "montelukast", "asthalin": "salbutamol",
    "allegra": "fexofenadine", "cetzine": "cetirizine",
    "emeset": "ondansetron", "domstal": "domperidone", "zerodol": "aceclofenac",
    "shelcal": "calcium", "neurobion": "vitamin b", "liv 52": "herbal",
    # ---- US ----
    "tylenol": "acetaminophen", "advil": "ibuprofen", "motrin": "ibuprofen",
    "aleve": "naproxen", "bayer": "aspirin", "bufferin": "aspirin",
    "lipitor": "atorvastatin", "crestor": "rosuvastatin", "zocor": "simvastatin",
    "norvasc": "amlodipine", "glucophage xr": "metformin",
    "zithromax": "azithromycin", "cipro": "ciprofloxacin", "levaquin": "levofloxacin",
    "prilosec": "omeprazole", "nexium": "esomeprazole", "protonix": "pantoprazole",
    "zantac": "ranitidine", "pepcid": "famotidine", "zofran": "ondansetron",
    "zoloft": "sertraline", "prozac": "fluoxetine", "paxil": "paroxetine",
    "lexapro": "escitalopram", "celexa": "citalopram", "effexor": "venlafaxine",
    "cymbalta": "duloxetine", "wellbutrin": "bupropion", "xanax": "alprazolam",
    "valium": "diazepam", "ativan": "lorazepam", "klonopin": "clonazepam",
    "ambien": "zolpidem", "seroquel": "quetiapine", "zyprexa": "olanzapine",
    "abilify": "aripiprazole", "risperdal": "risperidone",
    "lyrica": "pregabalin", "neurontin": "gabapentin", "ultram": "tramadol",
    "ultracet": "tramadol", "oxycontin": "oxycodone", "percocet": "oxycodone",
    "vicodin": "hydrocodone", "tegretol": "carbamazepine", "depakote": "valproate",
    "lamictal": "lamotrigine", "keppra": "levetiracetam", "dilantin": "phenytoin",
    "topamax": "topiramate", "singulair": "montelukast", "ventolin": "albuterol",
    "proair": "albuterol", "symbicort": "budesonide", "flovent": "fluticasone",
    "spiriva": "tiotropium", "zyrtec": "cetirizine", "claritin": "loratadine",
    "allegra-d": "fexofenadine", "benadryl": "diphenhydramine",
    "synthroid": "levothyroxine", "levoxyl": "levothyroxine",
    "accutane": "isotretinoin", "claravis": "isotretinoin", "roaccutane": "isotretinoin",
    "viagra": "sildenafil", "cialis": "tadalafil", "flomax": "tamsulosin",
    "propecia": "finasteride", "lasix": "furosemide", "coumadin": "warfarin",
    "cordarone": "amiodarone", "pacerone": "amiodarone",
    "plavix": "clopidogrel", "eliquis": "apixaban", "xarelto": "rivaroxaban",
    "pradaxa": "dabigatran", "brilinta": "ticagrelor", "humira": "adalimumab",
    "enbrel": "etanercept", "remicade": "infliximab", "keytruda": "pembrolizumab",
    "opdivo": "nivolumab", "ozempic": "semaglutide", "wegovy": "semaglutide",
    "rybelsus": "semaglutide", "trulicity": "dulaglutide", "victoza": "liraglutide",
    "jardiance": "empagliflozin", "farxiga": "dapagliflozin", "januvia": "sitagliptin",
    # ---- EU / UK ----
    "nurofen": "ibuprofen", "voltaren": "diclofenac", "voltarol": "diclofenac",
    "panadol": "paracetamol", "solpadeine": "codeine", "co-codamol": "codeine",
    "augmentin duo": "amoxicillin clavulanate", "ciproxin": "ciprofloxacin",
    "losec": "omeprazole", "seroxat": "paroxetine", "efexor": "venlafaxine",
    "istin": "amlodipine", "tenormin": "atenolol", "inderal": "propranolol",
    "ramipril-ratiopharm": "ramipril",
    # ---- Japan / LatAm common ----
    "loxonin": "loxoprofen", "gaster": "famotidine", "mucosolvan": "ambroxol",
    "buscopan": "hyoscine", "novalgina": "metamizole", "dipirona": "metamizole",
    # PGx-relevant brands
    "zyloric": "allopurinol", "zyloprim": "allopurinol", "imuran": "azathioprine",
    "xeloda": "capecitabine", "trexall": "methotrexate",
    # ---- Vaccines (brand -> generic vaccine name) ----
    "comirnaty": "covid-19 mrna vaccine", "spikevax": "covid-19 mrna vaccine",
    "fluarix": "influenza vaccine", "fluzone": "influenza vaccine",
    "flucelvax": "influenza vaccine", "flublok": "influenza vaccine",
    "gardasil": "hpv vaccine", "gardasil 9": "hpv vaccine", "cervarix": "hpv vaccine",
    "priorix": "mmr vaccine", "m-m-r ii": "mmr vaccine",
    "engerix": "hepatitis b vaccine", "engerix-b": "hepatitis b vaccine",
    "recombivax": "hepatitis b vaccine", "heplisav": "hepatitis b vaccine",
    "boostrix": "tdap vaccine", "adacel": "tdap vaccine",
    "prevnar": "pneumococcal vaccine", "prevnar 13": "pneumococcal vaccine",
    "pneumovax": "pneumococcal vaccine", "vaxneuvance": "pneumococcal vaccine",
    "shingrix": "zoster vaccine", "zostavax": "zoster vaccine",
    "rotarix": "rotavirus vaccine", "rotateq": "rotavirus vaccine",
}

# --------------------------------------------------------------------------- #
# ATC (Anatomical Therapeutic Chemical) codes for common generics. Worldwide
# WHO standard for drug classification. Partial but covers the corpus + demo.
# --------------------------------------------------------------------------- #
DRUG_ATC = {
    "paracetamol": "N02BE01", "acetaminophen": "N02BE01", "ibuprofen": "M01AE01",
    "aspirin": "B01AC06", "naproxen": "M01AE02", "diclofenac": "M01AB05",
    "tramadol": "N02AX02", "morphine": "N02AA01", "codeine": "R05DA04",
    "metformin": "A10BA02", "sitagliptin": "A10BH01", "empagliflozin": "A10BK03",
    "dapagliflozin": "A10BK01", "semaglutide": "A10BJ06", "insulin": "A10A",
    "atorvastatin": "C10AA05", "simvastatin": "C10AA01", "rosuvastatin": "C10AA07",
    "amlodipine": "C08CA01", "lisinopril": "C09AA03", "ramipril": "C09AA05",
    "losartan": "C09CA01", "telmisartan": "C09CA07", "metoprolol": "C07AB02",
    "atenolol": "C07AB03", "furosemide": "C03CA01", "spironolactone": "C03DA01",
    "warfarin": "B01AA03", "clopidogrel": "B01AC04", "apixaban": "B01AF02",
    "rivaroxaban": "B01AF01", "amiodarone": "C01BD01", "amoxicillin": "J01CA04",
    "amoxicillin clavulanate": "J01CR02", "azithromycin": "J01FA10",
    "ciprofloxacin": "J01MA02", "levofloxacin": "J01MA12", "doxycycline": "J01AA02",
    "metronidazole": "J01XD01", "omeprazole": "A02BC01", "esomeprazole": "A02BC05",
    "pantoprazole": "A02BC02", "ranitidine": "A02BA02", "ondansetron": "A04AA01",
    "sertraline": "N06AB06", "fluoxetine": "N06AB03", "escitalopram": "N06AB10",
    "venlafaxine": "N06AX16", "duloxetine": "N06AX21", "bupropion": "N06AX12",
    "alprazolam": "N05BA12", "diazepam": "N05BA01", "quetiapine": "N05AH04",
    "olanzapine": "N05AH03", "risperidone": "N05AX08", "gabapentin": "N03AX12",
    "pregabalin": "N03AX16", "carbamazepine": "N03AF01", "valproate": "N03AG01",
    "lamotrigine": "N03AX09", "levetiracetam": "N03AX14", "phenytoin": "N03AB02",
    "montelukast": "R03DC03", "salbutamol": "R03AC02", "albuterol": "R03AC02",
    "budesonide": "R03BA02", "fluticasone": "R03BA05", "cetirizine": "R06AE07",
    "loratadine": "R06AX13", "fexofenadine": "R06AX26", "levothyroxine": "H03AA01",
    "prednisone": "H02AB07", "prednisolone": "H02AB06", "dexamethasone": "H02AB02",
    "isotretinoin": "D10BA01", "methotrexate": "L04AX03", "adalimumab": "L04AB04",
    "tamoxifen": "L02BA01", "sildenafil": "G04BE03", "tadalafil": "G04BE08",
    "tamsulosin": "G04CA02", "finasteride": "D11AX10", "allopurinol": "M04AA01",
}

# --------------------------------------------------------------------------- #
# Symptom / adverse-event terms (lowercase, single or multi-word).
# --------------------------------------------------------------------------- #
SYMPTOMS = {
    "headache", "migraine", "nausea", "vomiting", "dizziness", "vertigo", "fatigue",
    "tiredness", "drowsiness", "somnolence", "insomnia", "rash", "skin rash", "itching",
    "pruritus", "hives", "urticaria", "swelling", "edema", "oedema", "fever", "chills",
    "diarrhea", "diarrhoea", "constipation", "abdominal pain", "stomach pain",
    "stomach ache", "cramps", "bloating", "heartburn", "acid reflux", "indigestion",
    "palpitations", "chest pain", "shortness of breath", "breathlessness", "dyspnea",
    "cough", "sore throat", "wheezing", "blurred vision", "double vision", "dry mouth",
    "dry eyes", "sweating", "night sweats", "tremor", "tremors", "seizure",
    "convulsions", "anxiety", "panic attacks", "depression", "suicidal thoughts",
    "suicidal ideation", "mood swings", "irritability", "agitation", "confusion",
    "memory loss", "brain fog", "hallucinations", "hair loss", "alopecia",
    "weight gain", "weight loss", "loss of appetite", "increased appetite",
    "muscle pain", "myalgia", "muscle weakness", "muscle cramps", "joint pain",
    "arthralgia", "back pain", "numbness", "tingling", "paresthesia", "weakness",
    "fainting", "syncope", "low blood pressure", "hypotension", "high blood pressure",
    "hypertension", "irregular heartbeat", "arrhythmia", "tachycardia", "bradycardia",
    "liver damage", "hepatotoxicity", "kidney damage", "renal failure", "jaundice",
    "bleeding", "bruising", "nosebleed", "blood in stool", "blood in urine",
    "allergic reaction", "allergy", "allergies", "anaphylaxis", "swollen face", "swollen lips",
    "difficulty breathing", "difficulty swallowing", "restlessness", "nightmares",
    "erectile dysfunction", "loss of libido", "decreased libido", "gynecomastia",
    "photosensitivity", "sensitivity to light", "dry skin", "peeling skin",
    "mouth ulcers", "gum bleeding", "hearing loss", "tinnitus", "ringing in ears",
    "flushing", "hot flashes", "cold hands", "swollen ankles", "leg swelling",
    "increased thirst", "frequent urination", "difficulty urinating", "dark urine",
    # vaccine adverse events of special interest (AESI)
    "myocarditis", "myopericarditis", "pericarditis", "guillain-barre syndrome",
    "guillain-barré syndrome", "guillain barre syndrome",
    "thrombosis with thrombocytopenia", "cerebral venous sinus thrombosis",
    "bell's palsy", "bells palsy", "facial paralysis", "febrile seizure",
    "febrile convulsion", "immune thrombocytopenia", "thrombocytopenia",
    "encephalitis", "acute disseminated encephalomyelitis",
    # clinical adverse event terms common in FHIR / structured reporting sources
    "rhabdomyolysis", "angioedema", "liver injury", "hepatic injury",
    "acute liver failure", "drug-induced liver injury", "dili",
    "stevens-johnson syndrome", "toxic epidermal necrolysis",
    "pancreatitis", "nephrotoxicity", "ototoxicity", "cardiotoxicity",
    "neutropenia", "agranulocytosis", "aplastic anemia", "thromboembolism",
    "pulmonary embolism", "deep vein thrombosis", "anaphylactic shock",
    "serotonin syndrome", "neuroleptic malignant syndrome",
    "hyponatremia", "hypokalemia", "hypoglycemia", "hyperglycemia",
    "qt prolongation", "torsades de pointes", "ventricular arrhythmia",
    "interstitial lung disease", "pulmonary fibrosis", "pneumonitis",
    # pregnancy / teratogen / congenital anomaly stratum (special-population PV)
    "birth defect", "birth defects", "congenital anomaly", "congenital anomalies",
    "congenital malformation", "teratogenicity", "teratogen",
    "neural tube defect", "spina bifida", "cleft palate", "cleft lip",
    "cardiac malformation", "heart defect", "limb reduction", "hypospadias",
    "microcephaly", "fetal growth restriction", "intrauterine growth restriction",
    "stillbirth", "miscarriage", "spontaneous abortion", "neonatal death",
    "fetal death", "embryotoxicity", "developmental delay",
    "patent ductus arteriosus", "renal impairment", "neonatal renal impairment",
}

# --------------------------------------------------------------------------- #
# Condition / indication terms (lowercase). Worldwide.
# --------------------------------------------------------------------------- #
CONDITIONS = {
    "diabetes", "type 2 diabetes", "type 1 diabetes", "hypertension",
    "high blood pressure", "high cholesterol", "asthma", "copd", "arthritis",
    "rheumatoid arthritis", "osteoarthritis", "gout", "depression", "anxiety",
    "bipolar disorder", "schizophrenia", "adhd", "ocd", "ptsd", "epilepsy",
    "seizure disorder", "migraine", "hypothyroidism", "hyperthyroidism", "gerd",
    "acid reflux", "peptic ulcer", "ibs", "crohn's disease", "ulcerative colitis",
    "infection", "urinary tract infection", "pneumonia", "bronchitis", "sinusitis",
    "tuberculosis", "covid", "covid-19", "flu", "influenza", "cancer",
    "breast cancer", "prostate cancer", "lung cancer", "leukemia", "lymphoma",
    "heart disease", "coronary artery disease", "heart failure", "atrial fibrillation",
    "stroke", "deep vein thrombosis", "kidney disease", "chronic kidney disease",
    "liver disease", "hepatitis", "acne", "psoriasis", "eczema", "rosacea",
    "insomnia", "pcos", "endometriosis", "osteoporosis", "anemia", "hiv", "malaria",
    "erectile dysfunction", "enlarged prostate", "allergy", "allergies", "fever",
    "cold", "common cold",
}

# Terms that look like symptoms but are NOT adverse events in medical context.
NON_MEDICAL_STOP = {
    "tattoo", "pet", "dog", "cat", "car", "phone", "battery", "game", "movie",
}


def normalize_drug(name: str) -> str:
    """Map a brand/casual mention to a canonical generic name where possible."""
    key = (name or "").strip().lower()
    if key in BRAND_TO_GENERIC:
        return BRAND_TO_GENERIC[key]
    return key


def atc_for(generic: str) -> str | None:
    """Return the WHO ATC code for a generic drug name, if known."""
    return DRUG_ATC.get((generic or "").strip().lower())
