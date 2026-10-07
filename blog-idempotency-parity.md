# The Third Leg of the Parity Test

Months ago, a commenter on this series proposed a test: if the same backend really stands behind both doors, then auth, error behavior, and idempotency must be preserved across them. [Authorization Stays in the Kitchen](https://dev.to/steefjan_wiggers_34a415b/authorization-stays-in-the-kitchen-p59) settled the first leg. The confusion telemetry and recovery messages settled the second. This post settles the third, and it turns out to be the leg that matters most for agents, because agents retry.

## Why agents make this urgent

Code retries when a developer writes a retry policy. Agents retry on their own judgment: a timeout, an ambiguous error, a truncated response, and the model decides the call probably failed and tries again. Nothing in the MCP protocol stops the second call from being a second order. The new driver in the companion repo proves the failure mode as a control case before proving the fix:

```text
3. retry without clientOrderId    PASS: orderId 9714f45b then 99523aed (two orders exist, as feared)
```

Same restaurant, same item, same quantity, two calls, two orders. Every production incident involving an agent and a non-idempotent write looks like this line.

## One decision, one place, again

The series rule holds: neither door contains business logic, and deduplication is business logic. The kitchen keeps a store keyed on the caller's idempotency key, remembers a fingerprint of the request alongside the original confirmation, and answers one of four ways: placed, replayed, conflict, or invalid.

```csharp
if (idempotencyKey is not null
    && _byIdempotencyKey.TryGetValue(idempotencyKey, out var seen))
{
    return seen.Fingerprint == Fingerprint(request)
        ? new OrderResult(OrderOutcome.Replayed, seen.Confirmation)
        : new OrderResult(OrderOutcome.Conflict, null);
}
```

A replayed key with the same request returns the original confirmation and creates nothing. The same key with a different request is a conflict, which is always a caller bug and deserves to be refused loudly. The doors only translate those outcomes into their caller's dialect, exactly as they did for authorization.

## The REST door speaks header

HTTP already has a convention for this: the `Idempotency-Key` request header, specified in an [IETF httpapi draft](https://greenbytes.de/tech/webdav/draft-ietf-httpapi-idempotency-key-header-04.html) that Stripe, Adyen, and most payment APIs shaped in practice. The draft says a completed operation replays its original result and a key reused with a different payload SHOULD get a 422, so that is what the door does.

Verified live, the same curl twice:

```text
HTTP/1.1 200 OK
{"orderId":"97e92454","restaurantName":"Trattoria Valkhof","itemName":"Margherita","quantity":2,"total":23.00,"status":"confirmed"}

HTTP/1.1 200 OK
{"orderId":"97e92454","restaurantName":"Trattoria Valkhof","itemName":"Margherita","quantity":2,"total":23.00,"status":"confirmed"}
```

Same orderId, one order, and the client cannot tell the replay from the original, which is the whole point. Then the same key with quantity 5:

```text
HTTP/1.1 422 Unprocessable Entity
{"error":"idempotency_conflict","detail":"This Idempotency-Key was already used for a different request. Send a new key for a new order."}
```

## The MCP door has no headers

Here the two doors genuinely differ, and the difference is instructive. A tool call carries a name and arguments, nothing else, so the idempotency key cannot ride in a header. It has to be an argument, which means it has to be in the contract, which means a sentence has to teach the agent to use it:

```csharp
[McpToolProperty("clientOrderId", "An order reference that comes from you, the caller: invent a unique value, and reuse the same value if you retry this order after an error or timeout.", isRequired: false)]
    string? clientOrderId
```

That sentence is the mechanism. On the REST door, idempotency works because a developer read the docs and wrote a header into their client. On the MCP door, it works only if the description convinces the model to invent a reference and hold onto it across a retry. There is no SDK to do it for the agent; the prose is the SDK.

The series tooling priced and policed the sentence immediately. The [contract linter](https://dev.to/steefjan_wiggers_34a415b/linting-prose-in-ci-2ke0) flagged `clientOrderId` as an identifier parameter the moment it existed, so the description had to say where the value comes from, and this parameter gave the provenance rule its first unusual answer: it comes from you. The token budget rule priced the addition at 42 tokens, taking the contract from 302 to 344 against a budget of 350, so the next contract sentence will have to pay for itself by shortening another. And because the deployed description hash is computed from these same attributes, the descHash changed, and the [confusion telemetry](https://dev.to/steefjan_wiggers_34a415b/watching-the-contract-fail-in-production-2dnd) can attribute any behavior shift to this exact wording.

The driver verified both halves end to end against the deployed server:

```text
1. retry with same clientOrderId  PASS: orderId d120204a then d120204a (one order exists)
2. same key, different request    PASS: The clientOrderId 'order-2ccc9bd3' was already used for a different order.
```

The conflict answer is recovery prose, as this door's denials always are, and it goes out through the telemetry helper as a new `order_conflict` sentinel, so key misuse is observable next to every other contract failure. Replays log their own trace, which gives you a retry rate for free: how often agents actually double-fire is now a query, not a guess.

## Honest limits

The store is in-memory, like everything in this sample, so the replay guarantee spans one instance and one process lifetime. A production version needs a durable store with a TTL, and on a plan that scales out, a shared one. The guarantee is also only as good as the agent's discipline: an agent that invents a fresh clientOrderId on every retry gets no protection, and nothing in the protocol forces it to comply. The description can only persuade. That makes idempotency on the MCP door a probabilistic defense in a way it never was for REST clients, and a good candidate for the eval harness to measure someday: given a simulated timeout, does the model actually reuse the key the description told it to reuse?

## The takeaway

The parity test now passes on all three legs, and each leg landed the same way: one decision in the kitchen, one dialect per door. For idempotency the dialects are a standard header on one side and a contract sentence on the other, and the asymmetry is the lesson. REST made retries safe with infrastructure; MCP has to make them safe with language. If your tools write anything that costs money, the deduplication store is the easy half. The sentence that gets the agent to use it is the half this series keeps measuring.

The kitchen policy, both doors, and the double-fire driver are in the [companion repo](https://github.com/steefjan1/mcp-vs-api-azure-functions); run `measure/drive_idempotency.py` against your own server and see whether check 3 scares you as much as it should.
