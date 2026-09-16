#!/usr/bin/env python3
"""Measures the standing context cost of MCP tool definitions.

Companion experiment for the post "What the Agent Pays for Discovery".

Counts cl100k_base tokens for a tools array at increasing tool counts and
three description verbosity levels, anchored by the real three-tool server
from the mcp-vs-api sample. Uses tiktoken when installed; otherwise falls
back to the bundled pure-Python counter (bpe.py) plus the public ranks file:

  curl -L -o cl100k_base.tiktoken \
    https://raw.githubusercontent.com/niieani/gpt-tokenizer/main/data/cl100k_base.tiktoken

Run: python token_cost.py
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent

def make_counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        import sys
        sys.path.insert(0, str(HERE))
        import bpe
        ranks = bpe.load_ranks(HERE / "cl100k_base.tiktoken")
        return lambda s: bpe.count_tokens(s, ranks)

count = make_counter()

# ---------------------------------------------------------------------------
# The real anchor: the three tools of the mcp-vs-api sample, as served.
# ---------------------------------------------------------------------------

REAL_TOOLS = [
    {
        "name": "search_restaurants",
        "description": "Searches the restaurant directory. Both filters are optional; call it without arguments to list every restaurant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cuisine": {"type": "string", "description": "Cuisine to filter by, for example 'Italian' or 'Japanese'."},
                "city": {"type": "string", "description": "City to filter by, for example 'Nijmegen' or 'Utrecht'."},
            },
            "required": [],
        },
    },
    {
        "name": "get_menu",
        "description": "Gets the menu for one restaurant, including item names, descriptions, and prices in euros.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurantId": {"type": "string", "description": "The restaurant id, as returned by search_restaurants (for example 'r1')."},
            },
            "required": ["restaurantId"],
        },
    },
    {
        "name": "place_order",
        "description": "Places an order for one menu item at a restaurant and returns a confirmation with the total price.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "restaurantId": {"type": "string", "description": "The restaurant id, as returned by search_restaurants."},
                "itemName": {"type": "string", "description": "The exact menu item name, as returned by get_menu."},
                "quantity": {"type": "integer", "description": "How many to order, between 1 and 20."},
            },
            "required": ["restaurantId", "itemName", "quantity"],
        },
    },
]

# ---------------------------------------------------------------------------
# Synthetic enterprise tool generator (deterministic).
# ---------------------------------------------------------------------------

VERBS = ["search", "get", "create", "update", "cancel", "approve", "list", "archive", "assign", "export"]
NOUNS = ["invoice", "order", "customer", "shipment", "ticket", "contract", "claim", "policy", "payment", "product"]
PARAMS = ["id", "status", "dateFrom", "dateTo", "ownerId", "amount", "category", "reference"]

def synth_tools(n, verbosity, seed=42):
    rng = random.Random(seed)
    tools = []
    for i in range(n):
        verb = VERBS[i % len(VERBS)]
        noun = NOUNS[(i // len(VERBS)) % len(NOUNS)]
        name = f"{verb}_{noun}" if i < len(VERBS) * len(NOUNS) else f"{verb}_{noun}_{i}"
        k = rng.randint(2, 4)
        params = rng.sample(PARAMS, k)
        if verbosity == "terse":
            desc = f"{verb.capitalize()}s a {noun}."
            pdesc = lambda p: f"The {p}."
        elif verbosity == "realistic":
            desc = (f"{verb.capitalize()}s a {noun} in the {noun} system. "
                    f"Use this when the user asks about {noun}s; identifiers come from the matching search tool.")
            pdesc = lambda p: f"The {p} of the {noun}, as returned by search_{noun}."
        else:  # verbose
            desc = (f"{verb.capitalize()}s a {noun} in the {noun} management system. Use this tool whenever the user "
                    f"asks to {verb} a {noun} or refers to an existing {noun} by name or number. Identifiers come from "
                    f"the matching search tool and must not be guessed. Returns the full {noun} record including status, "
                    f"owner, timestamps, and audit fields. If the {noun} does not exist, the tool returns an explanatory "
                    f"message rather than an error, so read the response before retrying.")
            pdesc = lambda p: (f"The {p} of the {noun}. Obtain this value from a previous search_{noun} call; "
                               f"do not invent it. Case sensitive.")
        tools.append({
            "name": name,
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {p: {"type": "string", "description": pdesc(p)} for p in params},
                "required": params[:1],
            },
        })
    return tools

def tokens_of(tools):
    return count(json.dumps({"tools": tools}, separators=(",", ":")))

# ---------------------------------------------------------------------------
# The experiment.
# ---------------------------------------------------------------------------

def main():
    results = {"anchor_real_3_tools": tokens_of(REAL_TOOLS)}
    rows = []
    for n in (3, 10, 30, 100):
        for verbosity in ("terse", "realistic", "verbose"):
            t = tokens_of(synth_tools(n, verbosity))
            rows.append({"tools": n, "verbosity": verbosity, "tokens": t,
                         "per_20_call_task": t * 20})
    results["grid"] = rows
    curated = tokens_of(synth_tools(100, "realistic")[:5])
    results["curated_5_of_100_realistic"] = curated
    full100 = next(r["tokens"] for r in rows if r["tools"] == 100 and r["verbosity"] == "realistic")
    results["curated_saving_pct"] = round(100 * (1 - curated / full100), 1)

    (HERE / "results.json").write_text(json.dumps(results, indent=2))
    print(f"real 3-tool restaurant server: {results['anchor_real_3_tools']} tokens\n")
    print(f"{'tools':>6} {'terse':>8} {'realistic':>10} {'verbose':>9}")
    for n in (3, 10, 30, 100):
        vals = {r['verbosity']: r['tokens'] for r in rows if r['tools'] == n}
        print(f"{n:>6} {vals['terse']:>8} {vals['realistic']:>10} {vals['verbose']:>9}")
    print(f"\ncurated manifest, 5 of 100 (realistic): {curated} tokens "
          f"({results['curated_saving_pct']}% saved vs full 100)")

if __name__ == "__main__":
    main()
