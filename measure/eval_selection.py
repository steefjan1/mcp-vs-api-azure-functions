#!/usr/bin/env python3
"""Stage-two eval: selection accuracy within the shortlist, with a live model.

Companion to eval_recall.py (stage one). Stage one measured whether the
correct tool reaches the shortlist; this measures whether the model chooses
it from the shortlist and fills the arguments correctly. To keep the stages
separated, every shortlist here is forced to contain the correct tool: the
correct tool plus the top BM25 distractors, deterministically shuffled. A
recall miss can therefore never masquerade as a selection miss.

Scoring per task:
  - selection: the model picked the expected tool
  - arguments: the task's reference value (e.g. INV-2005) appears among the
    argument values of a correct selection (a deliberately lenient proxy;
    exact schema validation would punish harmless formatting choices)

Every result row is tagged with the description-set hash and the model
deployment, per the telemetry design from the comment threads.

Runs against Azure OpenAI (chat completions), stdlib only. Configure:

  $env:AZURE_OPENAI_ENDPOINT   = "https://<resource>.openai.azure.com"
  $env:AZURE_OPENAI_API_KEY    = "<key>"
  $env:AZURE_OPENAI_DEPLOYMENT = "<chat deployment name>"
  $env:AZURE_OPENAI_API_VERSION = "2024-10-21"   # optional

For a resource with disableLocalAuth (Entra-only), set a bearer token
instead of the key (valid for about an hour; needs the Cognitive Services
OpenAI User role on the resource):

  $env:AZURE_OPENAI_TOKEN = az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv

Run:  python eval_selection.py            (full run, 4 conditions x sampled tasks)
      python eval_selection.py --dry-run  (print one prompt, call nothing)
      python eval_selection.py --sample 20 --conditions realistic
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from token_cost import synth_tools  # noqa: E402
from eval_recall import BM25, make_tasks, tool_document, tokenize, with_aliases  # noqa: E402

SHORTLIST_K = 5
SEED = 42

SYSTEM_PROMPT = (
    "You are a tool-calling agent. Choose exactly one tool from the provided "
    "list that best fulfills the user's request, and provide its arguments. "
    "Respond with ONLY a JSON object, no markdown, of the shape: "
    '{"tool": "<tool name>", "arguments": {"<param>": "<value>"}}'
)

def desc_hash(tools):
    return hashlib.sha256(
        json.dumps(tools, sort_keys=True).encode()).hexdigest()[:12]

def forced_shortlist(tools, bm25, index, task, rng):
    """Correct tool + top BM25 distractors, shuffled deterministically."""
    correct = index[task["tool"]]
    ranked = bm25.top(tokenize(task["utterance"]), SHORTLIST_K + 1)
    distractors = [i for i in ranked if i != correct][:SHORTLIST_K - 1]
    shortlist = [correct] + distractors
    rng.shuffle(shortlist)
    return [tools[i] for i in shortlist]

def build_prompt(shortlist, utterance):
    return (f"Available tools:\n{json.dumps({'tools': shortlist}, indent=2)}\n\n"
            f"User request: {utterance}")

def call_model(cfg, user_prompt, retries=4):
    url = (f"{cfg['endpoint']}/openai/deployments/{cfg['deployment']}"
           f"/chat/completions?api-version={cfg['api_version']}")
    # gpt-5 family: max_completion_tokens (not max_tokens), temperature fixed
    # at its default, so neither temperature nor max_tokens is sent.
    body = json.dumps({
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": user_prompt}],
        "max_completion_tokens": 2000,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    else:
        headers["api-key"] = cfg["key"]
    req = urllib.request.Request(url, data=body, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
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

def parse_choice(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text.strip())
        return obj.get("tool"), obj.get("arguments") or {}
    except json.JSONDecodeError:
        return None, {}

def ref_of(task):
    # eval_recall utterances end with the reference value
    return task["utterance"].rstrip(".?").split()[-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=60,
                    help="tasks per condition (even; half vocabulary, half paraphrase)")
    ap.add_argument("--conditions", nargs="*", default=[
        "terse", "realistic", "verbose", "realistic+aliases"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    all_tasks = make_tasks()
    rng = random.Random(SEED)
    by_kind = {"vocabulary": [t for t in all_tasks if t["kind"] == "vocabulary"],
               "paraphrase": [t for t in all_tasks if t["kind"] == "paraphrase"]}
    half = args.sample // 2
    tasks = rng.sample(by_kind["vocabulary"], half) + rng.sample(by_kind["paraphrase"], half)

    pools = {}
    for c in args.conditions:
        pools[c] = (with_aliases(synth_tools(100, "realistic"))
                    if c == "realistic+aliases" else synth_tools(100, c))

    if args.dry_run:
        c = args.conditions[0]
        tools = pools[c]
        bm25 = BM25([tool_document(t) for t in tools])
        index = {t["name"]: i for i, t in enumerate(tools)}
        task = tasks[0]
        sl = forced_shortlist(tools, bm25, index, task, random.Random(SEED))
        print(f"--- condition: {c}, expected tool: {task['tool']}, "
              f"ref: {ref_of(task)} ---")
        print(build_prompt(sl, task["utterance"]))
        return

    cfg = {
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
        "key": os.environ.get("AZURE_OPENAI_API_KEY", ""),
        "token": os.environ.get("AZURE_OPENAI_TOKEN", ""),
        "deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    }
    if not (cfg["endpoint"] and cfg["deployment"] and (cfg["key"] or cfg["token"])):
        sys.exit("Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and either "
                 "AZURE_OPENAI_API_KEY or AZURE_OPENAI_TOKEN (see module docstring).")

    results = {"model_deployment": cfg["deployment"], "shortlist_k": SHORTLIST_K,
               "tasks_per_condition": len(tasks), "seed": SEED,
               "conditions": {}, "rows": []}
    for c in args.conditions:
        tools = pools[c]
        bm25 = BM25([tool_document(t) for t in tools])
        index = {t["name"]: i for i, t in enumerate(tools)}
        dh = desc_hash(tools)
        stats = {k: {"n": 0, "selected": 0, "args_ok": 0}
                 for k in ("vocabulary", "paraphrase")}
        srng = random.Random(SEED)
        for n, task in enumerate(tasks, 1):
            sl = forced_shortlist(tools, bm25, index, task, srng)
            raw = call_model(cfg, build_prompt(sl, task["utterance"]))
            tool, arguments = parse_choice(raw)
            selected = tool == task["tool"]
            ref = ref_of(task)
            args_ok = selected and any(
                ref.lower() in str(v).lower() for v in arguments.values())
            s = stats[task["kind"]]
            s["n"] += 1
            s["selected"] += selected
            s["args_ok"] += args_ok
            results["rows"].append({
                "condition": c, "desc_hash": dh, "kind": task["kind"],
                "expected": task["tool"], "chosen": tool,
                "selected": selected, "args_ok": args_ok})
            print(f"\r{c}: {n}/{len(tasks)}", end="", flush=True)
        print()
        results["conditions"][c] = {"desc_hash": dh, **{
            k: {"n": v["n"],
                "selection_pct": round(100 * v["selected"] / v["n"], 1),
                "args_pct": round(100 * v["args_ok"] / v["n"], 1)}
            for k, v in stats.items()}}

    (HERE / "eval_selection_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nselection within a forced shortlist of {SHORTLIST_K}, "
          f"model {cfg['deployment']}, {len(tasks)} tasks per condition\n")
    print(f"{'condition':>18} {'kind':>11} {'selected':>9} {'args ok':>8}")
    for c, r in results["conditions"].items():
        for kind in ("vocabulary", "paraphrase"):
            print(f"{c:>18} {kind:>11} {r[kind]['selection_pct']:>8}% "
                  f"{r[kind]['args_pct']:>7}%")

if __name__ == "__main__":
    main()
