"""Field extraction and checklist for the Star Health and illustrative loan demos."""

import re
from decimal import Decimal, InvalidOperation

CLAIMS_SOURCE_URL = "https://www.starhealth.in/claims/#claim-process"
LOAN_SOURCE_URL = "https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12987#:~:text=Illustration%20for%20computation%20of%20APR"
LABELS = {
    "patient_name": "Patient name", "hospital": "Hospital", "admitted": "Admission date",
    "discharged": "Discharge date", "bill_number": "Hospital bill number", "hospital_total": "Hospital bill (₹)",
    "pharmacy_total": "Pharmacy bill (₹)", "applicant_name": "Applicant name", "employer": "Employer",
    "net_pay": "Monthly net pay (₹)", "purpose": "Loan purpose",
}
CONTEXT = {
    "claim": {
        "Discharge summary": ("patient_name", "hospital", "admitted", "discharged"),
        "Hospital bill": ("patient_name", "bill_number", "hospital_total"),
        "Pharmacy bill": ("patient_name", "pharmacy_total"),
        "Prescription": ("patient_name",),
    },
    "loan": {"Payslip": ("applicant_name", "employer", "net_pay")},
}
REQUIRED = {
    "claim": ["patient_name", "hospital", "admitted", "discharged", "bill_number", "hospital_total"],
    "loan": ["applicant_name", "employer", "net_pay", "purpose"],
}
OFFER = {
    "label": "RBI illustrative loan", "principal": 20000, "net_disbursed": 19600,
    "charges": 400, "months": 24, "monthly_rounded": 970, "total_repayment": 23274, "apr_percent": 17.07,
    "source_url": LOAN_SOURCE_URL,
}


def money(value):
    value = re.sub(r"(?i)\b(?:INR|Rs\.?)\s*", "", value).replace("₹", "").replace(",", "").strip()
    try:
        amount = Decimal(value)
        if amount.is_finite() and 0 < amount <= 100_000_000 and amount == amount.quantize(Decimal(".01")):
            return f"{amount:.2f}"
    except InvalidOperation:
        pass
    return ""


def date_value(value):
    from datetime import date, datetime

    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value).isoformat()
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(value, pattern).date().isoformat()
            except ValueError:
                continue
    except ValueError:
        pass
    return ""


PATTERNS = {
    "patient_name": r"patient(?: name)?", "hospital": r"hospital(?: name)?",
    "admitted": r"(?:admission date|date of admission|admitted on)",
    "discharged": r"(?:discharge date|date of discharge|discharged on)",
    "bill_number": r"(?:bill|invoice)\s*(?:number|no\.?|#)", "hospital_total": r"(?:grand total|amount paid|total amount|total)",
    "pharmacy_total": r"(?:grand total|amount paid|total amount|total)",
    "applicant_name": r"(?:employee name|applicant name|employee)", "employer": r"(?:employer|company name)",
    "net_pay": r"(?:net pay|take.home pay|net salary)",
}
MONEY_FIELDS = {"hospital_total", "pharmacy_total", "net_pay"}
DATE_FIELDS = {"admitted", "discharged"}


def extract_fields(kind, text):
    markers = {
        "Discharge summary": r"discharge summary", "Hospital bill": r"hospital (?:final )?(?:bill|invoice)",
        "Pharmacy bill": r"pharmacy (?:bill|invoice|receipt)", "Prescription": r"(?:doctor.s )?prescription",
        "Payslip": r"pay\s*slip|salary slip",
    }
    title = "\n".join(line for line in text.splitlines()[:7] if ":" not in line)
    found = next((doc_type for doc_type in CONTEXT[kind] if re.search(markers[doc_type], title, re.I)), "Other")
    fields = {}
    for field in CONTEXT[kind].get(found, ()):
        match = re.search(rf"(?im)^\s*(?:{PATTERNS[field]})[ \t]*[:：][ \t]*([^\r\n]+)", text)
        if not match:
            continue
        value = " ".join(match[1].split())[:160]
        if field in MONEY_FIELDS:
            value = money(value)
        if field in DATE_FIELDS:
            value = date_value(value)
        if value:
            fields[field] = value
    return found, fields


def state_view(state):
    kind = state["kind"]
    kinds = {item["type"] for item in state["documents"]}
    checklist = {}
    if kind == "claim":
        required_docs = ["Discharge summary", "Hospital bill"]
        if "Pharmacy bill" in kinds:
            required_docs.append("Prescription")
    else:
        required_docs = ["Payslip"]
    for item in required_docs:
        checklist[item] = item in kinds
    conflicts = {}
    observed = {}
    for item in state["documents"]:
        for key, value in item["fields"].items():
            observed.setdefault(key, {})[value.casefold()] = value
    for key, values in observed.items():
        if len(values) > 1 and key not in state["reviewed"]:
            conflicts[key] = list(values.values())
    fields = {key: next(iter(values.values())) for key, values in observed.items() if len(values) == 1}
    fields.update(state["reviewed"])
    required_fields = REQUIRED[kind].copy()
    if kind == "claim" and "Pharmacy bill" in kinds:
        required_fields.append("pharmacy_total")
    fields = {key: value for key, value in fields.items() if key in required_fields}
    complete = all(checklist.values()) and not conflicts and all(fields.get(key) for key in required_fields)
    status = "submitted" if state["reference"] else "ready" if complete and state["confirmed"] else "draft"
    additional = {"offer": OFFER} if kind == "loan" else {"checklist_source_url": CLAIMS_SOURCE_URL}
    return {
        **state, **additional, "checklist": checklist, "conflicts": conflicts, "fields": fields,
        "field_labels": {key: LABELS[key] for key in required_fields}, "status": status,
        "missing_fields": [key for key in required_fields if not fields.get(key)],
    }
