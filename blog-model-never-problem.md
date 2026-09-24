# The Model Was Never the Problem

The shortlist post ended with a promise: stage two of the eval, selection within the shortlist, measured with a live model, scored so that a recall miss can never masquerade as a selection miss. This post pays that debt. The design came straight from the comment threads: same tool pools, same task pairs, shortlists from the same retriever, and every result row tagged with the description-set hash so the numbers stay attributable across changes. The runner is `measure/eval_selection.py` in the [companion repo](https://github.com/steefjan1/mcp-vs-api-azure-functions), stdlib Python against any Azure OpenAI deployment.

## The method

Stage one showed recall failing at 5 percent on paraphrased requests, so scoring stage two on retrieved shortlists would mostly measure retrieval again. Instead, every shortlist here is forced: the correct tool plus its four strongest BM25 distractors, deterministically shuffled. That construction has a pleasant side effect. Because the distractors are whatever retrieval scores highest for the request, they are the correct tool's same-noun siblings. When the expected tool is approve_claim, the shortlist also contains cancel_claim, update_claim, and search_claim. The model does not get to coast on topic matching; it has to read verb semantics.

The model is gpt-5.4-mini, deliberately the small and cheap one, at its default temperature, sixty tasks per condition, half vocabulary phrasing and half paraphrase, across the four description conditions from the recall post. Scored on two things: did the model pick the expected tool, and did the task's reference value (the INV-2005 in the request) land in the arguments of a correct pick. The argument check is deliberately lenient; exact schema validation would punish harmless formatting.

One anecdote from setup that belongs in this series: the eval refused to run with an API key, because the Azure AI resource had disableLocalAuth set. The harness that measures keyless MCP tooling had to authenticate with an Entra bearer token itself. The 401 post's argument, arriving in person.

## The numbers

Selection accuracy, forced shortlist of five, sixty tasks per condition:

| Descriptions | Selection, vocabulary | Selection, paraphrase |
|---|---|---|
| Terse | 97% | 97% |
| Realistic | 97% | 93% |
| Verbose | 90% | 93% |
| Realistic plus aliases | 97% | 97% |

Read that table as flat, and I mean that as a finding, not a shrug. At thirty tasks per cell, every difference in it is one or two tasks, and one run at default temperature is a sample, not a truth. The honest summary is a single sentence: selection accuracy is 90 to 97 percent everywhere. A small model picks the right tool from a five-tool shortlist about nineteen times in twenty, whether the descriptions are terse or verbose, whether the user echoed the tool's vocabulary or paraphrased it into synonyms, and with the tool's own siblings crowding the list. Argument filling lands slightly lower, 87 to 97 percent, under the lenient scoring.

Two null results hide in there, and both are useful. Description verbosity, which did nothing for recall, also does nothing for selection; terse held its own against descriptions three times its token price. And the paraphrase gap, which was catastrophic for recall, nearly vanishes at selection time: once the right tool is in front of it, the model bridges "sign off on the damage report" to approve_claim without difficulty. The vocabulary gap is fatal to retrieval and almost irrelevant to judgment.

## Multiply the stages

The two-stage arithmetic is the real headline. End to end, task success is roughly recall times selection. For a paraphrased request against one hundred realistic tools:

| Setup | Recall | Selection | End to end |
|---|---|---|---|
| Realistic descriptions | 5% | 93% | ~5% |
| Realistic plus aliases | 100% | 97% | ~97% |

![Two-lane pipeline showing 100 paraphrased requests flowing through retrieval and model selection: with realistic descriptions 5 percent survive the shortlist stage and about 5 percent end in the right tool call, with an added alias sentence 100 percent survive retrieval and about 97 percent end in the right tool call](images/mcp-two-stage-funnel.png)

The entire end-to-end difference lives in stage one. Report one blended number, as most tool-calling benchmarks do, and you would conclude the model picks tools badly, when the model almost never saw the right tool at all. Measured separately, the model turns out to be nearly blameless, and the 13-token alias sentence from the recall post is carrying the whole system.

## What this changes about the budget

The reflex when an agent picks wrong tools is to reach for a bigger model. At this shortlist size, that money is misspent, because selection was never the failing stage. The failing stage was vocabulary coverage in the descriptions, which is fixed with words that cost thirteen tokens per tool, not with a model that costs ten times more per call. There will be scales where that stops being true; a shortlist of twenty near-duplicates or genuinely ambiguous intents will stress judgment in a way five siblings do not, and that is a measurable follow-up. But the burden of proof has moved. Before spending on model size for tool calling, measure your recall, because the odds are the model never saw the tool you are blaming it for not picking.

## The caveats, as always

One model, one run, sixty tasks per condition, differences within the table smaller than its noise floor. The forced shortlist isolates selection but flatters no condition, since all four saw identical lists. And the ceiling on the alias numbers inherits the recall post's caveat: my aliases match my paraphrases by construction. What survives all of that comfortably is the shape: selection high and flat, recall variable and decisive.

The runner, the results with their description hashes, and everything needed to reproduce this against your own deployment are in the [repo](https://github.com/steefjan1/mcp-vs-api-azure-functions) under `measure/`; the whole run costs a few cents. Argue with the numbers directly, it is what the comment section of this series is for.
