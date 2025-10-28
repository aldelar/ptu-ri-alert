import json
import logging
import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.reservations import AzureReservationAPI

app = func.FunctionApp()

@app.function_name(name="ptu-ri-alert-function")
@app.event_grid_trigger(arg_name="event")
def ptu_ri_alert_function(event: func.EventGridEvent):
    """
    Azure Function to monitor AI deployment events and check PTU capacity vs reservations.
    """
    logging.info('=' * 80)
    logging.info('🎯 Event Grid trigger function activated!')
    logging.info('=' * 80)
    
    # Parse the event data
    event_data = event.get_json()
    
    # Log all event properties
    logging.info(f"📋 Event ID: {event.id}")
    logging.info(f"📋 Event Type: {event.event_type}")
    logging.info(f"📋 Event Subject: {event.subject}")
    logging.info(f"📋 Event Time: {event.event_time}")
    
    # Extract and log specific data fields
    operation_name = event_data.get('operationName', 'N/A')
    status = event_data.get('status', 'N/A')
    
    logging.info(f"⚙️  Operation: {operation_name}")
    logging.info(f"✅ Status: {status}")
    
    # Check if this is a CognitiveServices deployment event
    if 'Microsoft.CognitiveServices/accounts' in event.subject and 'deployments/write' in operation_name:
        logging.warning('🚨 AI deployment detected!')
        logging.warning(f'   Resource: {event.subject}')
        
        try:
            # Parse the subject to extract details
            parts = event.subject.split('/')
            subscription_id = parts[2]
            resource_group = parts[4]
            account_name = parts[8]
            deployment_name = parts[10] if len(parts) > 10 else 'unknown'
            
            logging.info(f"📍 Subscription: {subscription_id}")
            logging.info(f"📍 Resource Group: {resource_group}")
            logging.info(f"� Account: {account_name}")
            logging.info(f"📍 Deployment: {deployment_name}")
            
            # Check PTU capacity vs reservations
            check_ptu_capacity(subscription_id, resource_group, account_name, deployment_name)
            
        except Exception as e:
            logging.error(f"❌ Error processing deployment event: {str(e)}")
            logging.exception(e)
    else:
        logging.info('ℹ️  Non-deployment event, skipping PTU check')
    
    logging.info('=' * 80)
    logging.info('✅ Event processing complete')
    logging.info('=' * 80)
    
    return {
        'status': 'success',
        'event_id': event.id,
        'event_type': event.event_type
    }


def check_ptu_capacity(subscription_id: str, resource_group: str, account_name: str, deployment_name: str):
    """
    Check PTU capacity across all deployments and compare with reservations.
    """
    logging.info('=' * 80)
    logging.info('📊 PTU CAPACITY CHECK')
    logging.info('=' * 80)
    
    try:
        credential = DefaultAzureCredential()
        
        # Step 1: Get total deployed PTUs from all deployments in this account
        logging.info(f"🔍 Scanning deployments in account: {account_name}")
        cog_client = CognitiveServicesManagementClient(credential, subscription_id)
        
        total_deployed_ptus = 0
        new_deployment_ptus = 0
        deployment_details = []
        
        deployments = cog_client.deployments.list(resource_group, account_name)
        for dep in deployments:
            if dep.sku and dep.sku.name and dep.sku.name.lower().startswith('provisioned'):
                capacity = dep.sku.capacity or 0
                total_deployed_ptus += capacity
                deployment_details.append(f"  - {dep.name}: {capacity} PTUs ({dep.sku.name})")
                
                if dep.name == deployment_name:
                    new_deployment_ptus = capacity
                    logging.warning(f"⭐ New deployment '{deployment_name}': {capacity} PTUs")
        
        logging.info(f"📈 Total deployed PTUs in this account: {total_deployed_ptus}")
        if deployment_details:
            logging.info("Deployment breakdown:")
            for detail in deployment_details:
                logging.info(detail)
        
        # Step 2: Get total reserved PTUs
        logging.info(f"🔍 Checking PTU reservations in subscription...")
        total_reserved_ptus = 0
        reservation_details = []
        
        try:
            reservation_client = AzureReservationAPI(credential)
            
            # List all reservation orders
            for order in reservation_client.reservation_order.list():
                for reservation in reservation_client.reservation.list(order.name):
                    # Check if this is a PTU reservation
                    if reservation.sku_description and 'Provisioned Throughput' in reservation.sku_description:
                        quantity = reservation.quantity or 0
                        total_reserved_ptus += quantity
                        reservation_details.append(f"  - {reservation.display_name or reservation.name}: {quantity} PTUs ({reservation.provisioning_state})")
                        
        except Exception as e:
            logging.warning(f"⚠️  Could not query reservations: {str(e)}")
            logging.warning("Note: Reservation data may be delayed up to 24 hours after purchase")
        
        logging.info(f"💰 Total reserved PTUs in subscription: {total_reserved_ptus}")
        if reservation_details:
            logging.info("Reservation breakdown:")
            for detail in reservation_details:
                logging.info(detail)
        
        # Step 3: Compare and report
        logging.info('=' * 80)
        logging.info('📊 CAPACITY vs RESERVATIONS REPORT')
        logging.info('=' * 80)
        
        if total_reserved_ptus == 0:
            logging.warning(f"⚠️  NO RESERVATIONS FOUND!")
            logging.warning(f"   All {total_deployed_ptus} deployed PTUs will be billed hourly")
            logging.warning(f"   Consider purchasing reservations for cost savings")
        elif total_deployed_ptus <= total_reserved_ptus:
            available = total_reserved_ptus - total_deployed_ptus
            logging.info(f"✅ FULLY COVERED by reservations")
            logging.info(f"   Deployed: {total_deployed_ptus} PTUs")
            logging.info(f"   Reserved: {total_reserved_ptus} PTUs")
            logging.info(f"   Available: {available} PTUs")
            logging.info(f"   New deployment '{deployment_name}' ({new_deployment_ptus} PTUs) is covered")
        else:
            excess = total_deployed_ptus - total_reserved_ptus
            logging.error(f"❌ EXCEEDS RESERVATIONS!")
            logging.error(f"   Deployed: {total_deployed_ptus} PTUs")
            logging.error(f"   Reserved: {total_reserved_ptus} PTUs")
            logging.error(f"   EXCESS: {excess} PTUs (will be billed hourly)")
            if new_deployment_ptus > 0:
                logging.error(f"   New deployment '{deployment_name}' ({new_deployment_ptus} PTUs) may be partially/fully billed hourly")
            logging.error(f"   ⚠️  Consider purchasing additional {excess} PTU reservations!")
        
        logging.info('=' * 80)
        
    except Exception as e:
        logging.error(f"❌ Error checking PTU capacity: {str(e)}")
        logging.exception(e)
