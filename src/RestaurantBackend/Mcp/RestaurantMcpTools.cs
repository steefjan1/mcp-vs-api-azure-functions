using System.Text.Json;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Extensions.Mcp;
using RestaurantBackend.Services;

namespace RestaurantBackend.Mcp;

/// <summary>
/// Door two: the same backend exposed as MCP tools. Nothing here is new
/// business logic. The value the MCP layer adds is self-description: an AI
/// agent connecting to this server can list the tools, read what each one
/// does, and see which parameters are required, without any documentation.
/// </summary>
public class RestaurantMcpTools(IRestaurantDirectory directory)
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { WriteIndented = true };

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
            ? "No restaurants matched. Try a different cuisine or city, or call the tool without filters to list all restaurants."
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
            ? $"Restaurant '{restaurantId}' was not found. Use search_restaurants first to get a valid id."
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
            ? "The order could not be placed. Check the restaurant id with search_restaurants, the item name with get_menu, and keep quantity between 1 and 20."
            : JsonSerializer.Serialize(confirmation, JsonOptions);
    }
}
