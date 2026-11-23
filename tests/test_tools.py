"""Tests for the three tools. No model is needed."""
import pytest

import store
import tools
from tools import book_shipment, check_order, find_order, message_buyer, validate_order


# --- check_order -----------------------------------------------------------

def test_rules_for_the_three_sample_orders():
    product = store.read_json("product.json")
    assert validate_order(find_order("1001"), product) == []
    assert validate_order(find_order("1002"), product) == ["insufficient_stock"]
    assert validate_order(find_order("1003"), product) == ["missing_field:address"]


def test_check_order_reports_ready_to_ship():
    r = check_order("1001")
    assert r["ok"] is True
    assert r["data"]["ready_to_ship"] is True


def test_check_order_reports_stock_numbers():
    r = check_order("1002")
    assert r["data"]["ready_to_ship"] is False
    assert r["data"]["requested_quantity"] == 12
    assert r["data"]["available_stock"] == 10


def test_check_order_unknown_order():
    r = check_order("9999")
    assert r["ok"] is False
    assert r["data"]["problems"] == ["order_not_found"]


def test_order_id_can_be_a_number():
    # The model may send 1001 instead of "1001".
    assert check_order(1001)["data"]["ready_to_ship"] is True


# --- book_shipment ---------------------------------------------------------

def test_invalid_order_is_refused_before_asking_the_seller(monkeypatch):
    monkeypatch.setattr(tools, "APPROVAL_MODE", "ask")

    def fail_if_asked(prompt):
        raise AssertionError("The seller should not be asked about an invalid order.")

    monkeypatch.setattr("builtins.input", fail_if_asked)
    r = book_shipment("1003")
    assert r["ok"] is False
    assert r["data"]["problems"] == ["missing_field:address"]
    assert store.read_json("shipments.json") == []
    assert store.read_jsonl("approvals.jsonl") == []


def test_approved_booking_creates_shipment_and_updates_stock():
    r = book_shipment("1001")
    assert r["ok"] is True
    assert r["data"]["tracking_number"] == "SIM10000001"
    assert len(store.read_json("shipments.json")) == 1
    assert store.read_json("product.json")["stock"] == 8
    assert find_order("1001")["status"] == "shipped"
    assert store.read_jsonl("approvals.jsonl")[0]["decision"] == "approved"


def test_declined_booking_books_nothing(monkeypatch):
    monkeypatch.setattr(tools, "APPROVAL_MODE", "no")
    r = book_shipment("1001")
    assert r["ok"] is False
    assert r["data"]["approved"] is False
    assert store.read_json("shipments.json") == []
    assert store.read_json("product.json")["stock"] == 10
    assert find_order("1001")["status"] == "new"
    assert store.read_jsonl("approvals.jsonl")[0]["decision"] == "declined"


@pytest.mark.parametrize("answer, approved", [
    ("y", True), ("YES", True), (" y ", True),
    ("n", False), ("", False), ("ok", False),
])
def test_only_y_or_yes_counts_as_seller_approval(monkeypatch, answer, approved):
    monkeypatch.setattr(tools, "APPROVAL_MODE", "ask")
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    r = book_shipment("1001")
    assert r["ok"] is approved
    assert store.read_jsonl("approvals.jsonl")[0]["approver"] == "seller"


def test_same_order_cannot_be_booked_twice():
    book_shipment("1001")
    r = book_shipment("1001")
    assert r["ok"] is False
    assert r["data"]["problems"] == ["already_shipped"]
    assert len(store.read_json("shipments.json")) == 1


# --- message_buyer ---------------------------------------------------------

def test_message_is_written_to_the_outbox():
    r = message_buyer("1003", "missing_info_request", "Please send us your shipping address.")
    assert r["ok"] is True
    sent = store.read_jsonl("outbox.jsonl")
    assert sent[0]["order_id"] == "1003"
    assert sent[0]["message_type"] == "missing_info_request"


def test_shipping_confirmation_needs_a_real_shipment():
    r = message_buyer("1003", "shipping_confirmation", "Your order has shipped!")
    assert r["ok"] is False
    assert store.read_jsonl("outbox.jsonl") == []


def test_made_up_tracking_number_is_refused():
    book_shipment("1001")
    r = message_buyer("1001", "shipping_confirmation", "Shipped! Tracking number SIM99999999.")
    assert r["ok"] is False
    assert store.read_jsonl("outbox.jsonl") == []


def test_tracking_number_on_an_unshipped_order_is_refused():
    r = message_buyer("1002", "cannot_ship_notice", "Sorry. Tracking number SIM10000001.")
    assert r["ok"] is False


def test_confirmation_must_include_the_tracking_number():
    book_shipment("1001")
    assert message_buyer("1001", "shipping_confirmation", "Your order has shipped!")["ok"] is False
    r = message_buyer("1001", "shipping_confirmation", "Your order has shipped! Tracking number: SIM10000001.")
    assert r["ok"] is True


def test_unknown_message_type_is_refused():
    assert message_buyer("1003", "reminder", "Hi there")["ok"] is False


def test_message_for_unknown_order_is_refused():
    assert message_buyer("9999", "missing_info_request", "Hi")["ok"] is False
