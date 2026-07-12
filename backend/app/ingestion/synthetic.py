"""Worldwide synthetic patient-post corpus generator.

Produces a realistic, reproducible corpus of patient-generated posts spread across
regions, countries, languages, platforms and drugs, over time — so the
disproportionality, trend, spike, causality, knowledge-graph and translation
engines all have meaningful global data offline. Also powers the streaming sim.

The corpus deliberately preserves a dramatic hero signal (isotretinoin -> depression)
with a late-window spike, and seeds a few non-English posts to exercise translation.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import List

# (brand, generic, symptom, condition, region, country)
_AE_TEMPLATES = [
    # North America
    ("Tylenol", "paracetamol", "liver damage", "fever", "North America", "United States"),
    ("Lipitor", "atorvastatin", "muscle pain", "high cholesterol", "North America", "United States"),
    ("Accutane", "isotretinoin", "depression", "acne", "North America", "United States"),
    ("Zoloft", "sertraline", "insomnia", "depression", "North America", "United States"),
    ("Ozempic", "semaglutide", "nausea", "type 2 diabetes", "North America", "United States"),
    ("Ozempic", "semaglutide", "vomiting", "type 2 diabetes", "North America", "Canada"),
    ("Xarelto", "rivaroxaban", "bleeding", "atrial fibrillation", "North America", "United States"),
    # Europe
    ("Voltaren", "diclofenac", "stomach pain", "back pain", "Europe", "Germany"),
    ("Nurofen", "ibuprofen", "heartburn", "arthritis", "Europe", "United Kingdom"),
    ("Seroxat", "paroxetine", "dizziness", "anxiety", "Europe", "United Kingdom"),
    ("Concor", "bisoprolol", "fatigue", "hypertension", "Europe", "France"),
    ("Augmentin", "amoxicillin clavulanate", "rash", "infection", "Europe", "Italy"),
    # India
    ("Dolo 650", "paracetamol", "nausea", "fever", "Asia", "India"),
    ("Combiflam", "ibuprofen", "stomach pain", "body ache", "Asia", "India"),
    ("Glycomet", "metformin", "diarrhea", "type 2 diabetes", "Asia", "India"),
    ("Thyronorm", "levothyroxine", "palpitations", "hypothyroidism", "Asia", "India"),
    ("Ecosprin", "aspirin", "bleeding", "heart disease", "Asia", "India"),
    # Rest of Asia / LatAm / Africa
    ("Loxonin", "loxoprofen", "stomach pain", "back pain", "Asia", "Japan"),
    ("Novalgina", "metamizole", "rash", "fever", "South America", "Brazil"),
    ("Panadol", "paracetamol", "dizziness", "fever", "Africa", "Nigeria"),
    ("Lyrica", "pregabalin", "drowsiness", "epilepsy", "Oceania", "Australia"),
    ("Neurontin", "gabapentin", "dizziness", "migraine", "North America", "United States"),
    # Pharmacogenomically-actionable pairs (CPIC/PharmGKB) — seed PGx-positive signals
    ("Tegretol", "carbamazepine", "rash", "epilepsy", "Asia", "India"),
    ("Zyloric", "allopurinol", "rash", "gout", "Europe", "United Kingdom"),
    ("Zocor", "simvastatin", "muscle pain", "high cholesterol", "North America", "United States"),
    ("Coumadin", "warfarin", "bleeding", "atrial fibrillation", "North America", "United States"),
    ("Solpadeine", "codeine", "drowsiness", "back pain", "Europe", "United Kingdom"),
    ("Imuran", "azathioprine", "bleeding", "crohn's disease", "North America", "Canada"),
]

# (brand, generic, symptom, condition, region, country) — deterministically injected
# so the demo reliably shows genomically-explainable (PGx) signals. Carbamazepine ->
# rash (HLA-B*15:02 / Stevens-Johnson) is the PGx hero.
_PGX_INJECT = [
    ("Tegretol", "carbamazepine", "rash", "epilepsy", "Asia", "India", 6),
    ("Zyloric", "allopurinol", "rash", "gout", "Europe", "United Kingdom", 4),
    ("Zocor", "simvastatin", "muscle pain", "high cholesterol", "North America", "United States", 4),
    ("Coumadin", "warfarin", "bleeding", "atrial fibrillation", "North America", "United States", 4),
]

# Geographically-concentrated hero (SPATIAL cluster). A substandard / counterfeit
# antibiotic batch surfaces as ciprofloxacin -> liver damage clustered overwhelmingly
# in ONE country (Nigeria / Africa), far beyond that market's expected share of the
# corpus geography — the pattern the Kulldorff-style spatial scan is built to catch.
# A couple of stray reports elsewhere keep the breakdown realistic (and show contrast).
# This is a brand-new drug->event pair, so it does not perturb the existing signals.
#   (brand, generic, symptom, condition, region, country, count)
_GEO_INJECT = [
    ("Cifran", "ciprofloxacin", "liver damage", "infection", "Africa", "Nigeria", 12),
    ("Cifran", "ciprofloxacin", "liver damage", "infection", "Asia", "India", 2),
    ("Cifran", "ciprofloxacin", "liver damage", "infection", "North America", "United States", 1),
]

# Vaccine pharmacovigilance injection. Vaccine PV is a distinct discipline, so we
# deterministically seed vaccine -> AESI (Adverse Event of Special Interest) signals
# so the Brighton-level + SCRI (self-controlled risk interval) surrogates have data.
# The onset offsets (days after the earliest supporting post) are clustered early so
# the SCRI relative incidence is elevated — mirroring the real-world pattern of AESIs
# occurring shortly after immunisation. Vaccine posts keep product_type="drug" so the
# existing drug/device pipeline logic is untouched; the vaccine overlay keys off the
# curated vaccine registry (drug name), not the product_type.
#   (brand, generic, symptom-surface, condition, region, country, [onset day offsets])
_VACCINE_INJECT = [
    # COVID-19 mRNA vaccine -> myocarditis (the vaccine-AESI hero; enough posts + a
    # clear early cluster so SCRI computes an elevated relative incidence).
    ("Comirnaty", "covid-19 mrna vaccine", "myocarditis", "covid-19",
     "North America", "United States", [0, 0, 1, 1, 2, 3, 4, 5, 12, 18]),
    ("Spikevax", "covid-19 mrna vaccine", "pericarditis", "covid-19",
     "Europe", "Germany", [0, 1, 2, 3, 11]),
    # Influenza vaccine -> Guillain-Barré syndrome (classic historical AESI).
    ("Fluarix", "influenza vaccine", "guillain-barre syndrome", "flu",
     "Europe", "United Kingdom", [0, 1, 2, 4, 10, 16]),
    # HPV vaccine -> syncope (vasovagal fainting, common in adolescents).
    ("Gardasil", "hpv vaccine", "fainting", "hpv",
     "North America", "United States", [0, 0, 1, 2, 3, 9, 15]),
    # MMR vaccine -> febrile seizure (paediatric AESI).
    ("Priorix", "mmr vaccine", "febrile seizure", "measles",
     "Asia", "India", [0, 1, 2, 8, 14]),
]

# Vernacular / slang AE posts (brand, full text, region, country). These contain
# NO literal MedDRA term — only patient idioms — so they exercise the vernacular
# mapping layer and demonstrate that plain-language posts still feed real signals.
# Each maps to an EXISTING drug->PT signal so it shows up as a supporting post:
#   Zoloft/insomnia+fatigue, Ozempic/vomiting+nausea, Neurontin/dizziness,
#   Thyronorm/palpitations+tremor, Lyrica/somnolence, Lipitor/myalgia.
_VERNACULAR_INJECT = [
    ("Zoloft", "Started Zoloft for my anxiety and I couldn't sleep a wink the first week — "
     "up all night and completely wiped out the next day. Really struggling.", "North America", "United States"),
    ("Ozempic", "After my Ozempic shot I was throwing up all evening and felt so queasy. "
     "Stopped it and it settled, but it was awful.", "North America", "United States"),
    ("Neurontin", "Neurontin left me with the room spinning every time I stood up. "
     "Terrifying, had to hold onto the wall.", "North America", "United States"),
    ("Thyronorm", "Since starting Thyronorm my heart was pounding out of my chest and my "
     "hands were shaking all day. So worried.", "Asia", "India"),
    ("Lyrica", "Lyrica knocks me out — I'm like a zombie all day and couldn't stay awake "
     "at work. Had to stop.", "Oceania", "Australia"),
    ("Lipitor", "A few weeks on Lipitor and my muscles are killing me, legs feel like lead. "
     "Doctor is checking it now.", "North America", "United States"),
]

_COUNTRY_CODES = {
    "United States": "US", "Canada": "CA", "Germany": "DE", "United Kingdom": "GB",
    "France": "FR", "Italy": "IT", "India": "IN", "Japan": "JP", "Brazil": "BR",
    "Nigeria": "NG", "Australia": "AU",
}

_NEGATIVE_TEMPLATES = [
    "Started {brand} for my {cond} and honestly feeling great, no side effects at all.",
    "{brand} worked wonders, no {sym} whatsoever. Highly recommend.",
    "I was worried about {sym} but after taking {brand} I had none of it, all good.",
    "My {cond} is finally under control thanks to {brand}. Zero complaints.",
]

_AE_TEMPLATES_TEXT = [
    "Started {brand} for my {cond} and within hours I developed terrible {sym}. Anyone else?",
    "After taking {brand} for a few days I got awful {sym}. Stopped the drug and it slowly went away.",
    "{brand} gave me the worst {sym} I've ever had. Had to go to the hospital. Never again.",
    "Been on {brand} for {cond}. Ever since I started I've had {sym}, it's really affecting me.",
    "Took {brand} again after stopping and the {sym} came back immediately. Definitely the drug.",
    "Day 3 on {brand} and the {sym} is unbearable. So worried about this reaction.",
    "My doctor put me on {brand} for {cond} but the {sym} started soon after. Feeling awful.",
]

# A few non-English posts to demonstrate worldwide language handling + translation.
# (text, lang, brand, generic, symptom, region, country)
_MULTILINGUAL = [
    ("Después de tomar {brand} para {cond} empecé con fuertes {sym}. ¿Le pasa a alguien más?",
     "es", "Novalgina", "metamizole", "rash", "South America", "Brazil"),
    ("Depuis que je prends {brand} pour {cond}, j'ai des {sym} horribles. J'ai arrêté et ça va mieux.",
     "fr", "Concor", "bisoprolol", "fatigue", "Europe", "France"),
    ("{brand} लेने के बाद मुझे बहुत {sym} होने लगी। दवा बंद करने पर ठीक हो गया।",
     "hi", "Dolo 650", "paracetamol", "nausea", "Asia", "India"),
    ("{brand}を飲んだ後、ひどい{sym}が出ました。薬をやめたら治りました。",
     "ja", "Loxonin", "loxoprofen", "stomach pain", "Asia", "Japan"),
    ("Nach der Einnahme von {brand} gegen {cond} bekam ich starke {sym}.",
     "de", "Voltaren", "diclofenac", "stomach pain", "Europe", "Germany"),
]
_SYM_LOCAL = {"rash": "erupción", "fatigue": "fatigue", "nausea": "मतली",
              "stomach pain": "胃の痛み"}

# (device, failure_mode, context, region, country) — medical-device vigilance.
# Preserves a strong device hero signal: insulin pump -> malfunction.
_DEVICE_TEMPLATES = [
    ("insulin pump", "malfunction", "type 1 diabetes", "North America", "United States"),
    ("insulin pump", "malfunction", "type 1 diabetes", "Europe", "United Kingdom"),
    ("insulin pump", "malfunction", "type 1 diabetes", "Asia", "India"),
    ("continuous glucose monitor", "inaccurate reading", "diabetes", "North America", "United States"),
    ("pacemaker", "battery failure", "arrhythmia", "Europe", "Germany"),
    ("hip implant", "device loosening", "osteoarthritis", "Oceania", "Australia"),
    ("knee implant", "device loosening", "osteoarthritis", "North America", "Canada"),
    ("coronary stent", "thrombosis", "coronary artery disease", "Asia", "Japan"),
    ("infusion pump", "overinfusion", "chemotherapy", "North America", "United States"),
    ("surgical mesh", "erosion", "hernia repair", "Europe", "France"),
]

_DEVICE_TEXT = [
    "My {device} started to {fail} last week during treatment for {cond}. Terrifying experience.",
    "After my {device} was fitted for {cond} it began to {fail}. Anyone else had this?",
    "The {device} {fail} within days — had to rush to the hospital. Never expected this.",
    "Ever since I got the {device} for {cond} it keeps showing signs of {fail}. Really worried.",
    "Day 4 with the {device} and it {fail}. Stopped using it and reported to my doctor.",
]

_PLATFORMS = ["reddit", "twitter", "forum"]
_SUBS = {"reddit": "reddit.com", "twitter": "x.com", "forum": "patient.info"}

_BACKGROUND_SYMPTOMS = ["headache", "nausea", "fatigue", "dizziness", "drowsiness"]
_BACKGROUND_TEXT = [
    "Been taking {brand} and got some mild {sym}, not sure if related.",
    "{brand} is okay but I do feel a bit of {sym} sometimes.",
    "On {brand} for a while now, occasional {sym} but manageable.",
]


def _hash_author(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()[:12]


def _meta(brand, region, country):
    return {"region": region, "country": country,
            "country_code": _COUNTRY_CODES.get(country, "US")}


def _make_background(idx, posted_at, rng):
    brand, _g, _s, _c, region, country = rng.choice(_AE_TEMPLATES)
    sym = rng.choice(_BACKGROUND_SYMPTOMS)
    text = rng.choice(_BACKGROUND_TEXT).format(brand=brand, sym=sym)
    platform = rng.choice(_PLATFORMS)
    return {
        "external_id": f"bg-{idx}-{int(posted_at.timestamp())}",
        "platform": platform,
        "url": f"https://{_SUBS[platform]}/post/bg{idx}",
        "author": _hash_author(f"bguser{idx}-{platform}"),
        "title": f"Notes on {brand}",
        "body": text,
        "lang": "en",
        "posted_at": posted_at,
        **_meta(brand, region, country),
    }


def _make_post(idx, posted_at, rng, ae):
    brand, generic, sym, cond, region, country = rng.choice(_AE_TEMPLATES)
    tmpl = _AE_TEMPLATES_TEXT if ae else _NEGATIVE_TEMPLATES
    text = rng.choice(tmpl).format(brand=brand, sym=sym, cond=cond)
    platform = rng.choice(_PLATFORMS)
    return {
        "external_id": f"syn-{idx}-{int(posted_at.timestamp())}",
        "platform": platform,
        "url": f"https://{_SUBS[platform]}/post/{idx}",
        "author": _hash_author(f"user{idx}-{platform}"),
        "title": f"Experience with {brand}",
        "body": text,
        "lang": "en",
        "posted_at": posted_at,
        **_meta(brand, region, country),
    }


def _make_device_post(idx, posted_at, rng):
    device, fail, cond, region, country = rng.choice(_DEVICE_TEMPLATES)
    # phrase the failure naturally (e.g. "malfunction" -> "malfunction")
    fail_phrase = {"malfunction": "malfunction", "battery failure": "have a battery failure",
                   "device loosening": "show device loosening", "thrombosis": "cause thrombosis",
                   "overinfusion": "overinfusion", "erosion": "cause erosion",
                   "inaccurate reading": "give an inaccurate reading"}.get(fail, fail)
    text = rng.choice(_DEVICE_TEXT).format(device=device, fail=fail_phrase, cond=cond)
    platform = rng.choice(_PLATFORMS)
    return {
        "external_id": f"dev-{idx}-{int(posted_at.timestamp())}",
        "platform": platform,
        "product_type": "device",
        "url": f"https://{_SUBS[platform]}/post/dev{idx}",
        "author": _hash_author(f"devuser{idx}-{platform}"),
        "title": f"Problem with my {device}",
        "body": text,
        "lang": "en",
        "posted_at": posted_at,
        **_meta(device, region, country),
    }


def _make_multilingual(idx, posted_at, rng):
    tmpl, lang, brand, generic, sym, region, country = rng.choice(_MULTILINGUAL)
    local_sym = _SYM_LOCAL.get(sym, sym)
    text = tmpl.format(brand=brand, sym=local_sym, cond="")
    platform = rng.choice(_PLATFORMS)
    return {
        "external_id": f"ml-{idx}-{int(posted_at.timestamp())}",
        "platform": platform,
        "url": f"https://{_SUBS[platform]}/post/ml{idx}",
        "author": _hash_author(f"mluser{idx}"),
        "title": f"{brand}",
        "body": text,
        "lang": lang,
        "posted_at": posted_at,
        **_meta(brand, region, country),
    }


def generate_corpus(days: int = 21, seed: int = 42) -> List[dict]:
    """Generate a worldwide corpus over `days` with a late-window hero spike."""
    rng = random.Random(seed)
    now = datetime.utcnow()
    posts: List[dict] = []
    idx = 0

    for day_offset in range(days, 0, -1):
        day = now - timedelta(days=day_offset)
        base = rng.randint(8, 14)  # higher worldwide volume for meaningful stats
        spike = day_offset <= 3
        n = base + (rng.randint(6, 10) if spike else 0)
        for _ in range(n):
            hour = rng.randint(0, 23)
            ts = day.replace(hour=hour, minute=rng.randint(0, 59))
            roll = rng.random()
            if roll < 0.06:
                posts.append(_make_multilingual(idx, ts, rng))
                idx += 1
                continue
            if roll < 0.18:
                posts.append(_make_device_post(idx, ts, rng))
                idx += 1
                continue
            if roll < 0.46:
                posts.append(_make_background(idx, ts, rng))
                idx += 1
                continue
            ae = roll < 0.82
            post = _make_post(idx, ts, rng, ae)
            if spike and ae and rng.random() < 0.6:
                post["body"] = (
                    "Started Accutane for my acne and the depression hit me hard within days. "
                    "Stopped it and things improved. Took it again and the depression came right back."
                )
                post["title"] = "Accutane and depression"
                post["region"] = rng.choice(["North America", "Europe", "Asia"])
            posts.append(post)
            idx += 1

    # Deterministically inject pharmacogenomically-actionable AE pairs so the PGx
    # overlay reliably has genomically-explainable signals to surface in the demo.
    for brand, _generic, sym, cond, region, country, count in _PGX_INJECT:
        for _ in range(count):
            day_offset = rng.randint(1, days)
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            text = rng.choice(_AE_TEMPLATES_TEXT).format(brand=brand, sym=sym, cond=cond)
            platform = rng.choice(_PLATFORMS)
            posts.append({
                "external_id": f"pgx-{idx}-{int(ts.timestamp())}",
                "platform": platform,
                "url": f"https://{_SUBS[platform]}/post/pgx{idx}",
                "author": _hash_author(f"pgxuser{idx}-{platform}"),
                "title": f"Experience with {brand}",
                "body": text,
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1

    # Inject the geographically-concentrated hero (spatial cluster): a substandard
    # ciprofloxacin batch reported overwhelmingly from one country, so the spatial
    # scan surfaces a clear hotspot with an elevated relative risk.
    for brand, _generic, sym, cond, region, country, count in _GEO_INJECT:
        for _ in range(count):
            day_offset = rng.randint(1, days)
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            text = rng.choice(_AE_TEMPLATES_TEXT).format(brand=brand, sym=sym, cond=cond)
            platform = rng.choice(_PLATFORMS)
            posts.append({
                "external_id": f"geo-{idx}-{int(ts.timestamp())}",
                "platform": platform,
                "url": f"https://{_SUBS[platform]}/post/geo{idx}",
                "author": _hash_author(f"geouser{idx}-{platform}"),
                "title": f"Experience with {brand}",
                "body": text,
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1

    # Inject vernacular/slang AE posts (no literal MedDRA term) so the demo shows
    # patient plain-language mapped to standardized PTs feeding real signals.
    for brand, text, region, country in _VERNACULAR_INJECT:
        for _ in range(3):
            day_offset = rng.randint(1, days)
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            platform = rng.choice(_PLATFORMS)
            posts.append({
                "external_id": f"vern-{idx}-{int(ts.timestamp())}",
                "platform": platform,
                "url": f"https://{_SUBS[platform]}/post/vern{idx}",
                "author": _hash_author(f"vernuser{idx}-{platform}"),
                "title": f"Experience with {brand}",
                "body": text,
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1

    # Inject vaccine -> AESI posts with early-clustered onsets so the vaccine safety
    # overlay (AESI match, Brighton level, SCRI relative incidence) has data. The
    # earliest onset per pair anchors the SCRI window, so offsets are days from origin.
    origin = now - timedelta(days=days)
    for brand, _generic, sym, cond, region, country, offsets in _VACCINE_INJECT:
        for off in offsets:
            off = min(off, days)
            ts = (origin + timedelta(days=off)).replace(
                hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            text = rng.choice(_AE_TEMPLATES_TEXT).format(brand=brand, sym=sym, cond=cond)
            platform = rng.choice(_PLATFORMS)
            posts.append({
                "external_id": f"vac-{idx}-{int(ts.timestamp())}",
                "platform": platform,
                "url": f"https://{_SUBS[platform]}/post/vac{idx}",
                "author": _hash_author(f"vacuser{idx}-{platform}"),
                "title": f"Experience after {brand}",
                "body": text,
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1

    return posts


# Therapeutic-area corpora for project workspaces (oncology / vaccine).
_ONCOLOGY_INJECT = [
    # Brands/generics + symptoms that exist in the offline lexicon (must extract for AE gates).
    ("Keytruda", "pembrolizumab", "pneumonitis", "melanoma", "North America", "United States", 8),
    ("Keytruda", "pembrolizumab", "hepatitis", "lung cancer", "Europe", "Germany", 6),
    ("Opdivo", "nivolumab", "rash", "melanoma", "North America", "United States", 6),
    ("Opdivo", "nivolumab", "diarrhea", "renal cell carcinoma", "Asia", "Japan", 5),
    ("Trexall", "methotrexate", "nausea", "breast cancer", "Europe", "United Kingdom", 5),
    ("tamoxifen", "tamoxifen", "hot flashes", "breast cancer", "North America", "United States", 5),
    ("imatinib", "imatinib", "muscle pain", "leukemia", "Asia", "India", 5),
    ("cisplatin", "cisplatin", "nausea", "lung cancer", "North America", "Canada", 5),
    ("paclitaxel", "paclitaxel", "numbness", "breast cancer", "Europe", "France", 5),
    ("doxorubicin", "doxorubicin", "chest pain", "lymphoma", "North America", "United States", 5),
    ("rituximab", "rituximab", "rash", "lymphoma", "Europe", "Italy", 4),
]


def generate_area_corpus(area: str, days: int = 21, seed: int = 42) -> List[dict]:
    """Build a focused synthetic corpus for oncology or vaccine project workspaces."""
    area = (area or "general").lower().strip()
    if area in ("general", "general-pv", ""):
        return generate_corpus(days=days, seed=seed)

    rng = random.Random(seed + hash(area) % 10_000)
    now = datetime.utcnow()
    posts: List[dict] = []
    idx = 0
    prefix = area[:3]

    if area == "vaccine":
        ae_bodies = [
            "After {brand} for {cond} I developed {sym}. Really worried — reporting to my doctor.",
            "Got {brand} and within days had {sym}. Never had this before the shot.",
            "{brand} side effect: severe {sym}. Had to go to urgent care.",
            "Post-{brand} {sym} hit hard. Deferring further doses until cleared.",
        ]
        origin = now - timedelta(days=days)
        for brand, _generic, sym, cond, region, country, offsets in _VACCINE_INJECT:
            for off in offsets:
                off = min(off, days)
                ts = (origin + timedelta(days=off)).replace(
                    hour=rng.randint(0, 23), minute=rng.randint(0, 59))
                text = rng.choice(ae_bodies).format(brand=brand, sym=sym, cond=cond)
                platform = rng.choice(_PLATFORMS)
                posts.append({
                    "external_id": f"{prefix}-vac-{idx}-{int(ts.timestamp())}",
                    "platform": platform,
                    "url": f"https://{_SUBS[platform]}/post/{prefix}vac{idx}",
                    "author": _hash_author(f"{prefix}vac{idx}-{platform}"),
                    "title": f"Experience after {brand}",
                    "body": text,
                    "lang": "en",
                    "posted_at": ts,
                    **_meta(brand, region, country),
                })
                idx += 1
        # Light background chatter so disproportionality has a denominator.
        for _ in range(max(40, days * 2)):
            day_offset = rng.randint(1, days)
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            brand, _g, sym, cond, region, country = rng.choice(_VACCINE_INJECT)[:6]
            posts.append({
                "external_id": f"{prefix}-bg-{idx}-{int(ts.timestamp())}",
                "platform": rng.choice(_PLATFORMS),
                "url": f"https://example.com/{prefix}/bg{idx}",
                "author": _hash_author(f"{prefix}bg{idx}"),
                "title": f"Question about {brand}",
                "body": f"Got my {brand} shot for {cond}. Feeling fine so far, any tips?",
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1
        return posts

    if area == "oncology":
        ae_bodies = [
            "Started {brand} for {cond} and developed severe {sym}. Had to pause treatment.",
            "On {brand} — the {sym} is unbearable. Oncologist is investigating immune-related AE.",
            "After two cycles of {brand} for {cond} I got {sym}. Dechallenged and it improved.",
            "{brand} caused {sym} within weeks. Scared to continue immunotherapy.",
        ]
        for brand, _generic, sym, cond, region, country, count in _ONCOLOGY_INJECT:
            for _ in range(count):
                day_offset = rng.randint(1, days)
                day = now - timedelta(days=day_offset)
                ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
                text = rng.choice(ae_bodies).format(brand=brand, sym=sym, cond=cond)
                platform = rng.choice(_PLATFORMS)
                posts.append({
                    "external_id": f"{prefix}-onc-{idx}-{int(ts.timestamp())}",
                    "platform": platform,
                    "url": f"https://{_SUBS[platform]}/post/{prefix}onc{idx}",
                    "author": _hash_author(f"{prefix}onc{idx}-{platform}"),
                    "title": f"Side effects on {brand}",
                    "body": text,
                    "lang": "en",
                    "posted_at": ts,
                    **_meta(brand, region, country),
                })
                idx += 1
        for _ in range(max(30, days)):
            day_offset = rng.randint(1, days)
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            brand, _g, sym, cond, region, country, _c = rng.choice(_ONCOLOGY_INJECT)
            posts.append({
                "external_id": f"{prefix}-bg-{idx}-{int(ts.timestamp())}",
                "platform": rng.choice(_PLATFORMS),
                "url": f"https://example.com/{prefix}/bg{idx}",
                "author": _hash_author(f"{prefix}bg{idx}"),
                "title": f"Starting {brand}",
                "body": f"Oncologist started me on {brand} for {cond}. Monitoring carefully.",
                "lang": "en",
                "posted_at": ts,
                **_meta(brand, region, country),
            })
            idx += 1
        return posts

    return generate_corpus(days=days, seed=seed)


def stream_batch(n: int = 3, seed: int | None = None) -> List[dict]:
    """Generate `n` brand-new posts timestamped 'now' for the live stream sim."""
    rng = random.Random(seed)
    now = datetime.utcnow()
    base = int(now.timestamp())
    out = []
    for i in range(n):
        ae = rng.random() < 0.75
        out.append(_make_post(base + i, now, rng, ae))
    return out
