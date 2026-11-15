import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from trust import consent, guardrails, ledger
from trust.pii import Vault, normalise_digits


@pytest.fixture(autouse=True)
def fresh_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)


# ---------- PII ----------
@pytest.mark.parametrize("raw", [
    "my pan is ABCDE1234F",
    "aadhaar 2345 6789 0123",
    "aadhaar 234567890123",
    "call me on 98765 43210",
    "call +91 9876543210",
    "mail me at asha.k@example.com",
    "pay to asha@okaxis",
    "account number 123456789012",
])
def test_pii_is_masked_and_restorable(raw):
    vault = Vault()
    masked = vault.mask(raw)
    assert masked != raw and "[" in masked
    assert vault.reveal(masked) == raw


@pytest.mark.parametrize("spoken, label", [
    ("my pan is A B C D E 1 2 3 4 F", "PAN"),
    ("my pan is A, B, C, D, E, 1, 2, 3, 4, F", "PAN"),
    ("my pan is A B C D E 1234 F", "PAN"),
    ("my pan is abcde 1234 f", "PAN"),
    ("call 9 8 7 6 5 4 3 2 1 0", "PHONE"),
    ("aadhaar 2 3 4 5 6 7 8 9 0 1 2 3", "AADHAAR"),
])
def test_pii_spelled_out_identifiers(spoken, label):
    assert f"[{label}_1]" in Vault().mask(spoken)


def test_pii_same_value_same_token():
    vault = Vault()
    assert vault.mask("ABCDE1234F and ABCDE1234F") == "[PAN_1] and [PAN_1]"


def test_pii_indic_digits_are_seen():
    masked = Vault().mask(normalise_digits("मेरा नंबर ९८७६५४३२१०"))
    assert "[PHONE_1]" in masked


def test_pii_leaves_ordinary_text_alone():
    assert Vault().mask("the waiting period is 30 days") == "the waiting period is 30 days"


# ---------- ledger ----------
def test_ledger_chain_detects_tampering(tmp_path):
    for i in range(3):
        ledger.append("audit", "s1", {"n": i})
    assert ledger.verify() == {"intact": True, "entries": 3, "broken_at": None}

    raw = sqlite3.connect(config.LEDGER_DB)
    raw.execute("DROP TRIGGER ledger_no_update")
    raw.execute("UPDATE ledger SET payload = '{\"n\": 99}' WHERE seq = 2")
    raw.commit()
    assert ledger.verify()["broken_at"] == 2


def test_ledger_rejects_update_and_delete():
    ledger.append("audit", "s1", {"n": 1})
    raw = sqlite3.connect(config.LEDGER_DB)
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("UPDATE ledger SET kind = 'x'")
    with pytest.raises(sqlite3.DatabaseError):
        raw.execute("DELETE FROM ledger")


# ---------- consent ----------
def test_consent_lifecycle():
    assert not consent.is_active("u1", "conversation")
    consent.grant("u1", "conversation")
    assert consent.is_active("u1", "conversation")
    assert not consent.is_active("u2", "conversation")  # per subject
    assert not consent.is_active("u1", "video_kyc")     # per purpose
    consent.revoke("u1", "conversation")
    assert not consent.is_active("u1", "conversation")
    assert len(ledger.entries(subject="u1", kind="consent")) == 2  # history is kept


# ---------- guardrails ----------
SOURCES = {"pol:4.2": "4.2 Waiting periods. A waiting period of 30 days applies. Sum insured is Rs 5,00,000."}


@pytest.mark.parametrize("reply, verdict", [
    ("The waiting period is 30 days [pol:4.2].", None),
    ("The sum insured is 5,00,000 [pol:4.2].", None),
    ("The waiting period is 45 days [pol:4.2].", "ungrounded_number"),
    ("The waiting period is 30 days.", "ungrounded_number"),          # number with no citation
    ("It is covered [pol:9.9].", "unknown_citation"),
    ("You should buy the gold plan [pol:4.2].", "pressure"),
    ("I recommend this policy.", "advice"),
    ("आपको यह पॉलिसी लेनी चाहिए", "pressure"),
    ("I don't have that information.", None),
])
def test_guardrails(reply, verdict):
    assert guardrails.check_reply(reply, SOURCES) == verdict


@pytest.mark.parametrize("reply, allow, verdict", [
    ("I recommend the Lotus plan [pol:4.2].", True, None),                 # allowed when built from engine facts
    ("I recommend the Lotus plan [pol:4.2].", False, "advice"),
    ("You should buy the Lotus plan [pol:4.2].", True, "pressure"),        # never allowed
    ("You must take this plan today [pol:4.2].", True, "pressure"),
    ("Hurry, this offer is a limited-time deal [pol:4.2].", True, "pressure"),
    ("This plan guarantees you the best returns [pol:4.2].", True, "pressure"),
    ("Lotus ranks first because its premium is lowest [pol:4.2].", True, None),
])
def test_recommendation_wording(reply, allow, verdict):
    assert guardrails.check_reply(reply, SOURCES, allow_recommendation=allow) == verdict


def test_citation_helpers():
    reply = "Thirty days apply [pol:4.2]. Also see [pol:4.2] and [pol:5.1]."
    assert guardrails.citations(reply) == ["pol:4.2", "pol:5.1"]
    assert "[" not in guardrails.strip_citations(reply)
