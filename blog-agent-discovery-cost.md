# What the Agent Pays for Discovery

A reader of [MCP vs API Is the Wrong Question](https://dev.to/steefjan_wiggers_34a415b/mcp-vs-api-is-the-wrong-question-392f) asked the question I could not answer at the time: did you measure the token cost of the live MCP discovery round trip against handing the model a curated tool manifest up front, and where does the break-even sit? I answered from first principles then. This post answers with numbers, from a small measurement harness that now lives in the [companion repo](https://github.com/steefjan1/mcp-vs-api-azure-functions) under `measure/`.

## Where the tokens actually go

First, the framing correction that makes the question answerable. The live discovery round trip is nearly free: an MCP client calls tools/list once per session, not per turn, and the payload that comes back is essentially the same manifest you would curate by hand. The cost that matters is different and larger: whatever tools the client ends up with, their definitions are injected into the model's context on every single call. A curated manifest pays that too. So "discovery versus manifest" is not the axis. The axis is how many tool definitions sit in context, how wordy they are, and how many model calls the task takes.

That is measurable without an LLM in the loop, exactly, with a tokenizer.

## The method

The harness serializes a tools array the way it reaches a model (JSON: name, description, input schema with per-parameter descriptions) and counts cl100k tokens. The anchor is real: the three tools of the restaurant sample, exactly as the Functions MCP extension serves them. Around that anchor it generates synthetic enterprise tools (search_invoice, approve_claim, and so on, two to four parameters each) at three description levels: terse (a sentence fragment), realistic (purpose plus parameter guidance, modeled on the sample's actual descriptions), and verbose (usage guidance, examples, and edge-case notes on everything). One honest caveat: harnesses reformat definitions slightly differently, so treat the absolute numbers as close and the relative differences as solid.

## The numbers

The real three-tool restaurant server costs 277 tokens per model call. That is the whole standing bill, and it is why break-even at this scale is immediate: there is nothing meaningful to save.

Scale changes the picture:

| Tools | Terse | Realistic | Verbose |
|---|---|---|---|
| 3 | 209 | 362 | 668 |
| 10 | 596 | 1,040 | 1,972 |
| 30 | 1,856 | 3,233 | 6,089 |
| 100 | 6,370 | 11,132 | 20,814 |

Two things jump out. The growth is linear in tool count, roughly 64 tokens per tool terse, 111 realistic, 208 verbose; there is no cliff, just a slope. And description style is its own multiplier: at every size, verbose costs about 1.9 times realistic and 3.3 times terse.

The slope compounds per task, not per session. A hundred realistic tools cost 11,132 tokens on every model call, so a 20-call agent task pays roughly 223,000 tokens for definitions alone, before a word of conversation or a byte of tool output. The curated comparison the commenter asked about: five relevant tools picked out of that hundred cost 542 tokens per call, a 95 percent saving.

## So where is the break-even?

For a server like the sample, there is none to find; 277 tokens is noise. My reading of the curve: below roughly ten tools, do nothing. Around thirty realistic tools you are paying 3,200 tokens per call and about 65,000 per task, which is real money at fleet scale but rarely worth architectural surgery. At a hundred tools you must do something, and the interesting part is that a curated manifest is only one of four options, and the crudest one.

A curated manifest is static tool selection: you save 95 percent of the context by deciding at design time which five tools matter, which is precisely the design-time knowledge MCP exists to avoid assuming. The alternatives keep discovery and cut the bill differently. Split the server by domain, so an agent connects to the invoice server or the shipment server rather than the everything server; this is the maître d' post's fleet argument wearing a cost hat. Use a client that defers tool loading and searches definitions on demand, which more agent runtimes now do. Or design coarser, intent-sized tools so a hundred resource-level operations become fifteen task-level ones, which a commenter on the first post predicted and the numbers now justify.

## The tension with post one

The first post argued that tool descriptions are load-bearing: vague text makes vague agents. This post seems to argue that words cost money. Both are true, and the numbers say where the balance sits. Realistic descriptions, around 25 words of purpose and parameter guidance per tool, cost 111 tokens each; that is the price of an agent that picks the right tool and recovers from errors, and it is worth paying. The verbose tier doubles the bill mostly with prose the model would infer anyway. So the budget rule I take away: spend description tokens on disambiguation between tools and on where identifiers come from, never on ceremony.

## What this does not measure

Selection accuracy. The other half of the commenter's question is whether the model picks the right tool less often at a hundred tools than at ten, and that needs a live model, many runs, and scripted tasks with known correct tool sequences. The harness is structured so that eval slots in next; that experiment, together with the description validation ideas from the comment thread, is its own post. What is measured here is the bill; whether the agent's judgment also degrades with the menu size is the follow-up.

## The takeaway

Discovery is not what costs you; standing context is. The bill is linear in tool count, multiplied by description style, and paid on every model call. Below ten tools, ignore it. Above that, the fix is not abandoning discovery for a hand-curated list; it is scoping servers, deferring definitions, and sizing tools to intents, with descriptions that earn their tokens.

The harness, the data, and the chart are in the repo under [`measure/`](https://github.com/steefjan1/mcp-vs-api-azure-functions); run `python token_cost.py` and argue with the numbers directly.
