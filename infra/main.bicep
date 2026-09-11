targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment, used to derive resource names.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string = 'swedencentral'

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
  }
}

output AZURE_FUNCTION_APP_NAME string = resources.outputs.functionAppName
output REST_API_BASE_URL string = '${resources.outputs.functionAppUri}/api'
output MCP_SERVER_URL string = '${resources.outputs.functionAppUri}/runtime/webhooks/mcp'
