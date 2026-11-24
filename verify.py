"""
verify.py - the finish action: check the model's claim against the records.

The model ends an order by calling finish(order_id, outcome, summary).
Python does not take the model's word for it. It looks at the shipments,
approvals and outbox in state/, and if the claim is not supported it returns
ok=False with the list of unmet conditions, so the model can fix what it missed.
"""
import store
from tools import find_order, find_shipment, result, validate_order

OUTCOMES = ["shipped", "cannot_ship", "needs_info", "declined", "not_found"]


def finish(order_id, outcome, summary):
    """The fourth action the model can choose. Its result is the evidence check."""
    if outcome not in OUTCOMES:
        return result(False, f"Unknown outcome '{outcome}'. Use one of: {', '.join(OUTCOMES)}.")
    unmet = check_claim(str(order_id), outcome)
    if unmet:
        return result(False, "Claim not supported by evidence: " + "; ".join(unmet), {"unmet": unmet})
    return result(True, f"Verified: order {order_id} is '{outcome}'.", {"outcome": outcome, "summary": summary})


def check_claim(order_id, outcome):
    """Return the conditions that are NOT met. An empty list means the claim is true."""
    order = find_order(order_id)
    if outcome == "not_found":
        return [] if order is None else ["order exists"]
    if order is None:
        return ["order does not exist"]

    shipment = find_shipment(order_id)
    decisions = [a["decision"] for a in store.read_jsonl("approvals.jsonl") if a["order_id"] == order_id]
    messages = [m for m in store.read_jsonl("outbox.jsonl") if m["order_id"] == order_id]
    sent_types = [m["message_type"] for m in messages]
    unmet = []

    if outcome == "shipped":
        confirmations = [m["text"] for m in messages if m["message_type"] == "shipping_confirmation"]
        if shipment is None:
            unmet.append("no shipment was booked")
        if "approved" not in decisions:
            unmet.append("no seller approval on record")
        if not confirmations:
            unmet.append("buyer was not sent a shipping_confirmation")
        elif shipment and shipment["tracking_number"] not in confirmations[-1]:
            unmet.append("tracking number sent to buyer does not match the shipment")
        return unmet

    # Every other outcome means nothing should have been booked.
    if shipment is not None:
        unmet.append("a shipment was booked")
    problems = validate_order(order, store.read_json("product.json"))

    if outcome == "cannot_ship":
        if "insufficient_stock" not in problems:
            unmet.append("order is not short of stock")
        if "cannot_ship_notice" not in sent_types:
            unmet.append("buyer was not sent a cannot_ship_notice")

    if outcome == "needs_info":
        missing = [p.split(":")[1] for p in problems if p.startswith("missing_field:")]
        requests = [m["text"].lower() for m in messages if m["message_type"] == "missing_info_request"]
        if not missing:
            unmet.append("order is not missing any information")
        elif not requests:
            unmet.append("buyer was not sent a missing_info_request")
        else:
            for field in missing:
                word = field.split("_")[-1]   # buyer_name -> name, address -> address
                if not any(word in text for text in requests):
                    unmet.append(f"the request to the buyer does not mention '{word}'")

    if outcome == "declined":
        if "declined" not in decisions:
            unmet.append("no seller decline on record")
        if "shipping_confirmation" in sent_types:
            unmet.append("buyer was told the order shipped")

    return unmet
