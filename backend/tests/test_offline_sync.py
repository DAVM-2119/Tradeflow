import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, Role, ShipperProfile, TransporterProfile, DriverProfile, VerificationStatus
from apps.marketplace.models import (
    Vehicle,
    VehicleType,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
    LocationUpdate,
    ShipmentMilestone,
    OfflineSyncEventType,
    OfflineSyncStatus,
    OfflineSyncEvent,
    IncidentType,
    DriverIncidentReport,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def setup_offline_sync_data(db):
    # Shipper
    shipper_user = User.objects.create_user(
        email='shipper_sync@tradeflow.et',
        password='Password123!',
        first_name='Abebe',
        last_name='Bikila',
        role=Role.SHIPPER,
        phone_number='+251911111199'
    )
    shipper_profile = ShipperProfile.objects.create(
        user=shipper_user,
        company_name='Mojo Import Export'
    )

    # Transporter User & Profile
    transporter_user = User.objects.create_user(
        email='transporter_sync@tradeflow.et',
        password='Password123!',
        first_name='Derartu',
        last_name='Tulu',
        role=Role.TRANSPORTER,
        phone_number='+251922222299'
    )
    transporter_profile = TransporterProfile.objects.create(
        user=transporter_user,
        company_name='Red Sea Transport',
        trade_license_number='TL-SYNC-999',
        tax_id='TIN-SYNC-999',
        verification_status=VerificationStatus.VERIFIED
    )

    # Driver User & Profile
    driver_user = User.objects.create_user(
        email='driver_sync@tradeflow.et',
        password='Password123!',
        first_name='Haile',
        last_name='Gebrselassie',
        role=Role.DRIVER,
        phone_number='+251933333399'
    )
    driver_profile = DriverProfile.objects.create(
        user=driver_user,
        transporter=transporter_profile,
        license_number='DL-SYNC-999',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )

    # Unassigned Driver User
    other_driver_user = User.objects.create_user(
        email='other_driver@tradeflow.et',
        password='Password123!',
        first_name='Tilahun',
        last_name='Gessesse',
        role=Role.DRIVER,
        phone_number='+251944444499'
    )
    other_driver_profile = DriverProfile.objects.create(
        user=other_driver_user,
        transporter=transporter_profile,
        license_number='DL-SYNC-888',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )

    # Vehicle
    vehicle = Vehicle.objects.create(
        transporter=transporter_profile,
        plate_number='ET-SYNC-999',
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=Decimal('40.00')
    )

    # CargoLoad
    load = CargoLoad.objects.create(
        shipper=shipper_profile,
        title='Coffee Container Transport',
        origin='Addis Ababa Dry Port',
        destination='Djibouti Port',
        cargo_type='Export Coffee',
        weight_tonnes=Decimal('28.50'),
        required_vehicle_type=VehicleType.FLATBED,
        pickup_date=timezone.now().date(),
        delivery_date=timezone.now().date() + timedelta(days=3),
        target_price=Decimal('120000.00'),
        status=LoadStatus.ASSIGNED,
        assigned_transporter=transporter_profile,
        assigned_vehicle=vehicle
    )

    # Shipment
    shipment = Shipment.objects.create(
        tracking_number='TRK-SYNC-99999',
        load=load,
        transporter=transporter_profile,
        vehicle=vehicle,
        driver=driver_profile,
        origin=load.origin,
        destination=load.destination,
        status=ShipmentStatus.IN_TRANSIT
    )

    return {
        'shipper_user': shipper_user,
        'transporter_user': transporter_user,
        'driver_user': driver_user,
        'driver_profile': driver_profile,
        'other_driver_user': other_driver_user,
        'shipment': shipment,
    }


@pytest.mark.django_db
def test_authenticated_driver_sync_gps_event(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    client_event_id = 'EVT-UUID-GPS-001'
    client_dt = (timezone.now() - timedelta(minutes=15)).isoformat()

    payload = {
        'device_id': 'MOB-DEV-01',
        'events': [
            {
                'client_event_id': client_event_id,
                'event_type': 'GPS_UPDATE',
                'shipment_id': shipment.id,
                'client_created_at': client_dt,
                'payload': {
                    'latitude': 8.9806,
                    'longitude': 38.7578,
                    'speed_kmh': 55.0,
                    'location_name': 'Mojo Toll Road Gate'
                }
            }
        ]
    }

    response = api_client.post('/api/v1/sync/events/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.data

    assert data['synced_count'] == 1
    assert data['results'][0]['client_event_id'] == client_event_id
    assert data['results'][0]['status'] == OfflineSyncStatus.SYNCED

    # Verify DB persistence
    assert OfflineSyncEvent.objects.filter(client_event_id=client_event_id).exists()
    assert LocationUpdate.objects.filter(shipment=shipment, latitude=Decimal('8.9806')).exists()


@pytest.mark.django_db
def test_unauthenticated_user_cannot_sync(api_client, setup_offline_sync_data):
    shipment = setup_offline_sync_data['shipment']
    payload = {
        'events': [
            {
                'client_event_id': 'EVT-UNAUTH-001',
                'event_type': 'GPS_UPDATE',
                'shipment_id': shipment.id,
                'client_created_at': timezone.now().isoformat(),
                'payload': {'latitude': 8.9806, 'longitude': 38.7578}
            }
        ]
    }
    response = api_client.post('/api/v1/sync/events/', payload, format='json')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_unassigned_driver_cannot_sync_event(api_client, setup_offline_sync_data):
    other_driver = setup_offline_sync_data['other_driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=other_driver)

    client_event_id = 'EVT-FORBIDDEN-001'
    payload = {
        'events': [
            {
                'client_event_id': client_event_id,
                'event_type': 'GPS_UPDATE',
                'shipment_id': shipment.id,
                'client_created_at': timezone.now().isoformat(),
                'payload': {'latitude': 8.9806, 'longitude': 38.7578}
            }
        ]
    }

    response = api_client.post('/api/v1/sync/events/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    assert response.data['failed_count'] == 1
    assert response.data['results'][0]['status'] == OfflineSyncStatus.FAILED
    assert "not an assigned driver" in response.data['results'][0]['message']


@pytest.mark.django_db
def test_invalid_coordinates_rejected(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    payload = {
        'events': [
            {
                'client_event_id': 'EVT-BAD-LAT-001',
                'event_type': 'GPS_UPDATE',
                'shipment_id': shipment.id,
                'client_created_at': timezone.now().isoformat(),
                'payload': {'latitude': 125.0, 'longitude': 38.7578}  # Invalid latitude > 90
            }
        ]
    }

    response = api_client.post('/api/v1/sync/events/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    assert response.data['failed_count'] == 1
    assert response.data['results'][0]['status'] == OfflineSyncStatus.FAILED


@pytest.mark.django_db
def test_idempotency_duplicate_event_handling(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    client_event_id = 'EVT-RETRY-DUP-999'
    event_item = {
        'client_event_id': client_event_id,
        'event_type': 'GPS_UPDATE',
        'shipment_id': shipment.id,
        'client_created_at': timezone.now().isoformat(),
        'payload': {'latitude': 8.5000, 'longitude': 39.2000}
    }

    # First Attempt
    resp1 = api_client.post('/api/v1/sync/events/', {'events': [event_item]}, format='json')
    assert resp1.status_code == status.HTTP_200_OK
    assert resp1.data['synced_count'] == 1
    server_record_id = resp1.data['results'][0]['server_record_id']

    # Retry Attempt with same client_event_id
    resp2 = api_client.post('/api/v1/sync/events/', {'events': [event_item]}, format='json')
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.data['duplicate_count'] == 1
    assert resp2.data['results'][0]['status'] == OfflineSyncStatus.DUPLICATE
    assert resp2.data['results'][0]['server_record_id'] == server_record_id

    # Verify no duplicate LocationUpdate created
    assert LocationUpdate.objects.filter(shipment=shipment, latitude=Decimal('8.5000')).count() == 1


@pytest.mark.django_db
def test_batch_sync_multiple_events(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    now_iso = timezone.now().isoformat()

    events = [
        {
            'client_event_id': 'BATCH-EVT-01',
            'event_type': 'GPS_UPDATE',
            'shipment_id': shipment.id,
            'client_created_at': now_iso,
            'payload': {'latitude': 8.6000, 'longitude': 39.3000}
        },
        {
            'client_event_id': 'BATCH-EVT-02',
            'event_type': 'WAYPOINT_CHECKIN',
            'shipment_id': shipment.id,
            'client_created_at': now_iso,
            'payload': {'status': 'IN_TRANSIT', 'location_name': 'Adama Highway Station'}
        },
        {
            'client_event_id': 'BATCH-EVT-03',
            'event_type': 'INCIDENT_REPORT',
            'shipment_id': shipment.id,
            'client_created_at': now_iso,
            'payload': {
                'incident_type': 'CHECKPOINT_DELAY',
                'description': '30-minute customs clearance delay at Mojo Checkpoint',
                'location_name': 'Mojo Gate'
            }
        }
    ]

    response = api_client.post('/api/v1/sync/events/', {'events': events}, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.data

    assert data['total_events'] == 3
    assert data['synced_count'] == 3
    assert data['failed_count'] == 0

    # Verify incident report creation in DB
    assert DriverIncidentReport.objects.filter(shipment=shipment, incident_type=IncidentType.CHECKPOINT_DELAY).exists()


@pytest.mark.django_db
def test_batch_sync_partial_failure_isolation(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    events = [
        {
            'client_event_id': 'ISOLATE-VALID-01',
            'event_type': 'GPS_UPDATE',
            'shipment_id': shipment.id,
            'client_created_at': timezone.now().isoformat(),
            'payload': {'latitude': 8.7000, 'longitude': 39.4000}
        },
        {
            'client_event_id': 'ISOLATE-INVALID-02',
            'event_type': 'GPS_UPDATE',
            'shipment_id': shipment.id,
            'client_created_at': timezone.now().isoformat(),
            'payload': {'latitude': 999.0, 'longitude': 39.4000}  # Invalid latitude
        }
    ]

    response = api_client.post('/api/v1/sync/events/', {'events': events}, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.data

    assert data['synced_count'] == 1
    assert data['failed_count'] == 1

    # Valid event should be saved in DB
    assert LocationUpdate.objects.filter(shipment=shipment, latitude=Decimal('8.7000')).exists()


@pytest.mark.django_db
def test_incident_report_list_endpoint(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    # First sync an incident report
    event = {
        'client_event_id': 'INCIDENT-QUERY-01',
        'event_type': 'INCIDENT_REPORT',
        'shipment_id': shipment.id,
        'client_created_at': timezone.now().isoformat(),
        'payload': {
            'incident_type': 'FUEL_UNAVAILABLE',
            'description': 'Diesel fuel station out of stock near Awash',
            'location_name': 'Awash Town'
        }
    }
    api_client.post('/api/v1/sync/events/', {'events': [event]}, format='json')

    # Query incident reports list endpoint
    response = api_client.get(f'/api/v1/shipments/{shipment.id}/incidents/')
    assert response.status_code == status.HTTP_200_OK
    data = response.data
    results = data['results'] if isinstance(data, dict) and 'results' in data else data
    assert len(results) == 1
    assert results[0]['incident_type'] == 'FUEL_UNAVAILABLE'
    assert 'Awash Town' in results[0]['location_name']


@pytest.mark.django_db
def test_oversized_batch_rejected(api_client, setup_offline_sync_data):
    driver_user = setup_offline_sync_data['driver_user']
    shipment = setup_offline_sync_data['shipment']
    api_client.force_authenticate(user=driver_user)

    # Create batch of 51 events (> MAX_BATCH_SIZE of 50)
    events = [
        {
            'client_event_id': f'BATCH-OVERSIZED-{i}',
            'event_type': 'GPS_UPDATE',
            'shipment_id': shipment.id,
            'client_created_at': timezone.now().isoformat(),
            'payload': {'latitude': 8.0, 'longitude': 38.0}
        }
        for i in range(51)
    ]

    response = api_client.post('/api/v1/sync/events/', {'events': events}, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
