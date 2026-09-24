#!/usr/bin/env python3
"""Drives mixed traffic at the MCP door so the confusion telemetry lights up.

Speaks streamable-HTTP MCP directly: initialize, initialized, then a batch of
tools/call requests, most of them deliberately wrong in the ways an agent gets
things wrong (invented restaurant ids, misremembered item names, impossible
quantities, filters that match nothing), plus some valid calls as control.
Each wrong call makes the server return a recovery message and emit one
"Contract confusion" log line with sentinel, descHash, and schemaVersion.

Configure (Entra bearer token; the server has built-in MCP auth on):

  $env:MCP_SERVER_URL = "https://<app>.azurewebsites.net/runtime/webhooks/mcp"
  $env:AZURE_OPENAI_TOKEN = az account get-access-token --resource <the scope from the server's PRM, e.g. https://<app>.azurewebsites.net/runtime/webhooks/mcp> --query accessToken -o tsv

Run:  python drive_confusion.py            (default 30 calls)
      python drive_confusion.py --calls 100
"""
import argparse
import itertools
import json
import os
import sys
import time
import urllib.error
import urllib.request

def post(url, token, payload, session=None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            body = resp.read().decode(errors="replace")
        return sid, body
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode(errors="replace")[:400]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None

def parse_result(body):
    """Handle both plain JSON and SSE-framed responses."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "result" in obj or "error" in obj:
                return obj
    return None

CALLS = [
    # (tool, arguments, why)
    ("get_menu", {"restaurantId": "r99"}, "invented id -> menu_unknown_restaurant"),
    ("get_menu", {"restaurantId": "trattoria-valkhof"}, "name instead of id -> menu_unknown_restaurant"),
    ("place_order", {"restaurantId": "r1", "itemName": "Pizza", "quantity": 2}, "inexact item -> order_rejected"),
    ("place_order", {"restaurantId": "r1", "itemName": "Margherita", "quantity": 50}, "quantity cap -> order_rejected"),
    ("search_restaurants", {"cuisine": "Klingon"}, "no match -> search_no_match"),
    ("search_restaurants", {"city": "Rotterdam"}, "no match -> search_no_match"),
    ("search_restaurants", {"cuisine": "Italian"}, "valid control"),
    ("get_menu", {"restaurantId": "r1"}, "valid control"),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=30)
    args = ap.parse_args()

    url = os.environ.get("MCP_SERVER_URL", "")
    token = os.environ.get("AZURE_OPENAI_TOKEN", "")
    if not (url and token):
        sys.exit("Set MCP_SERVER_URL and AZURE_OPENAI_TOKEN (see module docstring).")

    session, body = post(url, token, {
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "confusion-driver", "version": "1.0"}}})
    init = parse_result(body)
    if not init or "result" not in init:
        sys.exit(f"initialize failed: {body[:300]}")
    server = init["result"].get("serverInfo", {})
    print(f"connected to {server.get('name')} {server.get('version')} "
          f"(session {session or 'stateless'})")
    post(url, token, {"jsonrpc": "2.0", "method": "notifications/initialized"},
         session)

    rotation = itertools.cycle(CALLS)
    ok = confused = 0
    for i in range(1, args.calls + 1):
        tool, arguments, why = next(rotation)
        _, body = post(url, token, {
            "jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments}}, session)
        result = parse_result(body)
        text = ""
        if result and "result" in result:
            content = result["result"].get("content", [])
            text = content[0].get("text", "") if content else ""
        recovered = text and not text.lstrip().startswith(("[", "{"))
        confused += recovered
        ok += not recovered
        print(f"{i:>3} {tool:<19} {'confusion' if recovered else 'ok':<9} {why}")
        time.sleep(0.3)

    print(f"\n{args.calls} calls: {confused} recovery messages, {ok} clean results.")
    print("Give Application Insights a few minutes, then run the KQL from the post.")

if __name__ == "__main__":
    main()
