# MCP vs API Is the Wrong Question

I keep seeing "MCP vs API" discussed as if we need to choose one. We don't. They solve different problems, and the fastest way to see that is to run the same backend behind both. So that is what I built: one Azure Functions app that exposes identical business logic twice, once as a classic REST API and once as a remote MCP server. The code is in the companion repo, and this post walks through what it shows.

## Two different problems

The simplest way I think about it is this. An API tells software how to talk to another piece of software. MCP, the Model Context Protocol, helps an AI system understand what tools and resources are available, and how to use them.

Consider a normal application that needs a file from Google Drive. The developer already knows what is needed: app, Google Drive API, file. They read the API documentation, call the right endpoint, and process the response. The knowledge lives in the developer and gets compiled into the application.

Now ask an AI assistant: "Find our latest sales presentation, compare the numbers with our customer database, check whether the related GitHub project has changed, and summarise everything." The assistant may need to work across Google Drive, a database, GitHub, and internal documents. Nobody hardcoded that sequence. The AI has to discover what tools exist, what each one does, which parameters are required, and which tool to use next. That discovery problem is what MCP solves.

A good analogy: an API is calling a restaurant directly. You already know the restaurant, its number, and what you want. MCP is giving your assistant a standardised directory of restaurants, menus, and available actions. The assistant discovers what is available and chooses the right capability. And underneath, the restaurant still uses the same kitchen. That kitchen is often the API.

## Same kitchen, two doors

I took that analogy literally. The sample is a small restaurant directory with exactly one implementation of its business logic, an `IRestaurantDirectory` service that can search restaurants, return menus, and place orders. In front of it sit two doors.

Door one is the REST API, three HTTP-triggered functions:

```csharp
[Function(nameof(GetRestaurants))]
public IActionResult GetRestaurants(
    [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "restaurants")] HttpRequest req)
{
    string? cuisine = req.Query["cuisine"];
    string? city = req.Query["city"];
    return new OkObjectResult(directory.Search(cuisine, city));
}
```

Fixed endpoints, documented parameters, request and response. If you know the contract, this is the most direct path there is.

Door two is the MCP server, built with the Azure Functions MCP extension. I compared the hosting options for remote MCP servers on Functions in an [earlier post](https://sjwiggers.com/hosting-mcp-servers-azure-functions); this sample uses the binding extension, which has since reached a stable 1.x release with typed tool property attributes. The same operations become tools, and the trigger attributes carry something the REST door never needed: descriptions written for a machine that has to figure out what to call.

```csharp
[Function(nameof(SearchRestaurantsTool))]
public string SearchRestaurantsTool(
    [McpToolTrigger("search_restaurants",
        "Searches the restaurant directory. Both filters are optional; call it without arguments to list every restaurant.")]
        ToolInvocationContext context,
    [McpToolProperty("cuisine", "Cuisine to filter by, for example 'Italian' or 'Japanese'.", isRequired: false)]
        string? cuisine,
    [McpToolProperty("city", "City to filter by, for example 'Nijmegen' or 'Utrecht'.", isRequired: false)]
        string? city)
    => ...
```

Neither door contains business logic. Both call the same service. The Functions runtime hosts the MCP endpoint at `/runtime/webhooks/mcp`, protected in Azure by a system key, and the whole thing deploys to a Flex Consumption plan with `azd up`.

## What changes at door two

Run the app locally, point an MCP client at it (the repo ships a `.vscode/mcp.json` for VS Code, and Claude works too), and ask: "Find me an Italian restaurant in Nijmegen, show me the menu, and order two Margheritas."

The agent lists the available tools, reads their descriptions, and chains `search_restaurants`, `get_menu`, and `place_order` on its own. It passes the restaurant id from the first call into the second, and the exact item name from the second into the third. Nobody wrote that orchestration. Against the REST door, that same flow is three documented calls a developer wires together at design time.

That is the whole difference in one demo. The REST door serves callers who know. The MCP door serves callers who discover. Instead of teaching an AI system separately how to interact with twenty different tools, MCP gives those tools a consistent way to expose capabilities, which makes AI systems easier to extend, orchestrate, and maintain.

One consequence surprised me in a useful way: tool descriptions become load-bearing. The agent chooses tools based on the text in those attributes. Vague descriptions produce vague agents. Treat tool descriptions like API contracts, because for an agent, they are.

## Where MCP is the wrong answer

MCP is not the right door for everything, and reaching for it by default is how we get the next round of architecture astronautics.

Skip MCP when the caller is deterministic software. A backend service that needs a file from Drive should call the Drive API. Adding an MCP layer between two pieces of conventional software adds latency and a dependency, and discovers nothing, because there is no model doing the discovering.

Skip it when there is exactly one integration and it will stay that way. The discovery machinery pays off across many tools; for a single well-known endpoint it is overhead.

And be honest about what MCP does not do. It does not make an agent intelligent, and it does not do authorization for you. Everything we already needed for APIs, authentication, permissions, observability, and governance, we still need here. In fact, the more actions we allow AI to perform, the more important these become. In the sample, the demo endpoints are deliberately anonymous and the caveats section of the README says so out loud; in production, the REST door belongs behind API Management and the MCP door behind Entra ID, which the Functions extension now supports as built-in MCP auth.

## The real opportunity

So when someone asks me which is better, MCP or API, my answer is: wrong comparison. The architecture that keeps showing up in practice is AI assistant, MCP, existing API, business system. APIs connect software. MCP helps AI understand how to interact with that software. And AI agents turn those connections into actions and workflows.

The sample repo has the full code, local run instructions, and Bicep to deploy both doors to Azure Functions: [mcp-vs-api-azure-functions](https://github.com/steefjan1/mcp-vs-api-azure-functions). Clone it, open both doors, and the debate settles itself.
