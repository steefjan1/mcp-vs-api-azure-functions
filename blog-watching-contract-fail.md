# Watching the Contract Fail in Production

[Tool Descriptions Are the Contract](https://dev.to/steefjan_wiggers_34a415b/tool-descriptions-are-the-contract-5488) made a claim I had not tested: your MCP server's recovery messages are free confusion telemetry, because every time one is returned, you know exactly which misunderstanding just happened. The comment thread then designed the implementation better than I had: track each string alongside the tool version and a description hash, add the schema version as its own dimension, and treat a missing value as a first-class result, otherwise the cleanest dashboard is the one hiding the deployment that broke observability. This post builds exactly that, drives real traffic at it through the Entra-protected MCP door, and checks the dashboard against ground truth.

## The one-line change, and the hash that cannot drift

Each of the sample's three recovery returns now routes through one helper:

```csharp
private string Confusion(string sentinel, string tool, string message)
{
    logger.LogWarning(
        "Contract confusion: {Sentinel} on {Tool} (descHash {DescHash}, schemaVersion {SchemaVersion})",
        sentinel, tool, ToolContract.DescriptionHash, ToolContract.SchemaVersion);
    return message;
}
```

The sentinels are stable slugs, one per recovery sentence: `search_no_match`, `menu_unknown_restaurant`, `order_rejected`. The structured parameters become customDimensions in Application Insights, so the log line is a queryable row, not prose.

The description hash is the part worth stealing. The contract post showed that prose copies drift, so a hash maintained by hand would just be one more copy to forget. Instead, `ToolContract` computes it at startup by reflecting over the same `McpToolTrigger` and `McpToolProperty` attributes the MCP extension serves to clients, hashing every name and description in the deployed binary. The hash cannot disagree with what agents actually see, because it is derived from it. Edit one word of one description, redeploy, and every subsequent confusion row carries a new hash: the before and after of a contract change, joinable in KQL.

## Two doors before the traffic

Driving traffic at the server turned into its own small verification of [the 401 post](https://dev.to/steefjan_wiggers_34a415b/what-a-401-means-to-an-mcp-client-1a5i). The traffic driver is a Python script that speaks streamable-HTTP MCP directly, and since the server has built-in Entra authentication, the driver needs a bearer token. Getting one stopped at two separate gates.

First, Entra refused to mint the token at all: AADSTS65001, because Azure CLI, the tool requesting it, was not on the app registration's preauthorized client list. Then, with that fixed, the function app answered 403, because App Service authentication keeps its own allowed-client-applications list, and the CLI was not on that one either. The known-clients control from the 401 post exists twice, independently: Entra decides who may start the flow, Easy Auth decides whose tokens the app accepts, and a client must pass both. My own traffic generator had to be admitted as a known client, twice, before it was allowed to confuse the server. For a regulated organization, that is not friction; that is the audit trail existing before you asked for it.

## The traffic, with ground truth attached

The driver then made 60 calls: a rotation of requests that are wrong the way agents are actually wrong. An invented restaurant id, a restaurant name where an id belongs, a menu item from memory instead of from get_menu, a quantity past the cap, filters that match nothing, and valid calls as control. Because the rotation is deterministic, the console output is ground truth: exactly 16 `menu_unknown_restaurant`, 16 `order_rejected`, 14 `search_no_match`, and 14 clean results.

Which makes the dashboard check a real test instead of a demo. In Application Insights:

```kusto
traces
| where message startswith "Contract confusion"
| extend sentinel = tostring(customDimensions.Sentinel),
         tool = tostring(customDimensions.Tool),
         descHash = tostring(customDimensions.DescHash),
         schemaVersion = tostring(customDimensions.SchemaVersion)
| summarize confusions = count() by sentinel, tool, descHash, schemaVersion
| order by confusions desc
```

The result: `order_rejected` 16, `menu_unknown_restaurant` 16, `search_no_match` 14, every row carrying the same descHash and schemaVersion 1. The dashboard matches the driver's console exactly, so the pipeline is verified end to end, from a wrong argument in a JSON-RPC call to an attributable row in a Log Analytics table.

## Reading the dashboard as a contract report

Each sentinel names a failing sentence. A rising `menu_unknown_restaurant` count says the provenance sentence in get_menu's description, "as returned by search_restaurants", is not landing: agents are inventing ids. A rising `search_no_match` says callers expect a wider catalog than the descriptions promise. And because every row carries the descHash, the response to a bad trend is an experiment, not an argument: rewrite the sentence, redeploy, and compare the same sentinel across the two hashes. The description edit gets the same before-and-after treatment a performance fix gets.

The commenters' missing-value rule matters here too. The healthy state of this dashboard is not empty, it is present-with-baseline: some confusion is normal while valid traffic flows. A sentinel that silently vanishes, or rows arriving without a descHash, means a deployment broke the telemetry, not that agents stopped being confused. The alert to write is on absence and on unknown dimension values, not only on spikes.

## What is still missing, honestly

One dimension from the design is not in these rows: the client. The MCP initialize handshake carries clientInfo with a name and version, but the Functions MCP extension does not currently hand that to the tool method through `ToolInvocationContext`, so per-client confusion rates are not yet possible at this layer. That is a real gap; per-client breakdowns are how you distinguish one badly prompted agent from a contract problem affecting everyone. Until the extension exposes it, the client mix has to come from the platform's request telemetry instead of the tool's own rows.

## The takeaway

This is the cheapest contract test I know of: one logging helper, three stable sentinels, a hash computed from the deployed attributes so it can never drift, and a KQL query. The recovery messages were already written, the dashboard was already there; connecting them turns every agent mistake into an attributable data point against a specific version of your words. The prose is the interface, and now the interface has monitoring.

The code, the traffic driver, and the queries are in the [companion repo](https://github.com/steefjan1/mcp-vs-api-azure-functions); the whole change is one class and one helper in `src/RestaurantBackend/Mcp/RestaurantMcpTools.cs`, and `measure/drive_confusion.py` reproduces the traffic against any MCP server of your own.
