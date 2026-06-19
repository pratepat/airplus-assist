param storageAccountName string
param searchServiceName string
param openAiAccountName string
param acrName string
param caEnvName string
param location string = 'swedencentral'

// ── Azure OpenAI ───────────────────────────────────────────────────────────────

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2026-03-01' = {
  name: openAiAccountName
  location: location
  sku: {
    name: 'S0'
  }
  kind: 'OpenAI'
  properties: {
    apiProperties: {}
    customSubDomainName: openAiAccountName
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
    allowProjectManagement: false
    publicNetworkAccess: 'Enabled'
    storedCompletionsDisabled: false
  }
}

// Defender settings omitted — modifying this child resource causes RequestConflict
// on the parent account when OpenAI deployments are still settling.

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-03-01' = {
  parent: openAiAccount
  name: 'text-embedding-3-small'
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-03-01' = {
  parent: openAiAccount
  name: 'gpt-4o-mini'
  dependsOn: [embeddingDeployment]
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// ── Azure AI Search ────────────────────────────────────────────────────────────

resource searchService 'Microsoft.Search/searchServices@2026-03-01-preview' = {
  name: searchServiceName
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    computeType: 'Default'
    publicNetworkAccess: 'Enabled'
    networkRuleSet: {
      ipRules: []
      bypass: 'None'
    }
    encryptionWithCmk: {
      enforcement: 'Unspecified'
    }
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    dataExfiltrationProtections: []
    semanticSearch: 'free'
    knowledgeRetrieval: 'free'
  }
}

// ── Storage Account ────────────────────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2026-04-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    dnsEndpointType: 'Standard'
    defaultToOAuthAuthentication: false
    publicNetworkAccess: 'Enabled'
    allowCrossTenantReplication: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    networkAcls: {
      bypass: 'AzureServices'
      virtualNetworkRules: []
      ipRules: []
      defaultAction: 'Allow'
    }
    supportsHttpsTrafficOnly: true
    encryption: {
      services: {
        file: {
          keyType: 'Account'
          enabled: true
        }
        blob: {
          keyType: 'Account'
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
    }
    accessTier: 'Hot'
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2026-04-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: true
      days: 7
    }
  }
}

resource contentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-04-01' = {
  parent: blobServices
  name: 'content'
  properties: {
    publicAccess: 'None'
  }
}

// ── Container Registry ─────────────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// ── Container Apps ─────────────────────────────────────────────────────────────

resource caEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: caEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
  }
}

resource caApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'airplus-assist'
  location: location
  properties: {
    environmentId: caEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
        {
          name: 'storage-connection'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net'
        }
        {
          name: 'search-key'
          value: searchService.listAdminKeys().primaryKey
        }
        {
          name: 'openai-key'
          value: openAiAccount.listKeys().key1
        }
      ]
    }
    template: {
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
      containers: [
        {
          name: 'airplus-assist'
          image: '${acr.properties.loginServer}/airplus-assist:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAiAccount.properties.endpoint }
            { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-key' }
            { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${searchServiceName}.search.windows.net' }
            { name: 'AZURE_SEARCH_KEY', secretRef: 'search-key' }
            { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection' }
            { name: 'AZURE_STORAGE_CONTAINER', value: 'content' }
          ]
        }
      ]
    }
  }
}

// ── Outputs ────────────────────────────────────────────────────────────────────

output openAiEndpoint string = openAiAccount.properties.endpoint
output searchEndpoint string = 'https://${searchServiceName}.search.windows.net'
output storageAccountName string = storageAccount.name
output acrLoginServer string = acr.properties.loginServer
output containerAppUrl string = 'https://${caApp.properties.configuration.ingress.fqdn}'
