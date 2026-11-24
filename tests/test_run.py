"""Tests for chat mode in run.py. A fake model is used, so no Ollama is needed."""
import pytest

import run
import store
from test_agent import reply, use_fake_model


@pytest.mark.parametrize("text, order_id", [
    ("check order 1001", "1001"),
    ("what about 1003?", "1003"),
    ("Process order #1002 please", "1002"),
    ("hello", None),
    ("check 1001 and 1003", None),   # more than one order: ask for one
])
def test_find_order_id(text, order_id):
    assert run.find_order_id(text) == order_id


def test_chat_runs_the_agent_on_the_order_the_seller_names(monkeypatch):
    typed = ["hello", "check order 9999", "quit"]
    monkeypatch.setattr("builtins.input", lambda prompt: typed.pop(0))
    use_fake_model(monkeypatch, [
        reply("check_order", order_id="9999"),
        reply("finish", order_id="9999", outcome="not_found", summary="No such order."),
    ])
    run.chat("test")
    trace = store.read_jsonl("trace.jsonl")
    assert [step["order_id"] for step in trace] == ["9999", "9999"]
    assert trace[-1]["result"]["ok"] is True


def test_chat_stops_when_input_ends(monkeypatch):
    def input_closed(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", input_closed)
    run.chat("test")   # returns instead of crashing
