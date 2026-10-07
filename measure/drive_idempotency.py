#!/usr/bin/env python3
"""Double-fires place_order at the MCP door to prove idempotency end to end.

The scenario is the one agents actually produce: a call times out or returns
ambiguously, the agent retries, and without idempotency the kitchen now holds
two orders. This driver places an order with a clientOrderId, retries it with
the same id, and checks the two confirmations carry the SAME orderId. Then it
reuses the id for a different order and expects the order_conflict recovery
message. A control pair without any clientOrderId demonstrates the failure
mode: two calls, two different orderIds, two orders.

Configure (same as drive_confusion.py):

  $env:MCP_SERVER_URL = "https://<app>.azurewebsites.net/runtime/webhooks/mcp"
  $env:AZURE_OPENAI_TOKEN = az account get-access-token --resource <PRM scope> --query accessToken -o tsv

Run:  python drive_idempotency.py
"""
import json
import os
import sys
import time
import uuid

from drive_confusion import post, parse_result

def call(url, token, session, i, arguments):
    _, body = post(url, token, {
        "jsonrpc": "2.0", "id": i, "method": "tools/call",
        "params": {"name": "place_order", "arguments": arguments}}, session)
    result = parse_result(body)
    content = result["result"].get("content", []) if result and "result" in result else []
    text = content[0].get("text", "") if content else ""
    if text.lstrip().startswith("{"):
        return json.loads(text), None
    return None, text  # recovery prose

def main():
    url = os.environ.get("MCP_SERVER_URL", "")
    token = os.environ.get("AZURE_OPENAI_TOKEN", "")
    if not (url and token):
        sys.exit("Set MCP_SERVER_URL and AZURE_OPENAI_TOKEN (see module docstring).")

    session, body = post(url, token, {
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "idempotency-driver", "version": "1.0"}}})
    init = parse_result(body)
    if not init or "result" not in init:
        sys.exit(f"initialize failed: {body[:300]}")
    print(f"connected (session {session or 'stateless'})\n")
    post(url, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)

    failures = 0
    order = {"restaurantId": "r1", "itemName": "Margherita", "quantity": 2}
    key = f"order-{uuid.uuid4().hex[:8]}"

    # 1. Place, then retry with the same clientOrderId.
    first, _ = call(url, token, session, 1, {**order, "clientOrderId": key})
    time.sleep(0.5)
    second, _ = call(url, token, session, 2, {**order, "clientOrderId": key})
    same = first and second and first["orderId"] == second["orderId"]
    failures += not same
    print(f"1. retry with same clientOrderId  {'PASS' if same else 'FAIL'}: "
          f"orderId {first and first['orderId']} then {second and second['orderId']} "
          f"({'one order exists' if same else 'DUPLICATE ORDER'})")

    # 2. Reuse the key for a different order: must be refused, not placed.
    conflict, prose = call(url, token, session, 3,
                           {**order, "quantity": 5, "clientOrderId": key})
    refused = conflict is None and prose and "clientOrderId" in prose
    failures += not refused
    print(f"2. same key, different request    {'PASS' if refused else 'FAIL'}: "
          f"{prose[:80] if prose else conflict}")

    # 3. Control: the same retry without a key duplicates the order.
    a, _ = call(url, token, session, 4, order)
    time.sleep(0.5)
    b, _ = call(url, token, session, 5, order)
    duplicated = a and b and a["orderId"] != b["orderId"]
    failures += not duplicated
    print(f"3. retry without clientOrderId    {'PASS' if duplicated else 'FAIL'}: "
          f"orderId {a and a['orderId']} then {b and b['orderId']} "
          f"({'two orders exist, as feared' if duplicated else 'unexpectedly deduplicated'})")

    print(f"\n{'all checks passed' if failures == 0 else f'{failures} check(s) FAILED'}")
    print("The replay from check 1 is an 'Order replayed' trace in Application "
          "Insights; the refusal from check 2 is an order_conflict sentinel.")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
