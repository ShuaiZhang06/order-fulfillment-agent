"""Tests for finish(): claims are checked against the records, not taken on trust."""
import tools
from tools import book_shipment, message_buyer
from verify import finish


# --- shipped ---------------------------------------------------------------

def test_shipped_claim_without_a_shipment_is_not_supported():
    r = finish("1001", "shipped", "Done.")
    assert r["ok"] is False
    assert "no shipment was booked" in r["data"]["unmet"]


def test_shipped_claim_fails_if_the_buyer_was_not_told():
    book_shipment("1001")
    r = finish("1001", "shipped", "Done.")
    assert r["data"]["unmet"] == ["buyer was not sent a shipping_confirmation"]


def test_shipped_claim_with_full_evidence_is_verified():
    book_shipment("1001")
    message_buyer("1001", "shipping_confirmation", "Your order has shipped! Tracking number: SIM10000001.")
    assert finish("1001", "shipped", "Booked and buyer notified.")["ok"] is True


# --- cannot_ship -----------------------------------------------------------

def test_cannot_ship_needs_the_notice_to_the_buyer():
    assert finish("1002", "cannot_ship", "Not enough stock.")["ok"] is False
    message_buyer("1002", "cannot_ship_notice", "Sorry, we only have 10 mugs in stock right now.")
    assert finish("1002", "cannot_ship", "Not enough stock.")["ok"] is True


def test_wrong_outcome_for_the_order_is_caught():
    message_buyer("1001", "cannot_ship_notice", "Sorry, we cannot ship your order.")
    r = finish("1001", "cannot_ship", "Not enough stock.")
    assert "order is not short of stock" in r["data"]["unmet"]


# --- needs_info ------------------------------------------------------------

def test_needs_info_request_must_name_the_missing_field():
    message_buyer("1003", "missing_info_request", "Please send us more details.")
    r = finish("1003", "needs_info", "Asked the buyer.")
    assert r["data"]["unmet"] == ["the request to the buyer does not mention 'address'"]

    message_buyer("1003", "missing_info_request", "Please send us your shipping address.")
    assert finish("1003", "needs_info", "Asked the buyer.")["ok"] is True


# --- declined and not_found ------------------------------------------------

def test_declined_is_verified_from_the_approval_record(monkeypatch):
    monkeypatch.setattr(tools, "APPROVAL_MODE", "no")
    book_shipment("1001")
    assert finish("1001", "declined", "The seller said no.")["ok"] is True


def test_declined_claim_without_a_decline_is_not_supported():
    assert finish("1001", "declined", "The seller said no.")["ok"] is False


def test_not_found():
    assert finish("9999", "not_found", "No such order.")["ok"] is True
    assert finish("1001", "not_found", "No such order.")["ok"] is False


def test_unknown_outcome_is_refused():
    assert finish("1001", "done", "All good.")["ok"] is False
