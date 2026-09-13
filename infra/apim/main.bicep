// Deploys API Management in front of the mcp-vs-api sample, demonstrating the
// three gateway patterns from the follow-up post:
//   1. APIM in front of the REST door (classic gateway)
//   2. APIM as passthrough for the Functions MCP door (key injected by policy)
//   3. APIM as the MCP door itself (tools generated from the REST operations)
//
// Deploy into the SAME resource group as the function app:
//   az deployment group create -g <rg> -f infra/apim/main.bicep \
//     -p functionAppName=<func-app-name> publisherEmail=<you@example.com> \
//     -p mcpExtensionKey=<mcp_extension system key>

@description('Name of the existing function app from the base sample.')
param functionAppName string

@description('Publisher email required by API Management.')
param publisherEmail string

@description('Publisher name shown in the developer portal.')
param publisherName string = 'Cloud Perspectives'

@description('The mcp_extension system key of the function app; injected toward the backend by policy in pattern 2. Never handed to clients.')
@secure()
param mcpExtensionKey string

@description('Location for API Management. Defaults to the resource group location.')
param location string = resourceGroup().location

var apimName = 'apim-restaurant-${uniqueString(resourceGroup().id)}'
var functionHost = 'https://${functionAppName}.azurewebsites.net'

resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' = {
  name: apimName
  location: location
  sku: {
    name: 'BasicV2'
    capacity: 1
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

// The backend key as a secret named value; policies reference it as {{mcp-extension-key}}.
resource mcpKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-06-01-preview' = {
  parent: apim
  name: 'mcp-extension-key'
  properties: {
    displayName: 'mcp-extension-key'
    secret: true
    value: mcpExtensionKey
  }
}

// ---------------------------------------------------------------------------
// Pattern 1: APIM in front of the REST door
// ---------------------------------------------------------------------------

resource restApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'restaurant-rest'
  properties: {
    displayName: 'Restaurant REST API'
    description: 'The REST door of the mcp-vs-api sample, governed by the gateway.'
    path: 'restaurant'
    protocols: [ 'https' ]
    serviceUrl: '${functionHost}/api'
    subscriptionRequired: true
  }
}

resource getRestaurants 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: restApi
  name: 'get-restaurants'
  properties: {
    displayName: 'List restaurants'
    method: 'GET'
    urlTemplate: '/restaurants'
    description: 'Lists restaurants, optionally filtered by cuisine and city query parameters.'
  }
}

resource getRestaurantMenu 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: restApi
  name: 'get-restaurant-menu'
  properties: {
    displayName: 'Get menu'
    method: 'GET'
    urlTemplate: '/restaurants/{restaurantId}/menu'
    description: 'Returns the menu for one restaurant.'
    templateParameters: [
      {
        name: 'restaurantId'
        type: 'string'
        required: true
        description: 'The restaurant id, for example r1.'
      }
    ]
  }
}

resource placeOrder 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = {
  parent: restApi
  name: 'place-order'
  properties: {
    displayName: 'Place order'
    method: 'POST'
    urlTemplate: '/orders'
    description: 'Places an order for one menu item and returns a confirmation with the total price.'
  }
}

// Gateway governance for the REST door: rate limiting per subscription.
resource restApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: restApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: '''
<policies>
  <inbound>
    <base />
    <rate-limit calls="30" renewal-period="60" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
'''
  }
}

// ---------------------------------------------------------------------------
// Pattern 2: APIM as passthrough for the Functions MCP door
// The agent authenticates to APIM; a policy injects the backend system key.
// ---------------------------------------------------------------------------

resource mcpPassthrough 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'restaurant-mcp'
  properties: {
    type: 'mcp'
    displayName: 'Restaurant MCP (passthrough)'
    description: 'The Functions-hosted MCP door, governed by the gateway. Tool descriptions live in the function code.'
    path: 'restaurant-mcp'
    protocols: [ 'https' ]
    serviceUrl: functionHost
    subscriptionRequired: true
    mcpProperties: {
      transportType: 'streamable'
      endpoints: {
        message: {
          uriTemplate: '/runtime/webhooks/mcp'
        }
      }
    }
  }
}

resource mcpPassthroughPolicy 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: mcpPassthrough
  name: 'policy'
  dependsOn: [ mcpKeyNamedValue ]
  properties: {
    format: 'rawxml'
    value: '''
<policies>
  <inbound>
    <base />
    <!-- The client never holds the backend credential; the gateway injects it. -->
    <set-header name="x-functions-key" exists-action="override">
      <value>{{mcp-extension-key}}</value>
    </set-header>
    <rate-limit calls="60" renewal-period="60" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
'''
  }
}

// ---------------------------------------------------------------------------
// Pattern 3: APIM as the MCP door, generated from the REST operations.
// Note where the tool descriptions live now: in this file, not in the C#.
// ---------------------------------------------------------------------------

resource mcpGenerated 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'restaurant-mcp-generated'
  properties: {
    type: 'mcp'
    displayName: 'Restaurant MCP (generated from REST)'
    description: 'MCP server manufactured by the gateway from the REST API. Tools only; no resources or prompts.'
    path: 'restaurant-mcp-generated'
    protocols: [ 'https' ]
    subscriptionRequired: true
  }
}

resource toolSearchRestaurants 'Microsoft.ApiManagement/service/apis/tools@2025-09-01-preview' = {
  parent: mcpGenerated
  name: 'search_restaurants'
  properties: {
    displayName: 'search_restaurants'
    description: 'Searches the restaurant directory. Both cuisine and city filters are optional; call without arguments to list every restaurant.'
    operationId: getRestaurants.id
  }
}

resource toolGetMenu 'Microsoft.ApiManagement/service/apis/tools@2025-09-01-preview' = {
  parent: mcpGenerated
  name: 'get_menu'
  properties: {
    displayName: 'get_menu'
    description: 'Gets the menu for one restaurant, including item names, descriptions, and prices in euros. The restaurant id comes from search_restaurants.'
    operationId: getRestaurantMenu.id
  }
}

resource toolPlaceOrder 'Microsoft.ApiManagement/service/apis/tools@2025-09-01-preview' = {
  parent: mcpGenerated
  name: 'place_order'
  properties: {
    displayName: 'place_order'
    description: 'Places an order for one menu item at a restaurant and returns a confirmation with the total price. Item names come from get_menu.'
    operationId: placeOrder.id
  }
}

output apimName string = apim.name
output patternOneRestUrl string = '${apim.properties.gatewayUrl}/restaurant'
output patternTwoMcpUrl string = '${apim.properties.gatewayUrl}/restaurant-mcp/mcp'
output patternThreeMcpUrl string = '${apim.properties.gatewayUrl}/restaurant-mcp-generated/mcp'
