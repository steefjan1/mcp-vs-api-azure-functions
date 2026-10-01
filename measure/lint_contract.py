#!/usr/bin/env python3
"""Lints the MCP tool contract the way code gets linted.

The series argument, made enforceable: tool descriptions are the interface,
so wording problems should fail the build like type errors do. Four rules,
each one earned by a measured post:

  provenance     every identifier parameter says where its value comes from
                 (the sentence a schema cannot express; selection depends on it)
  when-to-call   every tool description contains a usage cue, not just a
                 what-it-does sentence
  token budget   the serialized tools array stays under budget, counted with
                 the same cl100k tokenizer as the discovery post
  drift          the C# attribute descriptions and the APIM Bicep copies of
                 the same tools are identical, because two copies of a
                 contract always fork

Aliases ("users may also say ...") are reported as a warning, not an error:
proven valuable for retrieval recall, but advisory at three tools.

Zero dependencies beyond the bundled tokenizer. Run: python lint_contract.py
Exit code 1 on any error, for CI.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
CSHARP = REPO / "src/RestaurantBackend/Mcp/RestaurantMcpTools.cs"
BICEP = REPO / "infra/apim/main.bicep"

TOKEN_BUDGET = 350  # cl100k tokens for the full tools array (real server: ~277)

TRIGGER_RE = re.compile(r'McpToolTrigger\("([^"]+)",\s*"([^"]+)"\)')
PROPERTY_RE = re.compile(r'McpToolProperty\("([^"]+)",\s*"([^"]+)",\s*isRequired:\s*(true|false)\)')
BICEP_TOOL_RE = re.compile(
    r"name:\s*'(\w+)'\s*\n\s*properties:\s*\{\s*\n\s*displayName:[^\n]*\n\s*description:\s*'([^']+)'")

WHEN_CUES = ("call", "use this", "use it", "when ")
PROVENANCE_CUES = ("as returned by", "comes from", "from search_", "from get_")
ALIAS_CUES = ("also say", "also call it", "aliases:")

def parse_csharp(text):
    """Returns [(tool_name, description, [(param, desc, required)])] in order."""
    tools = []
    pos = 0
    triggers = list(TRIGGER_RE.finditer(text))
    for i, trig in enumerate(triggers):
        end = triggers[i + 1].start() if i + 1 < len(triggers) else len(text)
        params = [(m.group(1), m.group(2), m.group(3) == "true")
                  for m in PROPERTY_RE.finditer(text, trig.end(), end)]
        tools.append((trig.group(1), trig.group(2), params))
    return tools

def is_identifier(param_name, param_desc):
    return (param_name.lower().endswith(("id", "name"))
            or "exact" in param_desc.lower())

def main():
    errors, warnings = [], []
    cs = CSHARP.read_text()
    tools = parse_csharp(cs)
    if not tools:
        sys.exit(f"lint_contract: no McpToolTrigger attributes found in {CSHARP}")

    for name, desc, params in tools:
        low = desc.lower()
        if not any(cue in low for cue in WHEN_CUES):
            errors.append(f"when-to-call  {name}: description says what it does "
                          f"but not when to call it")
        if not any(cue in low for cue in ALIAS_CUES):
            warnings.append(f"aliases       {name}: no alias sentence; paraphrased "
                            f"requests may miss it in retrieval")
        for pname, pdesc, _req in params:
            if is_identifier(pname, pdesc) and not any(
                    cue in pdesc.lower() for cue in PROVENANCE_CUES):
                errors.append(f"provenance    {name}.{pname}: identifier parameter "
                              f"without a where-it-comes-from sentence")

    # token budget, counted exactly as the discovery post counts
    sys.path.insert(0, str(HERE))
    from token_cost import make_counter
    import json
    count = make_counter()
    array = [{"name": n, "description": d,
              "inputSchema": {"type": "object",
                              "properties": {p: {"type": "string", "description": pd}
                                             for p, pd, _ in params},
                              "required": [p for p, _, r in params if r]}}
             for n, d, params in tools]
    total = count(json.dumps({"tools": array}, separators=(",", ":")))
    if total > TOKEN_BUDGET:
        errors.append(f"token-budget  tools array is {total} cl100k tokens, "
                      f"budget is {TOKEN_BUDGET}")

    # drift against the APIM-generated copies of the same tools
    bicep_tools = dict(BICEP_TOOL_RE.findall(BICEP.read_text()))
    for name, desc, _params in tools:
        if name in bicep_tools and bicep_tools[name] != desc:
            errors.append(f"drift         {name}: C# and infra/apim/main.bicep "
                          f"describe the same tool differently")

    print(f"lint_contract: {len(tools)} tools, {total} tokens "
          f"(budget {TOKEN_BUDGET})\n")
    for e in errors:
        print(f"  error    {e}")
    for w in warnings:
        print(f"  warning  {w}")
    if not errors and not warnings:
        print("  clean")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)

if __name__ == "__main__":
    main()
