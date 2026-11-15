"""Messages a person must see, whatever the AI could answer: a complaint, or someone in distress. Checked on every message
before the AI. Deliberately narrow: a false alarm costs an executive a minute, a miss costs much more, but a hospital
admission is the start of a claim, not distress, and must stay with the claim journey."""
import re
from typing import Optional

DISTRESS = [re.compile(p, re.I) for p in (
    r"\b(kill|hurt) myself\b", r"\bsuicid", r"\bend (my|it all|my life)\b", r"\bwant to die\b", r"\bno reason to live\b",
    r"\b(recovery|collection) agents?\b.{0,40}\b(threat|abus|harass|beat|home|family)", r"\b(threaten|harass)\w*\b.{0,30}\b(loan|recovery|agent)",
    r"आत्महत्या", r"मर जाना चाहता", r"मरना चाहती", r"जान दे दूँगा", r"धमकी", r"marna chahta", r"jaan de dunga", r"dhamki",
)]
COMPLAINT = [re.compile(p, re.I) for p in (
    r"\bcomplain", r"\bgrievance\b", r"\bfraud\b", r"\bscam\b", r"\bcheat(ed|ing)?\b", r"\bmis-?sold\b", r"\bombudsman\b",
    r"\bconsumer (court|forum)\b", r"\blegal (action|notice)\b", r"\bunauthori[sz]ed (debit|deduction|charge)",
    r"शिकायत", r"धोखा", r"फ्रॉड", r"ठगी", r"\bshikayat\b", r"\bdhokha\b", r"\bthagi\b",
)]


def detect(text: str) -> Optional[str]:
    """'distress', 'complaint' or None."""
    if any(p.search(text) for p in DISTRESS):
        return "distress"
    if any(p.search(text) for p in COMPLAINT):
        return "complaint"
    return None


ACK = {
    "distress": {"en-IN": "I'm bringing in a person from our team right now. Please stay with me.",
                 "hi-IN": "मैं अभी हमारी टीम के एक व्यक्ति को बुला रहा हूँ। कृपया जुड़े रहिए।"},
    "complaint": {"en-IN": "I'm sorry about this. I'm passing your complaint to a person from our team, who will take it from here.",
                  "hi-IN": "इसके लिए खेद है। मैं आपकी शिकायत हमारी टीम के एक व्यक्ति को दे रहा हूँ, जो इसे आगे देखेंगे।"},
}


def acknowledgement(reason: str, lang: str) -> str:
    table = ACK[reason]
    return table.get(lang, table["en-IN"])
