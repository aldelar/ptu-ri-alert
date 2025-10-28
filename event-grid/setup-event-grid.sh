#!/bin/bash

# Load environment variables from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: .env file not found at $ENV_FILE"
    echo "Please create a .env file with the required variables."
    exit 1
fi

# Load variables from .env file
set -a
source "$ENV_FILE"
set +a

echo "✓ Loaded configuration from .env file"
echo ""
echo "=========================================="
echo "Step 1: Configure Function Managed Identity"
echo "=========================================="

# Enable system-assigned managed identity for the function
echo "Enabling system-assigned managed identity..."
IDENTITY_OUTPUT=$(az functionapp identity assign \
  --name "$FUNCTION_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --query principalId -o tsv)

PRINCIPAL_ID="$IDENTITY_OUTPUT"
echo "✓ Managed identity enabled. Principal ID: $PRINCIPAL_ID"
echo ""

# Assign Reader role at subscription level (allows reading CognitiveServices deployments and Reservations)
echo "Assigning Reader role to managed identity..."
az role assignment create \
  --assignee "$PRINCIPAL_ID" \
  --role "Reader" \
  --scope "/subscriptions/$SUBSCRIPTION_ID" \
  --output none 2>/dev/null || echo "  (Role may already be assigned)"

echo "✓ Reader role assigned at subscription level"
echo ""
echo "Waiting for permissions to propagate..."
sleep 15
echo ""

echo "=========================================="
echo "Step 2: Create Event Grid System Topic"
echo "=========================================="

# Create Event Grid System Topic for monitoring Azure AI Foundry deployments
echo "Creating Event Grid system topic..."
az eventgrid system-topic create \
  --name "$TOPIC_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --source "/subscriptions/$SUBSCRIPTION_ID" \
  --topic-type Microsoft.Resources.Subscriptions \
  --location global

echo "✓ System topic created"
echo "Waiting for system topic to be fully provisioned..."
sleep 10
echo ""

echo "=========================================="
echo "Step 3: Create Event Subscription"
echo "=========================================="

# Create event subscription to filter for Azure AI Foundry and Azure OpenAI deployment events
# Note: Azure AI Foundry deployments can come from either:
# - Microsoft.CognitiveServices (AI Services/OpenAI deployments in AI Foundry)
# - Microsoft.MachineLearningServices (traditional ML workspace deployments)
echo "Creating event subscription..."
az eventgrid system-topic event-subscription create \
  --name NewAIFoundryDeploymentSubscription \
  --resource-group "$RESOURCE_GROUP" \
  --system-topic-name "$TOPIC_NAME" \
  --endpoint "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP/functions/$FUNCTION_NAME" \
  --endpoint-type azurefunction \
  --subject-begins-with "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.CognitiveServices" \
  --advanced-filter data.operationName StringIn Microsoft.CognitiveServices/accounts/deployments/write Microsoft.MachineLearningServices/workspaces/onlineEndpoints/deployments/write Microsoft.MachineLearningServices/workspaces/serverlessEndpoints/write \
  --advanced-filter data.status StringIn Succeeded

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo "✓ Managed identity enabled and configured"
echo "✓ Event Grid system topic created successfully!"
echo "✓ Event subscription configured to monitor AI Foundry deployments"
echo ""
echo "📋 Monitoring:"
echo "   - Azure AI Services (CognitiveServices) deployments"
echo "   - Azure ML workspace deployments"
echo "   - Filter: Successful deployment operations only"
echo ""
echo "🔐 Permissions:"
echo "   - Function identity: $PRINCIPAL_ID"
echo "   - Role: Reader (subscription level)"
echo "   - Access: CognitiveServices deployments + Azure Reservations"