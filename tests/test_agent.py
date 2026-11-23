"""Tests for the agent loop. A fake model replies from a script, so no Ollama is needed."""
import json

import pytest

import agent
import store


def reply(action, **argument):
    """Build a model reply in the format the system prompt asks for."""
    return json.dumps({"reason": "test", "action": action, "argument": argument})


def use_fake_model(monkeypatch, replies):
    """Replace the real model with one that returns these replies, in order."""
    replies = list(replies)
    monkeypatch.setattr(agent, "ask_model", lambda messages: replies.pop(0))


# --- parse_reply -----------------------------------------------------------

def test_valid_reply_is_accepted():
    r, error = agent.parse_reply(reply("check_order", order_id="1001"), "1001")
    assert error is None
    assert r["action"] == "check_order"


@pytest.mark.parametrize("raw, expected_error", [
    ("not json", "not valid JSON"),
    ('["a list"]', "must be a JSON object"),
    (reply("refund", order_id="1001"), "Unknown action"),
    (json.dumps({"action": "check_order", "argument": "1001"}), "argument must be a JSON object"),
    (reply("message_buyer", order_id="1001", text="Hi"), "needs these arguments: message_type"),
    (reply("check_order", order_id="1003"), "You are processing order 1001"),
])
def test_bad_replies_are_explained_to_the_model(raw, expected_error):
    r, error = agent.parse_reply(raw, "1001")
    assert r is None
    assert expected_error in error


def test_missing_reason_is_allowed():
    raw = json.dumps({"action": "check_order", "argument": {"order_id": "1001"}})
    r, error = agent.parse_reply(raw, "1001")
    assert r["reason"] == ""


# --- run_tool --------------------------------------------------------------

def test_extra_arguments_are_ignored():
    assert agent.run_tool("check_order", {"order_id": "1001", "extra": 1})["ok"] is True


def test_tool_crash_becomes_a_failed_result():
    r = agent.run_tool("message_buyer", {"order_id": "1003", "message_type": "missing_info_request", "text": None})
    assert r["ok"] is False
    assert "Tool error" in r["message"]


# --- run_episode -----------------------------------------------------------

def test_happy_path_for_order_1001(monkeypatch):
    use_fake_model(monkeypatch, [
        reply("check_order", order_id="1001"),
        reply("book_shipment", order_id="1001"),
        reply("message_buyer", order_id="1001", message_type="shipping_confirmation",
              text="Your mugs have shipped! Tracking number: SIM10000001."),
        reply("finish", order_id="1001", outcome="shipped", summary="Shipped and buyer notified."),
    ])
    assert agent.run_episode("1001", "test") == "shipped"
    assert len(store.read_jsonl("trace.jsonl")) == 4


def test_tool_results_are_given_back_to_the_model(monkeypatch):
    seen = []
    replies = [
        reply("check_order", order_id="1002"),
        reply("message_buyer", order_id="1002", message_type="cannot_ship_notice", text="Sorry, not enough stock."),
        reply("finish", order_id="1002", outcome="cannot_ship", summary="Asked for 12, only 10 in stock."),
    ]

    def fake_model(messages):
        seen.append(list(messages))
        return replies.pop(0)

    monkeypatch.setattr(agent, "ask_model", fake_model)
    assert agent.run_episode("1002", "test") == "cannot_ship"
    # When the model chose its second action, it had seen check_order's result.
    assert "insufficient_stock" in seen[1][-1]["content"]


def test_failed_finish_lets_the_model_fix_its_mistake(monkeypatch):
    use_fake_model(monkeypatch, [
        reply("check_order", order_id="1003"),
        reply("finish", order_id="1003", outcome="needs_info", summary="Asked the buyer."),  # forgot the message
        reply("message_buyer", order_id="1003", message_type="missing_info_request",
              text="Please send us your shipping address."),
        reply("finish", order_id="1003", outcome="needs_info", summary="Asked the buyer."),
    ])
    assert agent.run_episode("1003", "test") == "needs_info"
    trace = store.read_jsonl("trace.jsonl")
    assert trace[1]["result"]["ok"] is False   # the first finish was not supported by evidence


def test_invalid_replies_stop_at_the_step_limit(monkeypatch):
    use_fake_model(monkeypatch, ["not json"] * agent.MAX_STEPS)
    assert agent.run_episode("1001", "test") == "step_limit"
    assert len(store.read_jsonl("trace.jsonl")) == agent.MAX_STEPS
    assert store.read_json("shipments.json") == []
