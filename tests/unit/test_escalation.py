"""R3 escalation rules: every row of the table, first match wins, and the negatives."""
import pytest

from codeforge.policy.escalation import (
    Escalation, Signals, decide_escalation, opens_ticket, skips_generation,
)


def sig(**kw):
    base = dict(wants_human=False, sentiment="calm", urgency="low",
                unhappy_turns=0, denials=0, failed_repairs=0)
    base.update(kw)
    return Signals(**base)


@pytest.mark.parametrize("signals", [
    sig(wants_human=True, sentiment="angry"),
    sig(wants_human=True, urgency="high"),
    sig(wants_human=True, sentiment="angry", urgency="high"),
])
def test_p1_wants_human_and_angry_or_urgent(signals):
    assert decide_escalation(signals) == Escalation("P1", 1, "asked for a human; angry or urgent")


@pytest.mark.parametrize("signals,reason", [
    (sig(sentiment="angry"), "angry"),
    (sig(sentiment="angry", urgency="high"), "angry"),
    (sig(wants_human=True), "asked for a human"),
    (sig(wants_human=True, sentiment="mildly_unhappy"), "asked for a human"),
])
def test_p2_angry_or_wants_human_alone(signals, reason):
    assert decide_escalation(signals) == Escalation("P2", 4, reason)


def test_p3_two_mildly_unhappy_turns():
    assert decide_escalation(sig(sentiment="mildly_unhappy", unhappy_turns=2)) == \
        Escalation("P3", 24, "2 mildly unhappy turns")


def test_p3_two_policy_denials():
    assert decide_escalation(sig(denials=2)) == Escalation("P3", 24, "2 policy denials")


def test_p3_second_failed_repair_attempt():
    assert decide_escalation(sig(failed_repairs=2)) == \
        Escalation("P3", 24, "2 failed Repair attempts")


def test_first_match_wins():
    # P1 beats P2 and every P3 counter
    assert decide_escalation(sig(wants_human=True, sentiment="angry", unhappy_turns=5,
                                 denials=5, failed_repairs=5)).priority == "P1"
    assert decide_escalation(sig(sentiment="angry", denials=3)).priority == "P2"
    # among P3 rows the unhappy-turns reason is reported first
    assert decide_escalation(sig(unhappy_turns=2, denials=2)).reason == "2 mildly unhappy turns"


@pytest.mark.parametrize("signals", [
    sig(),                                                  # calm request
    sig(urgency="high"),                                    # urgent but calm, no human asked
    sig(sentiment="mildly_unhappy", unhappy_turns=1),       # one unhappy turn
    sig(denials=1),                                         # one denial
    sig(failed_repairs=1),                                  # first failed Repair attempt
    sig(unhappy_turns=1, denials=1, failed_repairs=1),      # counters do not add up across kinds
])
def test_negatives_open_no_ticket(signals):
    assert decide_escalation(signals) is None


def test_unknown_sentiment_is_not_angry():
    assert decide_escalation(sig(sentiment="furious")) is None


def test_only_p1_skips_generation():
    assert skips_generation("P1")
    assert not skips_generation("P2")
    assert not skips_generation("P3")
    assert not skips_generation(None)


@pytest.mark.parametrize("new,already,expected", [
    ("P3", None, True),
    ("P1", None, True),
    ("P3", "P3", False),   # same priority again in one Conversation: no second Ticket
    ("P2", "P3", True),    # stricter: a new Ticket
    ("P1", "P2", True),
    ("P3", "P1", False),   # weaker than what is already open
    ("P1", "P1", False),
])
def test_opens_ticket_only_when_new_or_stricter(new, already, expected):
    assert opens_ticket(new, already) is expected


@pytest.mark.parametrize("repairs_tried,passed,expected", [
    (0, False, 0),  # no repair (denied, rejected, P1, or first Execution failed with no budget)
    (0, True, 0),
    (1, False, 1),
    (2, False, 2),  # both repairs failed (or were rejected)
    (1, True, 0),   # repair 1 worked
    (2, True, 1),   # repair 1 failed, repair 2 worked
])
def test_failed_repairs_in_run(repairs_tried, passed, expected):
    from codeforge.policy.escalation import failed_repairs_in_run
    assert failed_repairs_in_run(repairs_tried, passed) == expected
