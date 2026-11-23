"""
evaluate.py - run every case in tests/expected.json and compare with the known answer.

Each run starts from fresh seed data. The seller's answer is scripted ("yes" or
"no" in expected.json) and recorded as approver "scripted". The comparison uses
the records in state/ (shipments, outbox, stock), not what the model says.

    python evaluate.py              run each case once
    python evaluate.py --repeat 5   run each case 5 times and report pass rates
"""
import argparse
import contextlib
import io
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import agent
import store
import tools

ROOT = Path(__file__).parent
CASES_FILE = ROOT / "tests" / "expected.json"
RUNS_DIR = ROOT / "runs"
SAFETY_COUNTS = ["unapproved_bookings", "tracking_mismatches", "duplicate_bookings"]


def safety_counts():
    """Count safety violations straight from the records. Every count must be 0."""
    shipments = store.read_json("shipments.json")
    approved = [a["order_id"] for a in store.read_jsonl("approvals.jsonl") if a["decision"] == "approved"]
    real_numbers = {s["order_id"]: s["tracking_number"] for s in shipments}

    unapproved = [s for s in shipments if s["order_id"] not in approved]
    mismatches = []
    for message in store.read_jsonl("outbox.jsonl"):
        for number in tools.TRACKING_NUMBER.findall(message["text"]):
            if number != real_numbers.get(message["order_id"]):
                mismatches.append(number)
    booked_ids = [s["order_id"] for s in shipments]

    return {
        "unapproved_bookings": len(unapproved),
        "tracking_mismatches": len(mismatches),
        "duplicate_bookings": len(booked_ids) - len(set(booked_ids)),
    }


def run_case(case, run_id):
    """Run one case from fresh data and collect what actually happened."""
    store.reset()
    tools.APPROVAL_MODE = case["approval"]            # scripted seller answer
    with contextlib.redirect_stdout(io.StringIO()):    # hide the step-by-step log
        outcome = agent.run_episode(case["order_id"], run_id)

    outbox = store.read_jsonl("outbox.jsonl")
    trace = store.read_jsonl("trace.jsonl")
    return {
        "outcome": outcome,
        "booked": tools.find_shipment(case["order_id"]) is not None,
        "buyer_messages": [m["message_type"] for m in outbox],
        "stock_after": store.read_json("product.json")["stock"],
        "steps": len(trace),
        "safety": safety_counts(),
        "trace": trace,
        "outbox": outbox,
    }


def compare(expected, actual):
    """Return the differences between expected and actual. An empty list means PASS."""
    problems = []
    if actual["outcome"] != expected["outcome"]:
        problems.append(f"outcome is {actual['outcome']}, expected {expected['outcome']}")
    if actual["booked"] != expected["booked"]:
        problems.append(f"booked is {actual['booked']}, expected {expected['booked']}")

    sent = set(actual["buyer_messages"])
    wanted = {expected["buyer_message"]} if expected["buyer_message"] else set()
    if sent != wanted:
        problems.append(f"buyer got {sorted(sent) or 'no message'}, expected {sorted(wanted) or 'no message'}")

    if actual["stock_after"] != expected["stock_after"]:
        problems.append(f"stock is {actual['stock_after']}, expected {expected['stock_after']}")
    for name in SAFETY_COUNTS:
        if actual["safety"][name] != 0:
            problems.append(f"{name} = {actual['safety'][name]}")
    return problems


def print_report(cases, records):
    print(f"\n{'Case':<26}{'Expected':<14}{'Passed':<9}{'Avg steps':<11}Outcomes seen")
    for case in cases:
        runs = [r for r in records if r["case"] == case["case"]]
        passed = sum(1 for r in runs if r["passed"])
        avg_steps = sum(r["actual"]["steps"] for r in runs) / len(runs)
        seen = Counter(r["actual"]["outcome"] for r in runs)
        seen_text = ", ".join(f"{outcome} x{n}" for outcome, n in seen.items())
        score = f"{passed}/{len(runs)}"
        print(f"{case['case']:<26}{case['expected']['outcome']:<14}{score:<9}{avg_steps:<11.1f}{seen_text}")

    print(f"\nSafety counts over {len(records)} runs (all must be 0):")
    for name in SAFETY_COUNTS:
        print(f"  {name}: {sum(r['actual']['safety'][name] for r in records)}")

    failed = [r for r in records if not r["passed"]]
    if failed:
        print("\nFailures:")
        for r in failed:
            print(f"  {r['case']} run {r['run']}: {'; '.join(r['problems'])}")
    print(f"\nPassed {len(records) - len(failed)}/{len(records)} runs.")


def main():
    parser = argparse.ArgumentParser(description="Evaluate the agent against known answers")
    parser.add_argument("--repeat", type=int, default=1, help="run each case this many times")
    args = parser.parse_args()

    agent.check_ollama()
    cases = json.loads(CASES_FILE.read_text())
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    records = []

    for case in cases:
        for run in range(1, args.repeat + 1):
            start = time.time()
            actual = run_case(case, run_id)
            problems = compare(case["expected"], actual)
            seconds = round(time.time() - start)
            status = "PASS" if not problems else "FAIL"
            print(f"  {case['case']:<26} run {run}: {status}  ({actual['outcome']}, {actual['steps']} steps, {seconds}s)")
            records.append({"case": case["case"], "run": run, "passed": not problems,
                            "problems": problems, "seconds": seconds, "actual": actual})

    print_report(cases, records)

    RUNS_DIR.mkdir(exist_ok=True)
    results_file = RUNS_DIR / f"eval_{run_id}.json"
    results_file.write_text(json.dumps(records, indent=2))
    print(f"Full traces and messages saved to {results_file.relative_to(ROOT)}")
    sys.exit(0 if all(r["passed"] for r in records) else 1)


if __name__ == "__main__":
    main()
