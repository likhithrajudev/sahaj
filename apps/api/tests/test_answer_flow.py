import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import structure, suggest


def test_follow_ups_skip_what_was_just_asked_and_shown():
    first = suggest.for_intent("loan_fine_print", "en-IN", "answer", False, asked=["And what about prepayment?"])
    assert "Can I prepay without a charge?" not in first and len(first) == 3
    second = suggest.for_intent("loan_fine_print", "en-IN", "answer", False, asked=[], shown=first)
    assert not set(first) & set(second) and len(second) == 3
    assert all("insurance" not in c.lower() for c in second)   # topped up from the loan domain first


def test_no_follow_ups_while_asking_or_with_a_person():
    assert suggest.for_intent("loan_fine_print", "en-IN", "ask", False) == []
    assert suggest.for_intent("loan_fine_print", "en-IN", "answer", True) == []


def test_a_stock_opener_is_not_the_headline():
    view = structure.build("Good question. A processing fee of 2 percent applies. [kfs:2.1]", [], {"kfs:2.1": "x"}, "answer")
    assert view["summary"].startswith("A processing fee") and len(view["points"]) == 1
    only = structure.build("Sure.", [], {}, "answer")
    assert only["summary"] == "Sure."


def test_the_human_option_survives_and_chips_stay_on_topic():
    chips = suggest.for_intent("loan_fine_print", "en-IN", "answer", False,
                               asked=["What hidden charges should I look for in a personal loan?", "And what about prepayment?"],
                               shown=["What will I pay in total?", "Work out my EMI", "What happens if I miss a payment?"])
    assert "Talk to a person" in chips and not any("plan" in c or "covered" in c for c in chips)
