# PTU RI Alert

Azure Function to monitor and alert on Azure AI Foundry PTU (Provisioned Throughput Units) deployments and track capacity vs reservations.

## Overview

This solution automatically monitors Azure AI Foundry model deployments and compares total PTU capacity against Azure Reservations to detect over-allocation or under-utilization.

## Architecture

```mermaid
graph TB
    subgraph "Azure AI Foundry"
        A[Model Deployment<br/>Create/Update]
    end
    
    subgraph "Event Grid"
        B[System Topic<br/>Microsoft.Resources.Subscriptions]
        C[Event Subscription<br/>Filtered by:<br/>- AI Foundry deployments<br/>- Status: Succeeded]
    end
    
    subgraph "Azure Function"
        D[ptu-ri-alert-function<br/>Event Grid Trigger]
        E[Scan All Workspaces<br/>for PTU Deployments]
        F[Query Azure<br/>Reservations API]
        G[Compare Capacity<br/>vs Reservations]
        H[Generate Report<br/>& Log Alerts]
    end
    
    subgraph "Azure Resources"
        I[ML Workspaces<br/>Serverless Endpoints]
        J[Azure Reservations<br/>PTU Reservations]
    end
    
    A -->|Resource Write Event| B
    B -->|Forward Event| C
    C -->|Trigger| D
    D --> E
    D --> F
    E -->|Read| I
    F -->|Read| J
    E --> G
    F --> G
    G --> H
    
    style A fill:#0078d4,stroke:#004578,color:#fff
    style D fill:#f2c811,stroke:#c9a700,color:#000
    style H fill:#00aa00,stroke:#008800,color:#fff
```

## Prerequisites

- Azure CLI installed and authenticated
- Azure Functions Core Tools v4
- Python 3.11+
- Azure subscription with:
  - Azure AI Foundry project(s)
  - Azure Function App (Flex Consumption or Consumption plan)
  - Permissions to create Event Grid topics and subscriptions
  - Reader access to ML workspaces and reservations

## Setup Instructions

### Step 1: Create the Azure Function App

First, create the Function App in Azure (if not already created):

```bash
# Set variables
SUBSCRIPTION_ID="your-subscription-id"
RESOURCE_GROUP="your-resource-group"
LOCATION="eastus2"
FUNCTION_APP_NAME="ptu-ri-alert"
STORAGE_ACCOUNT="yourptualertstorage"

# Create storage account (if needed)
az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS

# Create Function App (Flex Consumption)
az functionapp create \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --storage-account $STORAGE_ACCOUNT \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux
```

### Step 2: Configure Function App Settings

Set the required app settings for Python V2 programming model:

```bash
# Enable worker indexing (required for Python V2 model)
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings AzureWebJobsFeatureFlags=EnableWorkerIndexing
```

**Note**: For Flex Consumption plans, do NOT set `FUNCTIONS_WORKER_RUNTIME` as it's managed automatically.

### Step 3: Enable Managed Identity and Assign Permissions

**Critical**: The function requires a managed identity with proper permissions to access Azure resources.

#### Option A: Use the automated setup script (Recommended)

The `setup-event-grid.sh` script handles everything:

```bash
cd event-grid
chmod +x setup-event-grid.sh
./setup-event-grid.sh
```

This will:
1. Enable system-assigned managed identity on the function
2. Assign the Reader role at subscription level
3. Create the Event Grid system topic
4. Create the event subscription with proper filters

#### Option B: Manual setup

If you prefer to set up permissions manually:

```bash
# Enable system-assigned managed identity
az functionapp identity assign \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP

# Get the managed identity Principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId \
  --output tsv)

# Assign Reader role at subscription level
# This provides access to:
#   - Read CognitiveServices/AI Foundry deployments
#   - Read Azure Reservations
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"

# Wait for permissions to propagate (15-30 seconds)
sleep 15
```

**Why Reader role?**
- Access to read CognitiveServices account deployments (AI Foundry models)
- Access to query Azure Reservations API
- Least-privilege principle - no write permissions needed

### Step 4: Deploy the Function

Install dependencies and deploy the function:

```bash
cd function-app

# Deploy to Azure
func azure functionapp publish $FUNCTION_APP_NAME
```

Verify the function was deployed successfully:

```bash
az functionapp function list \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[].{Name:name, TriggerType:config.bindings[0].type}" \
  --output table
```

You should see:
```
Name                      TriggerType
------------------------  ---------------
ptu-ri-alert-function     eventGridTrigger
```

### Step 4: Deploy the Function

Install dependencies and deploy the function:

```bash
cd function-app

# Deploy to Azure
func azure functionapp publish $FUNCTION_APP_NAME
```

Verify the function was deployed successfully:

```bash
az functionapp function list \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "[].{Name:name, TriggerType:config.bindings[0].type}" \
  --output table
```

You should see:
```
Name                      TriggerType
------------------------  ---------------
ptu-ri-alert-function     eventGridTrigger
```

### Step 5: Create Event Grid System Topic and Subscription

**Important**: Run Step 3 (identity setup) BEFORE this step. The function must have proper permissions for the monitoring to work.

If you used the automated script in Step 3, Event Grid is already configured. Otherwise, update and run:

```bash
cd event-grid
chmod +x setup-event-grid.sh
# Edit the script to update configuration variables
./setup-event-grid.sh
```

Verify the Event Grid subscription was created:

```bash
az eventgrid system-topic event-subscription show \
  --name NewAIFoundryDeploymentSubscription \
  --resource-group $RESOURCE_GROUP \
  --system-topic-name AIFoundryDeploymentTopic
```

## How It Works

1. **Deployment Event**: When you create/update an AI Foundry model deployment, Azure emits a resource event
2. **Event Grid Filtering**: The system topic captures subscription-level events and filters for:
   - `Microsoft.CognitiveServices/accounts/deployments/write` (AI Foundry/OpenAI deployments)
   - Status: `Succeeded`
3. **Function Trigger**: The Azure Function receives the filtered event
4. **PTU Scanning**: Function uses managed identity to:
   - Read all deployments in the CognitiveServices account
   - Identify deployments with PTU capacity (SkuName starts with "Provisioned")
   - Sum total deployed PTUs
5. **Reservation Check**: Query Azure Reservations API for PTU reservations
6. **Report**: Log comparison results showing:
   - Total deployed PTUs across all models
   - Total reserved PTUs
   - Coverage status (fully covered / exceeds capacity / no reservations)

## Viewing Function Logs

### Azure Portal (Recommended)

1. Navigate to your Function App in Azure Portal
2. Go to **Functions** → **ptu-ri-alert-function** → **Monitor**
3. Click on any recent invocation to see detailed logs
4. Look for the PTU capacity report in the logs

### Application Insights Query

If Application Insights is enabled:

```kusto
traces
| where timestamp > ago(1h)
| where message contains "PTU" or message contains "deployment"
| order by timestamp desc
| project timestamp, message, severityLevel
```

### CLI (Metrics)

Check function execution metrics:

```bash
# Check if function was triggered
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP_NAME" \
  --metric "OnDemandFunctionExecutionCount" \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table

# Check Event Grid delivery metrics
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.EventGrid/systemTopics/AIFoundryDeploymentTopic" \
  --metric "MatchedEventCount,DeliverySuccessCount" \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table
```

## Testing

### Production Testing

Create or update a deployment in your Azure AI Foundry project:

```bash
# Example: Create a deployment
az cognitiveservices account deployment create \
  --resource-group $RESOURCE_GROUP \
  --name your-ai-foundry-resource \
  --deployment-name test-gpt4 \
  --model-name gpt-4 \
  --model-version "0125-Preview" \
  --model-format OpenAI \
  --sku-capacity 100 \
  --sku-name "ProvisionedManaged"
```

The function will automatically be triggered. Check the logs in Azure Portal (see "Viewing Function Logs" section above).

### Expected Log Output

When a deployment is created, you should see logs similar to:

```
================================================================================
🚨 NEW AI FOUNDRY DEPLOYMENT EVENT
================================================================================
Deployment: test-gpt4
Account: your-ai-foundry-resource
Resource Group: your-rg
Event Type: Microsoft.Resources.ResourceWriteSuccess

================================================================================
📊 PTU CAPACITY CHECK
================================================================================
🔍 Scanning deployments in account: your-ai-foundry-resource

Found deployment: test-gpt4
  Model: gpt-4
  SKU: ProvisionedManaged
  Capacity: 100 PTUs

📊 Total Deployed PTUs: 100
💰 Total Reserved PTUs: 200

✅ Deployed capacity (100 PTUs) is within reserved capacity (200 PTUs)
   Remaining reservation: 100 PTUs
```

### Local Testing (Optional)

Run the function locally:

```bash
cd function-app
func start
```

In another terminal, send a test Event Grid event:

```bash
curl -X POST http://localhost:7071/runtime/webhooks/EventGrid?functionName=ptu-ri-alert-function \
  -H "Content-Type: application/json" \
  -H "aeg-event-type: Notification" \
  -d '[
    {
      "id": "test-id",
      "eventType": "Microsoft.Resources.ResourceWriteSuccess",
      "subject": "/subscriptions/YOUR_SUB_ID/resourceGroups/YOUR_RG/providers/Microsoft.CognitiveServices/accounts/YOUR_ACCOUNT/deployments/test-deployment",
      "eventTime": "2025-10-27T12:00:00Z",
      "data": {
        "operationName": "Microsoft.CognitiveServices/accounts/deployments/write",
        "status": "Succeeded"
      },
      "dataVersion": "1.0",
      "metadataVersion": "1",
      "topic": "/subscriptions/YOUR_SUB_ID"
    }
  ]'
```

## Troubleshooting

### Authentication Errors

If you see `DefaultAzureCredential failed to retrieve a token`:

1. **Verify managed identity is enabled**:
   ```bash
   az functionapp identity show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP
   ```

2. **Verify role assignments**:
   ```bash
   PRINCIPAL_ID=$(az functionapp identity show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --query principalId -o tsv)
   az role assignment list --assignee $PRINCIPAL_ID --output table
   ```
   
   You should see the "Reader" role at subscription level.

3. **Wait for permissions to propagate**: It can take 15-30 seconds for role assignments to take effect. Redeploy if needed:
   ```bash
   cd function-app
   func azure functionapp publish $FUNCTION_APP_NAME
   ```

### Event Not Captured

If deployments don't trigger the function:

1. **Check Event Grid metrics**:
   ```bash
   az monitor metrics list \
     --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.EventGrid/systemTopics/AIFoundryDeploymentTopic" \
     --metric "MatchedEventCount,DeliverySuccessCount,DeliveryAttemptFailCount" \
     --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
     --interval PT5M \
     --output table
   ```

2. **Verify event subscription filters**:
   ```bash
   az eventgrid system-topic event-subscription show \
     --name NewAIFoundryDeploymentSubscription \
     --resource-group $RESOURCE_GROUP \
     --system-topic-name AIFoundryDeploymentTopic \
     --query "{SubjectBeginsWith:filter.subjectBeginsWith, AdvancedFilters:filter.advancedFilters}"
   ```

3. **Check function execution count**:
   ```bash
   az monitor metrics list \
     --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP_NAME" \
     --metric "OnDemandFunctionExecutionCount" \
     --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
     --interval PT5M \
     --output table
   ```

### Function Execution Failures

Check the function logs in Azure Portal → Function App → Functions → ptu-ri-alert-function → Monitor

Common issues:
- Missing managed identity (see Authentication Errors above)
- Invalid CognitiveServices account name in the event
- Network connectivity issues

## Architecture Details

### Event Flow

```
================================================================================
📊 PTU CAPACITY vs RESERVATIONS REPORT
================================================================================
Total PTU Deployments: 3
Total PTU Capacity Allocated: 150
Total PTU Reservations: 200
Reservation Utilization: 75.0%

✅ Under-utilized: 50 PTUs available

Deployment Details:
  - project-1/gpt-4-deployment: 100 PTUs (gpt-4)
  - project-2/gpt-35-turbo: 30 PTUs (gpt-35-turbo)
  - project-3/gpt-4-turbo: 20 PTUs (gpt-4-turbo)

Reservation Details:
  - OpenAI PTU Reservation: 200 units
================================================================================
```

## Project Structure

```
ptu-ri-alert/
├── README.md
├── pyproject.toml
├── function-app/
│   ├── function_app.py          # Main function code (Python V2 model)
│   ├── requirements.txt          # Python dependencies
│   ├── host.json                # Function host configuration
│   ├── local.settings.json      # Local development settings
│   └── .funcignore              # Files to exclude from deployment
└── event-grid/
    └── setup-event-grid.sh      # Event Grid setup script
```

## Important Notes

- **File Naming**: The function code must be in `function_app.py` (not `__init__.py`) for Python V2 programming model
- **Deployment Order**: Deploy the function BEFORE creating the Event Grid subscription
- **Flex Consumption**: If using Flex Consumption plan, do not manually set `FUNCTIONS_WORKER_RUNTIME`
- **Worker Indexing**: `AzureWebJobsFeatureFlags=EnableWorkerIndexing` is required for Python V2 model
- **Permissions**: The function's managed identity needs Reader access to workspaces and reservations

## Troubleshooting

### Function not appearing after deployment

1. Verify the file is named `function_app.py` (not `__init__.py`)
2. Check that `AzureWebJobsFeatureFlags=EnableWorkerIndexing` is set
3. Restart the function app: `az functionapp restart --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP`
4. Redeploy: `func azure functionapp publish $FUNCTION_APP_NAME`

### Event Grid subscription creation fails

1. Ensure the function is deployed and visible
2. Verify the function name matches exactly: `ptu-ri-alert-function`
3. Check that the AI project name is correct
4. Run the setup script again after fixing configuration

### Function receives events but can't check PTU capacity

1. Verify managed identity is enabled on the function app
2. Check that Reader role is assigned at subscription level
3. Verify Reservation Reader role if checking reservations
4. Check function logs for detailed error messages

## Permissions Reference

### Required Permissions for Full Functionality

The function requires different permissions depending on what resources it needs to access:

#### 1. Reading CognitiveServices Deployments ✅ (Required)

**Role:** Reader  
**Scope:** Subscription level  
**Purpose:** Read AI Foundry/CognitiveServices account deployments to scan PTU capacity

```bash
PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reader" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"
```

**Permissions granted:**
- `Microsoft.CognitiveServices/accounts/read`
- `Microsoft.CognitiveServices/accounts/deployments/read`

**What happens without this:**
```
❌ Error: DefaultAzureCredential failed to retrieve a token
   or
❌ Error: (AuthorizationFailed) does not have authorization to perform action 
   'Microsoft.CognitiveServices/accounts/deployments/read'
```

#### 2. Reading Azure Reservations 📊 (Optional, for reservation tracking)

**Role:** Reservations Reader  
**Scope:** Tenant level (`/providers/Microsoft.Capacity`)  
**Purpose:** Query PTU reservations to compare against deployed capacity

```bash
# Requires tenant-level admin permissions
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Reservations Reader" \
  --scope "/providers/Microsoft.Capacity"
```

**Permissions granted:**
- `Microsoft.Capacity/reservationOrders/read`
- `Microsoft.Capacity/reservations/read`

**What happens without this:**
```
⚠️  Could not query reservations: (AuthorizationFailed) 
    The client does not have authorization to perform action 
    'Microsoft.Capacity/reservationOrders/read' over scope '/providers/Microsoft.Capacity'
💰 Total reserved PTUs in subscription: 0
```

**Note:** The function will still work without this permission, but it won't be able to compare deployed PTUs against your reservations. It will simply report the total deployed PTUs.

#### 3. Permission Propagation Time

After assigning roles, permissions can take **15-30 seconds** to propagate. If you see authentication errors immediately after role assignment:

1. Wait 30 seconds
2. Redeploy the function or trigger a new deployment event
3. Check the function logs again

### Verification Commands

Check current role assignments:
```bash
PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

echo "Principal ID: $PRINCIPAL_ID"
echo ""
echo "Role Assignments:"
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --query "[].{Role:roleDefinitionName, Scope:scope}" \
  --output table
```

Expected output:
```
Role                  Scope
--------------------  -----------------------------------------------------
Reader                /subscriptions/547b3a70-abb4-425f-9a55-c1a14d50e8a1
Reservations Reader   /providers/Microsoft.Capacity
```

## Testing and Verification Guide

### Step 1: Create a Test Deployment

Create a new deployment to trigger the monitoring function:

```bash
# For PTU-based deployment (will show in capacity report):
az cognitiveservices account deployment create \
  --resource-group $RESOURCE_GROUP \
  --name your-ai-foundry-resource \
  --deployment-name test-ptu-gpt4 \
  --model-name gpt-4 \
  --model-version "0125-Preview" \
  --model-format OpenAI \
  --sku-capacity 100 \
  --sku-name "ProvisionedManaged"

# For PAYG deployment (will show 0 PTUs):
az cognitiveservices account deployment create \
  --resource-group $RESOURCE_GROUP \
  --name your-ai-foundry-resource \
  --deployment-name test-payg-gpt4 \
  --model-name gpt-4 \
  --model-version "0125-Preview" \
  --model-format OpenAI \
  --sku-capacity 1000 \
  --sku-name "GlobalStandard"
```

**Note:** Only deployments with SKU names starting with **"Provisioned"** (e.g., `ProvisionedManaged`) use PTUs. Other SKUs like `Standard`, `GlobalStandard` are pay-as-you-go (PAYG) and use tokens-per-minute (TPM).

### Step 2: Verify Event Grid Captured the Event

Wait ~30-60 seconds after deployment, then check Event Grid metrics:

```bash
# Check if event was matched
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.EventGrid/systemTopics/AIFoundryDeploymentTopic" \
  --metric "MatchedEventCount" \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table | grep -v "0.0"
```

**Expected output:**
```
Timestamp             Name            Total
--------------------  --------------  -------
2025-10-28T00:31:00Z  Matched Events  1.0
```

If you see **no matched events**, check:
- Deployment was in the correct resource group
- Event subscription filters are correct
- Deployment operation succeeded

### Step 3: Verify Event Was Delivered Successfully

Check if Event Grid successfully delivered the event to the function:

```bash
# Check delivery status
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.EventGrid/systemTopics/AIFoundryDeploymentTopic" \
  --metric "DeliverySuccessCount,DeliveryAttemptFailCount" \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table | grep -v "0.0"
```

**Expected output (success):**
```
Timestamp             Name                        Total
--------------------  --------------------------  -------
2025-10-28T00:31:00Z  Delivery Succeeded Events   1.0
```

**If you see delivery failures:**
```
Timestamp             Name                    Total
--------------------  ----------------------  -------
2025-10-28T00:31:00Z  Delivery Failed Events  3.0
```

This means Event Grid tried to deliver but failed. Common causes:
- Function endpoint not accessible
- Function authentication issues
- Event Grid will automatically retry (up to 30 times over 24 hours)

### Step 4: Verify Function Was Executed

Check if the function actually ran:

```bash
# Check function execution count
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP_NAME" \
  --metric "OnDemandFunctionExecutionCount" \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table | grep -v "0.0"
```

**Expected output:**
```
Timestamp             Name                                Total
--------------------  ----------------------------------  -------
2025-10-28T00:31:00Z  On Demand Function Execution Count  1.0
```

Multiple executions (e.g., 2-3) can appear if Event Grid retried delivery.

### Step 5: Check Deployment SKU Type

Verify if your deployment uses PTUs or PAYG:

```bash
# Check specific deployment
az cognitiveservices account deployment show \
  --resource-group $RESOURCE_GROUP \
  --name your-ai-foundry-resource \
  --deployment-name your-deployment-name \
  --query "{Name:name, Model:properties.model.name, Sku:sku.name, Capacity:sku.capacity}" \
  --output table

# List all deployments
az cognitiveservices account deployment list \
  --resource-group $RESOURCE_GROUP \
  --name your-ai-foundry-resource \
  --query "[].{Name:name, Model:properties.model.name, Sku:sku.name, Capacity:sku.capacity}" \
  --output table
```

**Output interpretation:**
```
Name        Model    Sku                 Capacity    Type
----------  -------  ------------------  ----------  ----
gpt-4-ptu   gpt-4    ProvisionedManaged  100         PTU ✅
gpt-4-payg  gpt-4    GlobalStandard      5000        TPM (PAYG) ❌
```

- **ProvisionedManaged**, **Provisioned** = PTU-based (will be counted)
- **GlobalStandard**, **Standard** = Pay-as-you-go (will show 0 PTUs)

### Step 6: View Function Logs and PTU Report

Go to Azure Portal to see the detailed PTU capacity report:

1. Navigate to: **Function App** → **ptu-ri-alert** → **Functions** → **ptu-ri-alert-function** → **Monitor**
2. Click on the most recent invocation (timestamp should match your deployment time)
3. View the logs

**Expected log output for PTU deployment:**
```
================================================================================
🚨 NEW AI FOUNDRY DEPLOYMENT EVENT
================================================================================
Deployment: test-ptu-gpt4
Account: your-ai-foundry-resource
Resource Group: your-rg

================================================================================
📊 PTU CAPACITY CHECK
================================================================================
🔍 Scanning deployments in account: your-ai-foundry-resource

Found deployment: test-ptu-gpt4
  Model: gpt-4
  SKU: ProvisionedManaged
  Capacity: 100 PTUs

📈 Total deployed PTUs in this account: 100

🔍 Checking PTU reservations in subscription...
💰 Total reserved PTUs in subscription: 0

================================================================================
📊 CAPACITY vs RESERVATIONS REPORT
================================================================================
⚠️  NO RESERVATIONS FOUND!
   All 100 deployed PTUs will be billed hourly
   Consider purchasing reservations for cost savings
```

**Expected log output for PAYG deployment:**
```
📈 Total deployed PTUs in this account: 0
💰 Total reserved PTUs in subscription: 0

⚠️  NO RESERVATIONS FOUND!
   All 0 deployed PTUs will be billed hourly
```

### Complete End-to-End Test Script

Here's a complete bash script to test everything:

```bash
#!/bin/bash

# Configuration
SUBSCRIPTION_ID="your-subscription-id"
RESOURCE_GROUP="your-resource-group"
FUNCTION_APP_NAME="ptu-ri-alert"
AI_RESOURCE_NAME="your-ai-foundry-resource"

echo "=========================================="
echo "PTU RI Alert - End-to-End Test"
echo "=========================================="
echo ""

echo "Step 1: Create test deployment..."
DEPLOYMENT_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "Deployment time: $DEPLOYMENT_TIME"

# Create a test deployment (you can comment this out if you don't want to create a new deployment)
# az cognitiveservices account deployment create \
#   --resource-group $RESOURCE_GROUP \
#   --name $AI_RESOURCE_NAME \
#   --deployment-name test-e2e-$(date +%s) \
#   --model-name gpt-4 \
#   --model-version "0125-Preview" \
#   --model-format OpenAI \
#   --sku-capacity 100 \
#   --sku-name "ProvisionedManaged"

echo ""
echo "Waiting 60 seconds for event propagation..."
sleep 60

echo ""
echo "Step 2: Check Event Grid metrics..."
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.EventGrid/systemTopics/AIFoundryDeploymentTopic" \
  --metric "MatchedEventCount" \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table | tail -10

echo ""
echo "Step 3: Check function execution..."
az monitor metrics list \
  --resource "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP_NAME" \
  --metric "OnDemandFunctionExecutionCount" \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --interval PT1M \
  --output table | tail -10

echo ""
echo "Step 4: Check all deployments..."
az cognitiveservices account deployment list \
  --resource-group $RESOURCE_GROUP \
  --name $AI_RESOURCE_NAME \
  --query "[].{Name:name, Model:properties.model.name, Sku:sku.name, Capacity:sku.capacity, PTU:sku.name}" \
  --output table

echo ""
echo "=========================================="
echo "✅ Test complete!"
echo "=========================================="
echo ""
echo "Next: Check function logs in Azure Portal for detailed PTU report"
echo "Portal URL: https://portal.azure.com/#@/resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Web/sites/$FUNCTION_APP_NAME/functions"
```

Save this as `test-ptu-alert.sh`, update the variables, and run:
```bash
chmod +x test-ptu-alert.sh
./test-ptu-alert.sh
```