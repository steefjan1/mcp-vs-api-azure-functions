using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Extensions.Mcp;
using Microsoft.Extensions.Logging;
using RestaurantBackend.Services;

namespace RestaurantBackend.Mcp;

/// <summary>
/// Identifies the deployed tool contract. The description hash is computed by
/// reflecting over the same McpTool* attributes the MCP extension serves, so
/// it can never drift from what clients actually see. Attach it to every
/// confusion log line and a rising counter becomes attributable to a specific
/// version of the words.
/// </summary>
public static class ToolContract
{
    public const string SchemaVersion = "1";

    public static readonly string DescriptionHash = Compute();

    private static string Compute()
    {
        var sb = new StringBuilder();
        foreach (var method in typeof(RestaurantMcpTools)
                     .GetMethods(BindingFlags.Public | BindingFlags.Instance)
                     .OrderBy(m => m.Name))
        {
            foreach (var parameter in method.GetParameters())
            {
                foreach (var attribute in parameter.GetCustomAttributesData())
                {
                    if (!attribute.AttributeType.Name.StartsWith("McpTool"))
                    {
                        continue;
                    }
                    foreach (var arg in attribute.ConstructorArguments)
                    {
                        sb.Append(arg.Value?.ToString()).Append('|');
                    }
                }
            }
        }
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(sb.ToString()));
        return Convert.ToHexString(bytes)[..12].ToLowerInvariant();
    }
}

/// <summary>
/// Door two: the same backend exposed as MCP tools. Nothing here is new
/// business logic. The value the MCP layer adds is self-description: an AI
/// agent connecting to this server can list the tools, read what each one
/// does, and see which parameters are required, without any documentation.
///
/// Every recovery message doubles as confusion telemetry: one structured log
/// line per return, tagged with a stable sentinel, the tool name, the
/// description hash, and the schema version. A rising count on one sentinel
/// is not an outage; it is a failing sentence in the tool contract, located
/// precisely.
/// </summary>
public class RestaurantMcpTools(IRestaurantDirectory directory, ILogger<RestaurantMcpTools> logger)
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    private string Confusion(string sentinel, string tool, string message)
    {
        logger.LogWarning(
            "Contract confusion: {Sentinel} on {Tool} (descHash {DescHash}, schemaVersion {SchemaVersion})",
            sentinel, tool, ToolContract.DescriptionHash, ToolContract.SchemaVersion);
        return message;
    }

    [Function(nameof(SearchRestaurantsTool))]
    public string SearchRestaurantsTool(
        [McpToolTrigger("search_restaurants", "Searches the restaurant directory. Both filters are optional; call it without arguments to list every restaurant.")]
            ToolInvocationContext context,
        [McpToolProperty("cuisine", "Cuisine to filter by, for example 'Italian' or 'Japanese'.", isRequired: false)]
            string? cuisine,
        [McpToolProperty("city", "City to filter by, for example 'Nijmegen' or 'Utrecht'.", isRequired: false)]
            string? city)
    {
        var results = directory.Search(cuisine, city);
        return results.Count == 0
            ? Confusion("search_no_match", "search_restaurants",
                "No restaurants matched. Try a different cuisine or city, or call the tool without filters to list all restaurants.")
            : JsonSerializer.Serialize(results, JsonOptions);
    }

    [Function(nameof(GetMenuTool))]
    public string GetMenuTool(
        [McpToolTrigger("get_menu", "Gets the menu for one restaurant, including item names, descriptions, and prices in euros.")]
            ToolInvocationContext context,
        [McpToolProperty("restaurantId", "The restaurant id, as returned by search_restaurants (for example 'r1').", isRequired: true)]
            string restaurantId)
    {
        var menu = directory.GetMenu(restaurantId);
        return menu is null
            ? Confusion("menu_unknown_restaurant", "get_menu",
                $"Restaurant '{restaurantId}' was not found. Use search_restaurants first to get a valid id.")
            : JsonSerializer.Serialize(menu, JsonOptions);
    }

    [Function(nameof(PlaceOrderTool))]
    public string PlaceOrderTool(
        [McpToolTrigger("place_order", "Places an order for one menu item at a restaurant and returns a confirmation with the total price.")]
            ToolInvocationContext context,
        [McpToolProperty("restaurantId", "The restaurant id, as returned by search_restaurants.", isRequired: true)]
            string restaurantId,
        [McpToolProperty("itemName", "The exact menu item name, as returned by get_menu.", isRequired: true)]
            string itemName,
        [McpToolProperty("quantity", "How many to order, between 1 and 20.", isRequired: true)]
            int quantity)
    {
        var confirmation = directory.PlaceOrder(new(restaurantId, itemName, quantity));
        return confirmation is null
            ? Confusion("order_rejected", "place_order",
                "The order could not be placed. Check the restaurant id with search_restaurants, the item name with get_menu, and keep quantity between 1 and 20.")
            : JsonSerializer.Serialize(confirmation, JsonOptions);
    }
}
