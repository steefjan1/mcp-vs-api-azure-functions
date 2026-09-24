#!/usr/bin/env python3
"""Stage-one eval: recall of the correct tool into a retrieval shortlist.

Companion experiment for the tool-selection eval post. Deferred tool loading
means the client retrieves candidate tools by matching the user's request
against tool names and descriptions. Stage one of the two-stage eval asks:
did the correct tool make the shortlist at all? A recall miss fails silently,
so it gets its own number, measured here without any LLM in the loop.

Method: BM25 retrieval over the serialized tool definitions (name,
description, parameter descriptions), at three description verbosity levels,
against two kinds of task utterances:
  - vocabulary: the user echoes the tool's own domain words
    ("approve the claim CLM-2041")
  - paraphrase: the user says the same thing in synonyms
    ("sign off on that damage report, number CLM-2041")

Run: python eval_recall.py   (writes eval_recall_results.json)
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

from token_cost import synth_tools, VERBS, NOUNS

HERE = Path(__file__).parent
K = 5          # shortlist size
N_TOOLS = 100  # tool pool size
SEED_TASKS = 7

VERB_SYNONYMS = {
    "search": "look for", "get": "pull up", "create": "set up",
    "update": "change", "cancel": "call off", "approve": "sign off on",
    "list": "show me all", "archive": "put away", "assign": "hand over",
    "export": "download",
}
NOUN_SYNONYMS = {
    "invoice": "bill", "order": "purchase", "customer": "client",
    "shipment": "delivery", "ticket": "support case", "contract": "agreement",
    "claim": "damage report", "policy": "coverage plan", "payment": "transaction",
    "product": "item",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")

def tokenize(text):
    return TOKEN_RE.findall(text.lower())

def tool_document(tool):
    parts = [tool["name"].replace("_", " "), tool["description"]]
    for p, spec in tool["inputSchema"]["properties"].items():
        parts.append(p)
        parts.append(spec.get("description", ""))
    return tokenize(" ".join(parts))

class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.avgdl = sum(len(d) for d in docs) / len(docs)
        self.tfs = [Counter(d) for d in docs]
        df = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def score(self, query, i):
        tf, dl = self.tfs[i], len(self.docs[i])
        s = 0.0
        for t in query:
            if t not in tf:
                continue
            f = tf[t]
            s += self.idf.get(t, 0) * f * (self.k1 + 1) / (
                f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def top(self, query, k):
        scored = sorted(range(len(self.docs)),
                        key=lambda i: self.score(query, i), reverse=True)
        return scored[:k]

def make_tasks():
    """One vocabulary and one paraphrase utterance per (verb, noun) pair."""
    tasks = []
    for vi, verb in enumerate(VERBS):
        for ni, noun in enumerate(NOUNS):
            idx = ni * len(VERBS) + vi  # matches synth_tools naming order
            if idx >= N_TOOLS:
                continue
            name = f"{verb}_{noun}"
            ref = f"{noun[:3].upper()}-{2000 + idx}"
            tasks.append({"tool": name, "kind": "vocabulary",
                          "utterance": f"Please {verb} the {noun} {ref}."})
            tasks.append({"tool": name, "kind": "paraphrase",
                          "utterance": f"Can you {VERB_SYNONYMS[verb]} "
                                       f"that {NOUN_SYNONYMS[noun]}, number {ref}?"})
    return tasks

def with_aliases(tools):
    """Realistic descriptions plus one alias sentence naming the synonyms."""
    out = []
    for t in tools:
        verb, noun = t["name"].split("_")[0], t["name"].split("_")[1]
        t = dict(t)
        t["description"] = (t["description"] + f" Users may also say "
                            f"'{VERB_SYNONYMS[verb]}' or '{NOUN_SYNONYMS[noun]}'.")
        out.append(t)
    return out

K_SWEEP = (3, 5, 10)

def run():
    tasks = make_tasks()
    results = {"shortlist_k": K, "k_sweep": list(K_SWEEP), "tool_pool": N_TOOLS,
               "tasks": len(tasks), "recall": {}, "recall_by_k": {}}
    conditions = {v: synth_tools(N_TOOLS, v) for v in ("terse", "realistic", "verbose")}
    conditions["realistic+aliases"] = with_aliases(synth_tools(N_TOOLS, "realistic"))
    for verbosity, tools in conditions.items():
        index = {t["name"]: i for i, t in enumerate(tools)}
        bm25 = BM25([tool_document(t) for t in tools])
        hits = {k: {"vocabulary": 0, "paraphrase": 0} for k in K_SWEEP}
        totals = {"vocabulary": 0, "paraphrase": 0}
        for task in tasks:
            totals[task["kind"]] += 1
            shortlist = bm25.top(tokenize(task["utterance"]), max(K_SWEEP))
            for k in K_SWEEP:
                if index[task["tool"]] in shortlist[:k]:
                    hits[k][task["kind"]] += 1
        results["recall_by_k"][verbosity] = {
            k: {kind: round(100 * hits[k][kind] / totals[kind], 1) for kind in totals}
            for k in K_SWEEP}
        results["recall"][verbosity] = results["recall_by_k"][verbosity][K]
    # token price of a shortlist of k realistic tools, from the same counter
    from token_cost import tokens_of
    results["shortlist_token_price_realistic"] = {
        k: tokens_of(conditions["realistic"][:k]) for k in K_SWEEP}
    (HERE / "eval_recall_results.json").write_text(json.dumps(results, indent=2))
    print(f"recall of the correct tool into the shortlist, "
          f"{N_TOOLS} tools, {len(tasks)} tasks\n")
    for k in K_SWEEP:
        price = results["shortlist_token_price_realistic"][k]
        print(f"recall@{k}  (a {k}-tool realistic shortlist costs ~{price} tokens/call)")
        print(f"{'descriptions':>18} {'vocabulary':>11} {'paraphrase':>11}")
        for verbosity in conditions:
            r = results["recall_by_k"][verbosity][k]
            print(f"{verbosity:>18} {r['vocabulary']:>10}% {r['paraphrase']:>10}%")
        print()

if __name__ == "__main__":
    run()
