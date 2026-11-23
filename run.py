"""
run.py - command-line entry point.

    python run.py --reset          copy the seed data into state/ (start fresh)
    python run.py --order 1001     process one order; the seller approves in the terminal
    python run.py --all            process every order whose status is "new"
"""
import argparse
from datetime import datetime

import agent
import store


def main():
    parser = argparse.ArgumentParser(description="Order fulfillment agent")
    parser.add_argument("--reset", action="store_true", help="copy the seed data into state/")
    parser.add_argument("--order", help="process one order, for example 1001")
    parser.add_argument("--all", action="store_true", help="process every order whose status is new")
    args = parser.parse_args()

    if args.reset or not store.STATE_DIR.exists():
        store.reset()
        print("State reset from data/seed/.")
    if not args.order and not args.all:
        if not args.reset:
            parser.print_help()
        return

    agent.check_ollama()

    if args.all:
        order_ids = [o["order_id"] for o in store.read_json("orders.json") if o["status"] == "new"]
    else:
        order_ids = [args.order]

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    outcomes = {}
    for order_id in order_ids:
        print(f"\n========== Order {order_id} ==========")
        outcomes[order_id] = agent.run_episode(order_id, run_id)

    print("\n========== Summary ==========")
    for order_id, outcome in outcomes.items():
        print(f"  Order {order_id}: {outcome}")
    print("  Records: state/trace.jsonl, state/outbox.jsonl, state/shipments.json")


if __name__ == "__main__":
    main()
