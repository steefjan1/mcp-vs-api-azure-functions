namespace RestaurantBackend.Models;

/// <summary>A restaurant in the directory. This is the "kitchen" both doors lead to.</summary>
public record Restaurant(string Id, string Name, string Cuisine, string City, decimal Rating);

/// <summary>A single dish on a restaurant menu.</summary>
public record MenuItem(string Name, string Description, decimal Price);

/// <summary>A menu belonging to one restaurant.</summary>
public record Menu(string RestaurantId, string RestaurantName, IReadOnlyList<MenuItem> Items);

/// <summary>An order request as it arrives through either door.</summary>
public record OrderRequest(string RestaurantId, string ItemName, int Quantity);

/// <summary>A confirmed order, returned identically by the REST API and the MCP tool.</summary>
public record OrderConfirmation(
    string OrderId,
    string RestaurantName,
    string ItemName,
    int Quantity,
    decimal Total,
    string Status);

/// <summary>
/// What the kitchen decided about an order attempt. Replayed means the same
/// idempotency key arrived again with the same request, so the original
/// confirmation is returned and no second order exists. Conflict means the
/// key was reused with a different request, which is always a caller bug.
/// </summary>
public enum OrderOutcome { Placed, Replayed, Conflict, Invalid }

/// <summary>The kitchen's answer: an outcome, plus the confirmation when one exists.</summary>
public record OrderResult(OrderOutcome Outcome, OrderConfirmation? Confirmation);
