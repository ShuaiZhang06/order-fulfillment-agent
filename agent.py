"""
agent.py - the agent loop.

For one order, repeat:
    1. ask the model what to do next
    2. check its reply
    3. run the tool it picked
    4. record the step and give the result back to the model
    5. stop when finish() is verified against the records, or after MAX_STEPS

The model only chooses actions and writes text. Python runs the tools,
enforces the safety rules, and decides whether a claimed outcome is true.
"""
import json
import os
import sys

import requests

import store
import tools
import verify

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
TEMPERATURE = 0.6   # the Ollama default for qwen3:8b (PRD 7.1)
MAX_STEPS = 8

# The model picks an action by name; Python looks up the function here.
TOOLS = {
    "check_order": tools.check_order,
    "book_shipment": tools.book_shipment,
    "message_buyer": tools.message_buyer,
    "finish": verify.finish,
}

# The arguments each action needs.
ARGUMENTS = {
    "check_order": ["order_id"],
    "book_shipment": ["order_id"],
    "message_buyer": ["order_id", "message_type", "text"],
    "finish": ["order_id", "outcome", "summary"],
}

SYSTEM_PROMPT = """You are an order-fulfillment assistant for a small online shop that sells one product.
You handle ONE order at a time. Choose the next action based on the results you have seen so far.

Actions:
- check_order(order_id): look up the order and check it. Always do this first.
- book_shipment(order_id): ask the seller to approve, then book the shipment with the courier.
  Only use it when check_order says ready_to_ship is true.
- message_buyer(order_id, message_type, text): send a message to the buyer.
  message_type is one of: shipping_confirmation, missing_info_request, cannot_ship_notice.
- finish(order_id, outcome, summary): end this order and report to the seller.
  outcome is one of: shipped, cannot_ship, needs_info, declined, not_found.
  summary is one or two sentences for the seller.

Rules:
- Information missing: send a missing_info_request that names the missing field, then finish with needs_info.
- Not enough stock: send a cannot_ship_notice, then finish with cannot_ship.
  In the summary, tell the seller how many were requested and how many are in stock.
- Booking succeeded: send a shipping_confirmation that includes the tracking number from book_shipment,
  then finish with shipped.
- Seller declined: do not message the buyer. Finish with declined.
- Order does not exist: finish with not_found.
- Never invent a tracking number. Only use the one returned by book_shipment.
- If a result has "ok": false, read its message and decide what to do next.

Reply with JSON only, in exactly this format:
{"reason": "<one short sentence>", "action": "<action name>", "argument": {<arguments>}}"""


def check_ollama():
    """Stop early with a clear message if Ollama is not running or the model is missing."""
    try:
        tags = requests.get(OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5).json()
    except requests.RequestException:
        sys.exit("Cannot reach Ollama. Start it with:  ollama serve")
    installed = [m["name"] for m in tags.get("models", [])]
    if MODEL not in installed:
        sys.exit(f"Model {MODEL} is not installed. Download it with:  ollama pull {MODEL}")


def ask_model(messages):
    response = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": TEMPERATURE},
    }, timeout=180)
    response.raise_for_status()
    return response.json()["message"]["content"]


def parse_reply(raw, order_id):
    """Check the model's reply. Returns (reply, None) if it is usable, or (None, error)."""
    try:
        reply = json.loads(raw)
    except ValueError:
        return None, "Your reply was not valid JSON."
    if not isinstance(reply, dict):
        return None, "Your reply must be a JSON object with reason, action and argument."

    action = reply.get("action")
    argument = reply.get("argument")
    if action not in TOOLS:
        return None, f"Unknown action '{action}'. Choose one of: {', '.join(TOOLS)}."
    if not isinstance(argument, dict):
        return None, "argument must be a JSON object."
    missing = [name for name in ARGUMENTS[action] if name not in argument]
    if missing:
        return None, f"{action} needs these arguments: {', '.join(missing)}."
    # One run handles one order, so every action must be about that order.
    if str(argument["order_id"]) != str(order_id):
        return None, f"You are processing order {order_id}. Use order_id {order_id}."

    reply.setdefault("reason", "")
    return reply, None


def run_tool(action, argument):
    """Call the function for this action. A crash becomes a normal failed result."""
    args = {name: argument[name] for name in ARGUMENTS[action]}
    try:
        return TOOLS[action](**args)
    except Exception as error:
        return {"ok": False, "message": f"Tool error: {type(error).__name__}: {error}", "data": {}}


def run_episode(order_id, run_id):
    """Process one order. Returns the verified outcome, or "step_limit"."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Process order {order_id}."},
    ]

    for step in range(1, MAX_STEPS + 1):
        # 1. Ask the model what to do next.
        raw = ask_model(messages)
        messages.append({"role": "assistant", "content": raw})

        # 2. Check the reply.  3. Run the tool the model picked.
        reply, error = parse_reply(raw, order_id)
        if error:
            print(f"\n[{order_id}] step {step}  INVALID REPLY  {raw[:200]}")
            result = {"ok": False, "message": error, "data": {}}
        else:
            print(f"\n[{order_id}] step {step}  MODEL   {reply['reason']}")
            print(f"           ACTION  {reply['action']} {json.dumps(reply['argument'])}")
            result = run_tool(reply["action"], reply["argument"])
        print(f"           RESULT  {'ok' if result['ok'] else 'FAILED'}: {result['message']}")

        # 4. Record the step and give the result back to the model.
        store.append_jsonl("trace.jsonl", {
            "run_id": run_id,
            "order_id": str(order_id),
            "step": step,
            "model_reply": reply if reply else raw,
            "result": result,
            "time": tools.now(),
        })
        messages.append({"role": "user", "content": "Result: " + json.dumps(result)})

        # 5. Stop only when finish() has been verified against the records.
        if reply and reply["action"] == "finish" and result["ok"]:
            print(f"\n[{order_id}] DONE  outcome '{result['data']['outcome']}' verified.")
            print(f"           Report to seller: {result['data']['summary']}")
            return result["data"]["outcome"]

    print(f"\n[{order_id}] STOPPED  {MAX_STEPS} steps used without a verified finish.")
    return "step_limit"
