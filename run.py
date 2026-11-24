"""
run.py - command-line entry point.

    python run.py                  chat mode: type requests such as "check order 1001"
    python run.py --reset          copy the seed data into state/ (start fresh)
    python run.py --order 1001     process one order; the seller approves in the terminal
    python run.py --all            process every order whose status is "new"
"""
import argparse
import re
from datetime import datetime

import agent
import store


def new_order_ids():
    return [o["order_id"] for o in store.read_json("orders.json") if o["status"] == "new"]


def process(order_ids, run_id):
    """Run the agent on each order, then print a short summary."""
    outcomes = {}
    for order_id in order_ids:
        print(f"\n========== Order {order_id} ==========")
        outcomes[order_id] = agent.run_episode(order_id, run_id)

    print("\n========== Summary ==========")
    for order_id, outcome in outcomes.items():
        print(f"  Order {order_id}: {outcome}")
    print("  Records: state/trace.jsonl, state/outbox.jsonl, state/shipments.json")


def find_order_id(text):
    """Find the order number in what the seller typed. Returns None unless there is exactly one."""
    numbers = re.findall(r"\d+", text)
    return numbers[0] if len(numbers) == 1 else None


def chat(run_id):
    """Chat mode. Python picks the order number out of the request; the agent does the rest."""
    print('Chat mode. Type a request such as "check order 1001", or: all, reset, quit')
    while True:
        try:
            text = input("\nseller> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        command = text.lower()
        if command == "":
            continue
        if command in ["quit", "exit"]:
            break
        if command == "reset":
            store.reset()
            print("State reset from data/seed/.")
            continue
        if command == "all":
            process(new_order_ids(), run_id)
            continue

        order_id = find_order_id(text)
        if order_id is None:
            print("Please name one order number, for example: check order 1001")
            continue
        process([order_id], run_id)


def main():
    parser = argparse.ArgumentParser(description="Order fulfillment agent")
    parser.add_argument("--reset", action="store_true", help="copy the seed data into state/")
    parser.add_argument("--order", help="process one order, for example 1001")
    parser.add_argument("--all", action="store_true", help="process every order whose status is new")
    args = parser.parse_args()

    if args.reset or not store.STATE_DIR.exists():
        store.reset()
        print("State reset from data/seed/.")
    if args.reset and not args.order and not args.all:
        return   # --reset on its own only resets

    agent.check_ollama()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if args.order:
        process([args.order], run_id)
    elif args.all:
        process(new_order_ids(), run_id)
    else:
        chat(run_id)


if __name__ == "__main__":
    main()
