using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Azure.Functions.Worker;
using RestaurantBackend.Models;
using RestaurantBackend.Services;

namespace RestaurantBackend.Api;

/// <summary>
/// Door one: a classic REST API. The caller (a developer) already knows these
/// endpoints exist, what they return, and which parameters they take, because
/// they read the documentation. Fixed endpoints, request and response.
/// </summary>
public class RestaurantHttpApi(IRestaurantDirectory directory)
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    [Function(nameof(GetRestaurants))]
    public IActionResult GetRestaurants(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "restaurants")] HttpRequest req)
    {
        string? cuisine = req.Query["cuisine"];
        string? city = req.Query["city"];
        return new OkObjectResult(directory.Search(cuisine, city));
    }

    [Function(nameof(GetRestaurantMenu))]
    public IActionResult GetRestaurantMenu(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "restaurants/{restaurantId}/menu")] HttpRequest req,
        string restaurantId)
    {
        var menu = directory.GetMenu(restaurantId);
        return menu is null
            ? new NotFoundObjectResult(new { error = $"Restaurant '{restaurantId}' not found." })
            : new OkObjectResult(menu);
    }

    [Function(nameof(PlaceOrder))]
    public async Task<IActionResult> PlaceOrder(
        [HttpTrigger(AuthorizationLevel.Anonymous, "post", Route = "orders")] HttpRequest req)
    {
        OrderRequest? order;
        try
        {
            order = await JsonSerializer.DeserializeAsync<OrderRequest>(req.Body, JsonOptions);
        }
        catch (JsonException)
        {
            return new BadRequestObjectResult(new { error = "Request body must be valid JSON." });
        }

        if (order is null || string.IsNullOrWhiteSpace(order.RestaurantId) || string.IsNullOrWhiteSpace(order.ItemName))
        {
            return new BadRequestObjectResult(new { error = "restaurantId and itemName are required." });
        }

        // The kitchen decides; this door renders the decision as a machine-
        // shaped 403, because its caller is code and code branches on status.
        var caller = CallerContext.FromClientPrincipal(req.Headers["x-ms-client-principal"]);
        if (!OrderPolicy.MayPlaceOrders(caller))
        {
            return new ObjectResult(new
            {
                error = "forbidden",
                detail = $"Placing orders requires the {OrderPolicy.RequiredRole} role.",
                requiredRole = OrderPolicy.RequiredRole
            })
            { StatusCode = StatusCodes.Status403Forbidden };
        }

        // Idempotency: the client supplies a key in the standard header; the
        // kitchen deduplicates. This door only translates the kitchen's
        // outcome into status codes: a replay is a 200 with the original
        // body, a key reused for a different request is a 422.
        string? idempotencyKey = req.Headers["Idempotency-Key"];
        var result = directory.PlaceOrder(order, idempotencyKey);
        return result.Outcome switch
        {
            OrderOutcome.Conflict => new ObjectResult(new
            {
                error = "idempotency_conflict",
                detail = "This Idempotency-Key was already used for a different request. Send a new key for a new order."
            })
            { StatusCode = StatusCodes.Status422UnprocessableEntity },
            OrderOutcome.Invalid => new BadRequestObjectResult(new { error = "Unknown restaurant or menu item, or invalid quantity (1-20)." }),
            _ => new OkObjectResult(result.Confirmation)
        };
    }
}
