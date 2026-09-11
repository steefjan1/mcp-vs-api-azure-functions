# MCP vs API: same backend, both doors

A working Azure Functions sample that settles the "MCP vs API" debate the practical way: one backend, exposed twice.

The app is a small restaurant directory (the "kitchen"). It has exactly one implementation of its business logic, and two doors into it:

- **Door one, a classic REST API.** Fixed HTTP endpoints for a developer who reads the docs and knows what to call.
- **Door two, a remote MCP server.** The same operations exposed as MCP tools that an AI agent can discover, understand, and call, using the [Azure Functions MCP extension](https://learn.microsoft.com/azure/azure-functions/functions-bindings-mcp).

Neither door contains business logic. Both call the same `IRestaurantDirectory` service. That is the point: MCP does not replace the API, it makes the same capability consumable by AI agents.

```
                        ┌──────────────────────────────────────────┐
                        │        Azure Functions (one app)         │
                        │                                          │
  Developer ──────────▶ │  HTTP triggers          ┌─────────────┐  │
  (knows the docs)      │  GET  /api/restaurants  │             │  │
                        │  GET  /api/.../menu ──▶ │ Restaurant  │  │
                        │  POST /api/orders       │ Directory   │  │
                        │                         │ (the        │  │
  AI agent ───────────▶ │  MCP tool triggers      │  kitchen)   │  │
  (discovers tools)     │  search_restaurants ──▶ │             │  │
                        │  get_menu               └─────────────┘  │
                        │  place_order                             │
                        └──────────────────────────────────────────┘
```

## Project layout

| Path | What it is |
|---|---|
| `src/RestaurantBackend/Services/` | The single backend service both doors call |
| `src/RestaurantBackend/Api/` | Door one: HTTP-triggered REST endpoints |
| `src/RestaurantBackend/Mcp/` | Door two: MCP tool triggers |
| `src/RestaurantBackend/test.http` | REST requests you can run from VS Code |
| `.vscode/mcp.json` | MCP server registration for VS Code / GitHub Copilot |
| `infra/` | Bicep for a Flex Consumption function app (azd) |

## Prerequisites

- [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)
- [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) v4
- [Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) for local storage emulation (`npm i -g azurite`)
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/) to deploy

## Run it locally

Start Azurite in one terminal:

```
azurite --silent
```

Start the function app in another:

```
cd src/RestaurantBackend
func start
```

You now have both doors open on `localhost:7071`.

### Door one: call the REST API

```
curl "http://localhost:7071/api/restaurants?cuisine=Italian"
curl "http://localhost:7071/api/restaurants/r1/menu"
curl -X POST "http://localhost:7071/api/orders" -H "Content-Type: application/json" -d "{\"restaurantId\":\"r1\",\"itemName\":\"Margherita\",\"quantity\":2}"
```

Or open `src/RestaurantBackend/test.http` in VS Code and run the requests from there.

### Door two: connect an MCP client

The MCP server (streamable HTTP) is at:

```
http://localhost:7071/runtime/webhooks/mcp
```

**VS Code / GitHub Copilot:** the repo ships `.vscode/mcp.json`. Open the file, start the `restaurant-directory-local` server, and the three tools appear in agent mode.

**Claude Desktop / Claude Code:** add a remote MCP server pointing at the URL above, for example:

```
claude mcp add --transport http restaurant-directory http://localhost:7071/runtime/webhooks/mcp
```

Then ask something like: *"Find me an Italian restaurant in Nijmegen, show me the menu, and order two Margheritas."* The agent chains `search_restaurants`, `get_menu`, and `place_order` on its own. That chain is the difference between the two doors: nobody wrote that orchestration.

## Deploy to Azure

```
azd up
```

This provisions a Flex Consumption function app (azd prompts for the region; `swedencentral` works well), storage with identity-based access, and Application Insights, then deploys the app. The outputs include both doors:

- `REST_API_BASE_URL`: the REST API base
- `MCP_SERVER_URL`: the MCP endpoint

In Azure, the MCP webhook is protected by a system key. Retrieve it with:

```
az functionapp keys list --resource-group <rg> --name <app-name> --query systemKeys.mcp_extension -o tsv
```

and send it as the `x-functions-key` header (the `restaurant-directory-azure` entry in `.vscode/mcp.json` prompts for it).

## Caveats, deliberately visible

This sample proves an architectural point, not a production posture:

- The REST endpoints are anonymous for demo purposes. In production, put them behind Azure API Management or function keys, and put the MCP endpoint behind Entra ID (the extension supports built-in MCP auth with Entra as identity provider).
- Orders live in memory and vanish on restart or scale-out. A real backend would use durable storage.
- Tool descriptions are load-bearing. The agent chooses tools based on the text in `McpToolTrigger` and `McpToolProperty`. Vague descriptions produce vague agents; treat them like API contracts.
- MCP does not make an agent intelligent, and it does not do authorization for you. Everything you already needed for APIs (authentication, permissions, observability, governance) you still need here, and more urgently.

## Blog post

This repo accompanies the Cloud Perspectives post "MCP vs API is the wrong question" on [sjwiggers.com](https://sjwiggers.com).
