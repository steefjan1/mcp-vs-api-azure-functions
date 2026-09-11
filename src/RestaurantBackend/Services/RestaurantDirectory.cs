using System.Collections.Concurrent;
using RestaurantBackend.Models;

namespace RestaurantBackend.Services;

/// <summary>
/// The single business capability in this sample. Both the REST API and the
/// MCP tools call this service. Neither door contains business logic of its own.
/// </summary>
public interface IRestaurantDirectory
{
    IReadOnlyList<Restaurant> Search(string? cuisine, string? city);
    Menu? GetMenu(string restaurantId);
    OrderConfirmation? PlaceOrder(OrderRequest request);
}

public class InMemoryRestaurantDirectory : IRestaurantDirectory
{
    private static readonly IReadOnlyList<Restaurant> Restaurants =
    [
        new("r1", "Trattoria Valkhof", "Italian", "Nijmegen", 4.6m),
        new("r2", "De Molen Bistro", "Dutch", "Nijmegen", 4.3m),
        new("r3", "Sakura House", "Japanese", "Utrecht", 4.7m),
        new("r4", "Casa Andaluz", "Spanish", "Utrecht", 4.2m),
        new("r5", "Spice Route", "Indian", "Amsterdam", 4.5m),
        new("r6", "Canal Greens", "Vegetarian", "Amsterdam", 4.4m),
    ];

    private static readonly IReadOnlyDictionary<string, IReadOnlyList<MenuItem>> Menus =
        new Dictionary<string, IReadOnlyList<MenuItem>>
        {
            ["r1"] = [new("Margherita", "Tomato, mozzarella, basil", 11.50m), new("Tagliatelle al ragù", "Slow-cooked beef ragù", 16.00m), new("Tiramisu", "Classic, made in house", 7.50m)],
            ["r2"] = [new("Stamppot", "Kale mash with smoked sausage", 13.00m), new("Bitterballen", "Eight pieces with mustard", 6.50m), new("Appeltaart", "With whipped cream", 5.50m)],
            ["r3"] = [new("Sushi moriawase", "Chef's selection, 12 pieces", 24.00m), new("Ramen shoyu", "Soy-based broth, chashu pork", 15.50m), new("Matcha ice cream", "Two scoops", 6.00m)],
            ["r4"] = [new("Paella mixta", "Chicken and seafood, for one", 19.50m), new("Gambas al ajillo", "Garlic prawns", 12.00m), new("Crema catalana", "Torched to order", 6.50m)],
            ["r5"] = [new("Butter chicken", "With basmati rice and naan", 17.00m), new("Chana masala", "Chickpea curry, vegan", 14.00m), new("Gulab jamun", "Two pieces in syrup", 5.00m)],
            ["r6"] = [new("Seasonal risotto", "With local vegetables", 16.50m), new("Beetroot carpaccio", "Goat cheese, walnuts", 10.50m), new("Chocolate torte", "Flourless", 7.00m)],
        };

    private readonly ConcurrentDictionary<string, OrderConfirmation> _orders = new();

    public IReadOnlyList<Restaurant> Search(string? cuisine, string? city) =>
        Restaurants
            .Where(r => string.IsNullOrWhiteSpace(cuisine) || r.Cuisine.Equals(cuisine.Trim(), StringComparison.OrdinalIgnoreCase))
            .Where(r => string.IsNullOrWhiteSpace(city) || r.City.Equals(city.Trim(), StringComparison.OrdinalIgnoreCase))
            .ToList();

    public Menu? GetMenu(string restaurantId)
    {
        var restaurant = Restaurants.FirstOrDefault(r => r.Id == restaurantId);
        if (restaurant is null || !Menus.TryGetValue(restaurantId, out var items))
        {
            return null;
        }

        return new Menu(restaurant.Id, restaurant.Name, items);
    }

    public OrderConfirmation? PlaceOrder(OrderRequest request)
    {
        if (request.Quantity is < 1 or > 20)
        {
            return null;
        }

        var menu = GetMenu(request.RestaurantId);
        var item = menu?.Items.FirstOrDefault(i => i.Name.Equals(request.ItemName?.Trim(), StringComparison.OrdinalIgnoreCase));
        if (menu is null || item is null)
        {
            return null;
        }

        var confirmation = new OrderConfirmation(
            OrderId: Guid.NewGuid().ToString("N")[..8],
            RestaurantName: menu.RestaurantName,
            ItemName: item.Name,
            Quantity: request.Quantity,
            Total: item.Price * request.Quantity,
            Status: "confirmed");

        _orders[confirmation.OrderId] = confirmation;
        return confirmation;
    }
}
