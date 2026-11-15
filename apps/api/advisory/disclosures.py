"""Fixed disclosure text shown with every recommendation. Never written by the model.

DRAFTS: the wording, the missing items (for example how Sahaj is paid, and its IRDAI registration details),
and every translation beyond English and Hindi need compliance approval. Other languages fall back to English.
"""
VERSION = "2026-11-draft-1"

TEXT = {
    "en-IN": [
        "These suggestions are based only on the information you gave me, and nothing else.",
        "Premiums shown are indicative. The insurer decides the final premium and whether to accept you, after its own checks.",
        "Please read the policy wording before you buy, especially the waiting periods and exclusions. You can cancel within the free-look period.",
        "Plans are ranked using only the criteria shown with them.",
        "You can ask to talk to a person at any time.",
    ],
    "hi-IN": [
        "ये सुझाव केवल आपकी दी हुई जानकारी पर आधारित हैं, और किसी चीज़ पर नहीं।",
        "दिखाए गए प्रीमियम केवल अनुमानित हैं। अंतिम प्रीमियम और आपको स्वीकार करना है या नहीं, यह बीमा कंपनी अपनी जाँच के बाद तय करती है।",
        "खरीदने से पहले पॉलिसी का विवरण ज़रूर पढ़ें, ख़ासकर प्रतीक्षा अवधि और अपवाद। फ़्री-लुक अवधि के भीतर आप पॉलिसी रद्द कर सकते हैं।",
        "योजनाओं को केवल उन्हीं मानदंडों से क्रमबद्ध किया गया है जो उनके साथ दिखाए गए हैं।",
        "आप कभी भी किसी व्यक्ति से बात करने के लिए कह सकते हैं।",
    ],
}


def disclosures(language_code: str) -> list:
    return TEXT.get(language_code, TEXT["en-IN"])
