"""
tools.py - the three tools the model can choose from.

    check_order(order_id)                        look up an order and check it
    book_shipment(order_id)                      ask the seller, then book with the simulated courier
    message_buyer(order_id, message_type, text)  write a simulated message to the buyer

Every tool returns {"ok": ..., "message": ..., "data": {...}}.
The safety rules (check again before booking, seller approval, real tracking
numbers only) are enforced here in Python. They do not depend on the model.
"""
import re
from datetime import datetime

import store

REQUIRED_FIELDS = ["buyer_name", "phone", "address"]
MESSAGE_TYPES = ["shipping_confirmation", "missing_info_request", "cannot_ship_notice"]
TRACKING_NUMBER = re.compile(r"SIM\d{8}")

# "ask"        = ask the seller in the terminal (used in the demo).
# "yes" / "no" = scripted answer, used only by evaluate.py and the tests.
APPROVAL_MODE = "ask"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def result(ok, message, data=None):
    return {"ok": ok, "message": message, "data": data or {}}


def now():
    return datetime.now().isoformat(timespec="seconds")


def find_order(order_id):
    for order in store.read_json("orders.json"):
        if order["order_id"] == str(order_id):
            return order
    return None


def find_shipment(order_id):
    for shipment in store.read_json("shipments.json"):
        if shipment["order_id"] == str(order_id):
            return shipment
    return None


def validate_order(order, product):
    """The order rules, written only here. Returns a list of problems (empty = OK)."""
    if order["status"] == "shipped":
        return ["already_shipped"]
    problems = []
    for field in REQUIRED_FIELDS:
        if not (order.get(field) or "").strip():
            problems.append("missing_field:" + field)
    if order["quantity"] > product["stock"]:
        problems.append("insufficient_stock")
    return problems


# ---------------------------------------------------------------------------
# Tool 1: check_order
# ---------------------------------------------------------------------------

def check_order(order_id):
    """Look up an order and check it. Read-only."""
    order = find_order(order_id)
    if order is None:
        return result(False, f"Order {order_id} does not exist.", {"problems": ["order_not_found"]})

    product = store.read_json("product.json")
    problems = validate_order(order, product)
    data = {
        "order": order,
        "problems": problems,
        "requested_quantity": order["quantity"],
        "available_stock": product["stock"],
        "ready_to_ship": problems == [],
    }
    if problems:
        return result(True, "Order cannot be shipped yet: " + ", ".join(problems), data)
    return result(True, "Order is complete and in stock. Ready to ship.", data)


# ---------------------------------------------------------------------------
# Tool 2: book_shipment
# ---------------------------------------------------------------------------

def ask_seller(order, product):
    """Return (approved, approver). Only 'y' or 'yes' counts as approval."""
    if APPROVAL_MODE != "ask":
        return APPROVAL_MODE == "yes", "scripted"
    print()
    print(f"  Order {order['order_id']}: {order['quantity']} x {product['name']}")
    print(f"  Ship to: {order['buyer_name']}, {order['address']}, phone {order['phone']}")
    try:
        answer = input("  Approve shipment? [y/n] ")
    except EOFError:   # no one can answer (input is closed), so treat it as "no"
        answer = ""
    return answer.strip().lower() in ["y", "yes"], "seller"


def courier_book(order):
    """Simulated courier "SimShip". Tracking numbers come from here, never from the model."""
    shipments = store.read_json("shipments.json")
    number = len(shipments) + 1
    shipment = {
        "shipment_id": f"SHP{number:03d}",
        "order_id": order["order_id"],
        "tracking_number": f"SIM{10000000 + number}",
        "carrier": "SimShip",
        "created_at": now(),
    }
    shipments.append(shipment)
    store.write_json("shipments.json", shipments)
    return shipment


def book_shipment(order_id):
    """Check the order again, ask the seller, and only then book the shipment."""
    order = find_order(order_id)
    if order is None:
        return result(False, f"Order {order_id} does not exist.", {"problems": ["order_not_found"]})

    # Check again even if check_order already ran: the model may have
    # skipped it, misread it, or passed the wrong order id.
    product = store.read_json("product.json")
    problems = validate_order(order, product)
    if problems:
        return result(False, "Booking refused: " + ", ".join(problems), {"problems": problems})

    # Nothing is booked without the seller's approval.
    approved, approver = ask_seller(order, product)
    store.append_jsonl("approvals.jsonl", {
        "order_id": order["order_id"],
        "decision": "approved" if approved else "declined",
        "approver": approver,
        "time": now(),
    })
    if not approved:
        return result(False, "The seller declined this shipment. Nothing was booked.", {"approved": False})

    shipment = courier_book(order)

    product["stock"] -= order["quantity"]
    store.write_json("product.json", product)

    orders = store.read_json("orders.json")
    for o in orders:
        if o["order_id"] == order["order_id"]:
            o["status"] = "shipped"
    store.write_json("orders.json", orders)

    return result(True, f"Shipment booked. Tracking number: {shipment['tracking_number']}.", {
        "approved": True,
        "shipment_id": shipment["shipment_id"],
        "tracking_number": shipment["tracking_number"],
        "carrier": shipment["carrier"],
    })


# ---------------------------------------------------------------------------
# Tool 3: message_buyer
# ---------------------------------------------------------------------------

def message_buyer(order_id, message_type, text):
    """Write a simulated message to the buyer (state/outbox.jsonl). Nothing is really sent."""
    order = find_order(order_id)
    if order is None:
        return result(False, f"Order {order_id} does not exist.")
    if message_type not in MESSAGE_TYPES:
        return result(False, f"Unknown message_type '{message_type}'. Use one of: {', '.join(MESSAGE_TYPES)}.")
    if not text.strip():
        return result(False, "The message text is empty.")

    # Never let a made-up tracking number reach the buyer.
    shipment = find_shipment(order_id)
    real_number = shipment["tracking_number"] if shipment else None
    for number in TRACKING_NUMBER.findall(text):
        if number != real_number:
            return result(False, f"Message refused: {number} is not the tracking number for order {order_id}.")

    if message_type == "shipping_confirmation":
        if shipment is None:
            return result(False, "Message refused: this order has no booked shipment, so it has not shipped.")
        if real_number not in text:
            return result(False, f"Message refused: a shipping confirmation must include the tracking number {real_number}.")

    store.append_jsonl("outbox.jsonl", {
        "order_id": order["order_id"],
        "to": order["buyer_name"],
        "message_type": message_type,
        "text": text,
        "time": now(),
    })
    return result(True, f"Message sent to {order['buyer_name']} (simulated).", {"message_type": message_type})
