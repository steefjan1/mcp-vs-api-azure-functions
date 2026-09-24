#!/usr/bin/env python3
"""The embedding rematch: stage-one recall with a semantic retriever.

Reruns eval_recall.py's exact experiment (same 200 tasks, same four
description conditions, recall@k for k in 3/5/10) with one swap: BM25 is
replaced by cosine similarity over Azure OpenAI embeddings. The question it
answers: does semantic retrieval repeal the vocabulary gap, or soften it,
and does the 13-token alias line still pay?

Cost note: one run embeds ~600 short texts (4 x 100 tool documents plus
200 task utterances), a fraction of a cent on text-embedding-3-small.

Configure (key or Entra bearer token, same as eval_selection.py):

  $env:AZURE_OPENAI_ENDPOINT         = "https://<resource>.openai.azure.com"
  $env:AZURE_OPENAI_EMBED_DEPLOYMENT = "<embedding deployment name>"
  $env:AZURE_OPENAI_API_KEY          = "<key>"        # or:
  $env:AZURE_OPENAI_TOKEN = az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv

Run:  python eval_recall_embed.py
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from token_cost import synth_tools  # noqa: E402
from eval_recall import make_tasks, with_aliases  # noqa: E402

K_SWEEP = (3, 5, 10)
N_TOOLS = 100
BATCH = 100

def tool_text(tool):
    parts = [tool["name"].replace("_", " "), tool["description"]]
    for p, spec in tool["inputSchema"]["properties"].items():
        parts.append(f"{p}: {spec.get('description', '')}")
    return " ".join(parts)

def embed_batch(cfg, texts, retries=4):
    url = (f"{cfg['endpoint']}/openai/deployments/{cfg['deployment']}"
           f"/embeddings?api-version={cfg['api_version']}")
    body = json.dumps({"input": texts}).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    else:
        headers["api-key"] = cfg["key"]
    req = urllib.request.Request(url, data=body, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            return [d["embedding"] for d in
                    sorted(data["data"], key=lambda d: d["index"])]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            detail = ""
            try:
                detail = e.read().decode(errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} from the endpoint: {detail}") from None
    raise RuntimeError("unreachable")

def embed_all(cfg, texts):
    out = []
    for i in range(0, len(texts), BATCH):
        out.extend(embed_batch(cfg, texts[i:i + BATCH]))
        print(f"\rembedded {min(i + BATCH, len(texts))}/{len(texts)}",
              end="", flush=True)
    print()
    return out

def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)

def main():
    cfg = {
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
        "key": os.environ.get("AZURE_OPENAI_API_KEY", ""),
        "token": os.environ.get("AZURE_OPENAI_TOKEN", ""),
        "deployment": os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", ""),
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }
    if not (cfg["endpoint"] and cfg["deployment"] and (cfg["key"] or cfg["token"])):
        sys.exit("Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_EMBED_DEPLOYMENT, and "
                 "either AZURE_OPENAI_API_KEY or AZURE_OPENAI_TOKEN "
                 "(see module docstring).")

    tasks = make_tasks()
    print(f"embedding {len(tasks)} task utterances...")
    task_vecs = embed_all(cfg, [t["utterance"] for t in tasks])

    conditions = {v: synth_tools(N_TOOLS, v) for v in ("terse", "realistic", "verbose")}
    conditions["realistic+aliases"] = with_aliases(synth_tools(N_TOOLS, "realistic"))

    results = {"retriever": f"cosine over {cfg['deployment']}",
               "k_sweep": list(K_SWEEP), "tool_pool": N_TOOLS,
               "tasks": len(tasks), "recall_by_k": {}}
    for name, tools in conditions.items():
        print(f"embedding {N_TOOLS} tool documents ({name})...")
        tool_vecs = embed_all(cfg, [tool_text(t) for t in tools])
        index = {t["name"]: i for i, t in enumerate(tools)}
        hits = {k: {"vocabulary": 0, "paraphrase": 0} for k in K_SWEEP}
        totals = {"vocabulary": 0, "paraphrase": 0}
        for tvec, task in zip(task_vecs, tasks):
            totals[task["kind"]] += 1
            ranked = sorted(range(N_TOOLS),
                            key=lambda i: cosine(tvec, tool_vecs[i]),
                            reverse=True)
            correct = index[task["tool"]]
            for k in K_SWEEP:
                if correct in ranked[:k]:
                    hits[k][task["kind"]] += 1
        results["recall_by_k"][name] = {
            k: {kind: round(100 * hits[k][kind] / totals[kind], 1)
                for kind in totals} for k in K_SWEEP}

    (HERE / "eval_recall_embed_results.json").write_text(
        json.dumps(results, indent=2))
    print(f"\nembedding-retriever recall, {N_TOOLS} tools, {len(tasks)} tasks, "
          f"model {cfg['deployment']}\n")
    for k in K_SWEEP:
        print(f"recall@{k}")
        print(f"{'descriptions':>18} {'vocabulary':>11} {'paraphrase':>11}")
        for name in conditions:
            r = results["recall_by_k"][name][k]
            print(f"{name:>18} {r['vocabulary']:>10}% {r['paraphrase']:>10}%")
        print()

if __name__ == "__main__":
    main()
