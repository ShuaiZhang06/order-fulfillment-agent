"""Tests for evaluate.py. A fake model is used, so no Ollama is needed."""
import json

import evaluate
import store
import verify
from test_agent import reply, use_fake_model

CASES = json.loads(evaluate.CASES_FILE.read_text())


def test_expected_cases_are_well_formed():
    for case in CASES:
        assert case["approval"] in ["yes", "no"]
        assert case["expected"]["outcome"] in verify.OUTCOMES


# --- safety_counts: read straight from the records ---------------------------

def test_safety_counts_are_zero_on_fresh_data():
    assert evaluate.safety_counts() == {
        "unapproved_bookings": 0, "tracking_mismatches": 0, "duplicate_bookings": 0}


def test_safety_counts_catch_a_booking_with_no_approval():
    # Write a shipment directly, bypassing book_shipment, to prove the count
    # comes from the records and not from trusting the tools.
    store.write_json("shipments.json", [{"order_id": "1001", "tracking_number": "SIM10000001"}])
    assert evaluate.safety_counts()["unapproved_bookings"] == 1


def test_safety_counts_catch_a_fake_tracking_number():
    store.append_jsonl("outbox.jsonl", {"order_id": "1001", "message_type": "shipping_confirmation",
                                        "text": "Tracking number SIM12345678"})
    assert evaluate.safety_counts()["tracking_mismatches"] == 1


def test_safety_counts_catch_a_duplicate_booking():
    shipment = {"order_id": "1001", "tracking_number": "SIM10000001"}
    store.write_json("shipments.json", [shipment, shipment])
    store.append_jsonl("approvals.jsonl", {"order_id": "1001", "decision": "approved"})
    assert evaluate.safety_counts()["duplicate_bookings"] == 1


# --- compare ---------------------------------------------------------------

def good_actual():
    return {"outcome": "needs_info", "booked": False, "buyer_messages": ["missing_info_request"],
            "stock_after": 10, "safety": evaluate.safety_counts()}


def test_compare_passes_when_everything_matches():
    expected = CASES[2]["expected"]   # 1003 missing address
    assert evaluate.compare(expected, good_actual()) == []


def test_compare_lists_every_difference():
    expected = CASES[2]["expected"]
    actual = good_actual()
    actual["outcome"] = "cannot_ship"
    actual["buyer_messages"] = ["missing_info_request", "cannot_ship_notice"]
    problems = evaluate.compare(expected, actual)
    assert len(problems) == 2
    assert "outcome is cannot_ship" in problems[0]


def test_compare_fails_when_buyer_is_messaged_but_should_not_be():
    expected = CASES[3]["expected"]   # 1001 seller declines
    actual = {"outcome": "declined", "booked": False, "buyer_messages": ["cannot_ship_notice"],
              "stock_after": 10, "safety": evaluate.safety_counts()}
    assert evaluate.compare(expected, actual) != []


# --- run_case --------------------------------------------------------------

def test_run_case_collects_the_actual_records(monkeypatch):
    use_fake_model(monkeypatch, [
        reply("check_order", order_id="1001"),
        reply("book_shipment", order_id="1001"),
        reply("message_buyer", order_id="1001", message_type="shipping_confirmation",
              text="Shipped! Tracking number: SIM10000001."),
        reply("finish", order_id="1001", outcome="shipped", summary="Shipped."),
    ])
    actual = evaluate.run_case(CASES[0], "test")
    assert actual["steps"] == 4
    assert evaluate.compare(CASES[0]["expected"], actual) == []
    assert store.read_jsonl("approvals.jsonl")[0]["approver"] == "scripted"


def test_run_case_uses_the_scripted_decline(monkeypatch):
    use_fake_model(monkeypatch, [
        reply("check_order", order_id="1001"),
        reply("book_shipment", order_id="1001"),
        reply("finish", order_id="1001", outcome="declined", summary="The seller declined."),
    ])
    actual = evaluate.run_case(CASES[3], "test")
    assert evaluate.compare(CASES[3]["expected"], actual) == []
    assert store.read_jsonl("approvals.jsonl")[0]["decision"] == "declined"
