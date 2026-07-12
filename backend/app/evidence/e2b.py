"""ICH E2B ICSR XML export (R2 legacy + R3-style), adapted from SignalRx.

Generates demonstration Individual Case Safety Reports. PII is already scrubbed
upstream; patient identifiers are emitted as [REDACTED-BY-PII-VAULT]. Now enriched
with MedDRA-style Preferred Term / SOC, WHO ATC drug class, WHO-UMC causality, and
the signal narrative. Demo-grade templates, not validated regulatory submissions.
"""
from __future__ import annotations

from datetime import datetime
from xml.dom import minidom
from xml.etree.ElementTree import Element, SubElement, tostring


def _el(parent, tag, text=None, **attrs):
    e = SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def _meddra(signal: dict) -> dict:
    return signal.get("meddra") or {}


def _stats_line(signal: dict) -> str:
    return (f"PRR={signal.get('prr')} ROR={signal.get('ror')} "
            f"chi2={signal.get('chi_square')} reports={signal.get('post_count')} "
            f"strength={signal.get('strength')} severity={signal.get('severity')}")


def generate_e2b_xml(signal: dict, narrative: str = "") -> str:
    """E2B(R3)-style ICSR (enriched)."""
    now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    md = _meddra(signal)

    root = Element("ichicsr", lang="en")
    header = _el(root, "ichicsrmessageheader")
    _el(header, "messagetype", "ichicsr")
    _el(header, "messageformatversion", "3.0")
    _el(header, "messageformatrelease", "1.0")
    _el(header, "messagenumb", f"VIGILAI-{signal.get('id', 'NA')}")
    _el(header, "messagesenderidentifier", "VIGILAI")
    _el(header, "messagereceiveridentifier", "REGULATOR")
    _el(header, "messagedateformat", "204")
    _el(header, "messagedate", now)

    safetyreport = _el(root, "safetyreport")
    _el(safetyreport, "safetyreportversion", "1")
    _el(safetyreport, "safetyreportid", f"VIGILAI-{signal.get('id', 'NA')}")
    _el(safetyreport, "primarysourcecountry", signal.get("primary_country_code", "US"))
    _el(safetyreport, "occurcountry", signal.get("primary_country_code", "US"))
    _el(safetyreport, "transmissiondateformat", "102")
    _el(safetyreport, "transmissiondate", datetime.utcnow().strftime("%Y%m%d"))
    _el(safetyreport, "reporttype", "2")
    _el(safetyreport, "serious", "1" if signal.get("severity") in {"Critical", "High"} else "2")

    primarysource = _el(safetyreport, "primarysource")
    _el(primarysource, "qualification", "5")  # consumer
    _el(primarysource, "reportercountry", signal.get("primary_country_code", "US"))

    patient = _el(safetyreport, "patient")
    _el(patient, "patientinitial", "[REDACTED-BY-PII-VAULT]")

    reaction = _el(patient, "reaction")
    _el(reaction, "primarysourcereaction", signal.get("symptom", ""))
    _el(reaction, "reactionmeddrapt", md.get("pt", signal.get("symptom", "")))
    _el(reaction, "reactionmeddrasoc", md.get("soc", ""))
    _el(reaction, "reactionoutcome", "6")  # unknown

    drug = _el(patient, "drug")
    _el(drug, "drugcharacterization", "1")  # suspect
    _el(drug, "medicinalproduct", signal.get("drug", ""))
    if signal.get("drug_atc"):
        _el(drug, "drugatccode", signal.get("drug_atc"))
    _el(drug, "drugadministrationroute", "048")
    drugassessment = _el(drug, "drugreactionrelatedness")
    _el(drugassessment, "drugassessmentsource", "VigilAI WHO-UMC")
    _el(drugassessment, "drugresult", signal.get("who_umc", "Unassessable"))

    summary = _el(patient, "summary")
    _el(summary, "narrativeincludeclinical",
        narrative or signal.get("narrative")
        or f"Signal detected from social listening. {_stats_line(signal)}. "
           f"WHO-UMC causality: {signal.get('who_umc')}.")

    xml_bytes = tostring(root, encoding="utf-8")
    return minidom.parseString(xml_bytes).toprettyxml(indent="  ")


def generate_e2b_r2_xml(signal: dict, narrative: str = "") -> str:
    """E2B(R2) legacy ICSR (SGML-era element names)."""
    now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    md = _meddra(signal)

    root = Element("ichicsr", lang="en")
    header = _el(root, "ichicsrmessageheader")
    _el(header, "messagetype", "ichicsr")
    _el(header, "messageformatversion", "2.1")
    _el(header, "messageformatrelease", "2.0")
    _el(header, "messagenumb", f"VIGILAI-R2-{signal.get('id', 'NA')}")
    _el(header, "messagesenderidentifier", "VIGILAI")
    _el(header, "messagereceiveridentifier", "REGULATOR")
    _el(header, "messagedateformat", "204")
    _el(header, "messagedate", now)

    sr = _el(root, "safetyreport")
    _el(sr, "safetyreportversion", "1")
    _el(sr, "safetyreportid", f"VIGILAI-R2-{signal.get('id', 'NA')}")
    _el(sr, "primarysourcecountry", signal.get("primary_country_code", "US"))
    _el(sr, "occurcountry", signal.get("primary_country_code", "US"))
    _el(sr, "reporttype", "2")
    _el(sr, "serious", "1" if signal.get("severity") in {"Critical", "High"} else "2")

    ps = _el(sr, "primarysource")
    _el(ps, "qualification", "5")

    patient = _el(sr, "patient")
    _el(patient, "patientinitial", "[REDACTED-BY-PII-VAULT]")
    reaction = _el(patient, "reaction")
    _el(reaction, "primarysourcereaction", signal.get("symptom", ""))
    _el(reaction, "reactionmeddraversionpt", "27.0")
    _el(reaction, "reactionmeddrapt", md.get("pt", signal.get("symptom", "")))
    drug = _el(patient, "drug")
    _el(drug, "drugcharacterization", "1")
    _el(drug, "medicinalproduct", signal.get("drug", ""))
    _el(drug, "activesubstancename", signal.get("drug", ""))
    summary = _el(patient, "summary")
    _el(summary, "narrativeincludeclinical",
        narrative or signal.get("narrative")
        or f"Signal from social listening. {_stats_line(signal)}.")

    xml_bytes = tostring(root, encoding="utf-8")
    return minidom.parseString(xml_bytes).toprettyxml(indent="  ")
