import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError, PermissionDenied
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from channels.layers import get_channel_layer

from apps.accounts.models import Role, TransporterProfile, DriverProfile, ShipperProfile
from apps.marketplace.models import (
    CargoLoad, LoadStatus, Vehicle, Shipment, ShipmentStatus,
    DriverIncidentReport, IncidentType,
    AutomationRule, AutomationRuleType, RecommendationPriority, RecommendationStatus,
    AutomationRecommendationType, AutomationRecommendation,
    OperationalEvent, OperationalEventType, EventSeverity,
    Notification, NotificationType, NotificationPreference
)
from apps.marketplace.realtime_services import OperationalEventService, NotificationService
from apps.marketplace.realtime_serializers import (
    OperationalEventSerializer, NotificationSerializer, NotificationPreferenceSerializer
)
from apps.marketplace.ws_auth import JWTAuthMiddleware
from apps.marketplace.routing import websocket_urlpatterns

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_phase14@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_phase14@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def shipper_user(db):
    user = User.objects.filter(email="shipper_phase14@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="shipper_phase14@tradeflow.et", password="Password123!", role=Role.SHIPPER)
        ShipperProfile.objects.get_or_create(
            user=user,
            defaults={
                "company_name": "Modjo Imports PLC",
                "trade_license_number": "TL-SHIP-14",
                "tax_id": "TIN-SHIP-14"
            }
        )
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.filter(email="transporter_phase14@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="transporter_phase14@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
        TransporterProfile.objects.get_or_create(
            user=user,
            defaults={
                "company_name": "Abyssinia Transport PLC",
                "trade_license_number": "TL-ABY-14",
                "tax_id": "TIN-ABY-14",
                "verification_status": "VERIFIED"
            }
        )
    return user


@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.filter(email="driver_phase14@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="driver_phase14@tradeflow.et", password="Password123!", role=Role.DRIVER)
        DriverProfile.objects.get_or_create(
            user=user,
            defaults={
                "transporter": transporter_user.transporter_profile,
                "license_number": "DL-ETH-1414"
            }
        )
    return user


@pytest.fixture
def unrelated_user(db):
    user = User.objects.filter(email="unrelated_phase14@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="unrelated_phase14@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user



@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Wheat Import Freight #14",
        origin="Addis Ababa",
        destination="Djibouti Port",
        weight_tonnes=Decimal("25.50"),
        target_price=Decimal("120000.00"),
        pickup_date=timezone.now().date() + timedelta(days=1),
        delivery_date=timezone.now().date() + timedelta(days=3),
        status=LoadStatus.ASSIGNED
    )


    vehicle = Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ETH-1414",
        vehicle_type="FLATBED",
        capacity_tonnes=Decimal("30.00")
    )
    shipment = Shipment.objects.create(
        tracking_number="TRK-20260822-0014-REALTIME",
        load=load,
        transporter=transporter_user.transporter_profile,
        driver=driver_user.driver_profile,
        vehicle=vehicle,
        status=ShipmentStatus.DRIVER_ASSIGNED,
        origin="Addis Ababa",
        destination="Djibouti Port"
    )
    return shipment


@pytest.mark.django_db
class TestOperationalEventModelAndService:
    def test_create_operational_event_success(self, active_shipment, shipper_user):
        event = OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.HIGH,
            shipment=active_shipment,
            actor=shipper_user,
            source='TELEM_ENGINE',
            title='Route Deviation Warning',
            description='Vehicle is 14.5 km from corridor',
            payload={'deviation_km': 14.5}
        )

        assert event.id is not None
        assert event.event_type == OperationalEventType.ROUTE_DEVIATION
        assert event.severity == EventSeverity.HIGH
        assert event.shipment == active_shipment
        assert event.actor == shipper_user
        assert event.payload['deviation_km'] == 14.5
        assert event.idempotency_key.startswith("event:")

    def test_invalid_event_type_validation(self):
        with pytest.raises(ValidationError):
            OperationalEventService.create_event(
                event_type='INVALID_TYPE',
                title='Invalid',
                description='Invalid event type'
            )

    def test_invalid_severity_validation(self):
        with pytest.raises(ValidationError):
            OperationalEventService.create_event(
                event_type=OperationalEventType.SYSTEM_ALERT,
                severity='EXTREME',
                title='Invalid',
                description='Invalid severity'
            )

    def test_event_idempotency_prevents_duplicate_creation(self, active_shipment):
        key = "idempotent-key-unique-14"
        event1 = OperationalEventService.create_event(
            event_type=OperationalEventType.ETA_DELAY,
            severity=EventSeverity.MEDIUM,
            shipment=active_shipment,
            title='ETA Delay',
            description='Predicted arrival delayed by 90 mins',
            idempotency_key=key
        )

        event2 = OperationalEventService.create_event(
            event_type=OperationalEventType.ETA_DELAY,
            severity=EventSeverity.MEDIUM,
            shipment=active_shipment,
            title='ETA Delay Duplicate',
            description='Duplicate attempt',
            idempotency_key=key
        )

        assert event1.id == event2.id
        assert OperationalEvent.objects.filter(idempotency_key=key).count() == 1


@pytest.mark.django_db
class TestNotificationModelAndService:
    def test_recipient_determination_for_shipment_event(self, active_shipment, shipper_user, transporter_user, driver_user, admin_user):
        event = OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.HIGH,
            shipment=active_shipment,
            title='Route Deviation',
            description='Corridor deviation'
        )

        recipients = NotificationService.determine_recipients(event)
        recipient_emails = [r.email for r in recipients]

        assert shipper_user.email in recipient_emails
        assert transporter_user.email in recipient_emails
        assert driver_user.email in recipient_emails
        assert admin_user.email in recipient_emails

    def test_duplicate_notification_prevention(self, active_shipment, shipper_user):
        event = OperationalEventService.create_event(
            event_type=OperationalEventType.FUEL_RISK,
            severity=EventSeverity.MEDIUM,
            shipment=active_shipment,
            title='Fuel Consumption Risk',
            description='Exceeding corridor average'
        )

        notifs1 = NotificationService.create_notifications_for_event(event)
        notifs2 = NotificationService.create_notifications_for_event(event)

        assert len(notifs2) == 0  # Deduplicated

    def test_mark_notification_as_read(self, shipper_user):
        event = OperationalEvent.objects.create(
            event_type=OperationalEventType.SYSTEM_ALERT,
            severity=EventSeverity.LOW,
            title='System Alert',
            description='Routine maintenance',
            idempotency_key='manual-notif-1'
        )
        notif = Notification.objects.create(
            recipient=shipper_user,
            event=event,
            notification_type=NotificationType.SYSTEM_ALERT,
            priority=EventSeverity.LOW,
            title='Maintenance',
            message='Routine check'
        )

        assert notif.is_read is False

        updated_notif = NotificationService.mark_as_read(notif.id, shipper_user)
        assert updated_notif.is_read is True
        assert updated_notif.read_at is not None

    def test_mark_all_as_read(self, shipper_user):
        event1 = OperationalEvent.objects.create(
            event_type=OperationalEventType.SYSTEM_ALERT,
            title='Alert 1',
            description='Message 1',
            idempotency_key='manual-notif-2'
        )
        event2 = OperationalEvent.objects.create(
            event_type=OperationalEventType.SYSTEM_ALERT,
            title='Alert 2',
            description='Message 2',
            idempotency_key='manual-notif-3'
        )
        Notification.objects.create(recipient=shipper_user, event=event1, notification_type=NotificationType.SYSTEM_ALERT, title='A', message='A')
        Notification.objects.create(recipient=shipper_user, event=event2, notification_type=NotificationType.SYSTEM_ALERT, title='B', message='B')

        count = NotificationService.mark_all_as_read(shipper_user)
        assert count == 2
        assert Notification.objects.filter(recipient=shipper_user, is_read=False).count() == 0

    def test_acknowledge_critical_notification(self, shipper_user):
        event = OperationalEvent.objects.create(
            event_type=OperationalEventType.HIGH_OPERATIONAL_RISK,
            severity=EventSeverity.CRITICAL,
            title='Critical Operational Risk',
            description='Risk score 95/100',
            idempotency_key='manual-notif-4'
        )
        notif = Notification.objects.create(
            recipient=shipper_user,
            event=event,
            notification_type=NotificationType.RISK_ALERT,
            priority=EventSeverity.CRITICAL,
            title='Critical Risk',
            message='Risk score 95/100'
        )

        assert notif.is_acknowledged is False

        ack_notif = NotificationService.acknowledge_notification(notif.id, shipper_user)
        assert ack_notif.is_acknowledged is True
        assert ack_notif.acknowledged_at is not None
        assert ack_notif.is_read is True

    def test_unread_count_calculation(self, shipper_user):
        event1 = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='T1', description='D1', idempotency_key='manual-notif-5')
        event2 = OperationalEvent.objects.create(event_type=OperationalEventType.HIGH_OPERATIONAL_RISK, severity=EventSeverity.CRITICAL, title='T2', description='D2', idempotency_key='manual-notif-6')

        Notification.objects.create(recipient=shipper_user, event=event1, notification_type=NotificationType.SYSTEM_ALERT, priority=EventSeverity.MEDIUM, title='N1', message='M1')
        Notification.objects.create(recipient=shipper_user, event=event2, notification_type=NotificationType.RISK_ALERT, priority=EventSeverity.CRITICAL, title='N2', message='M2')

        counts = NotificationService.get_unread_count(shipper_user)
        assert counts['unread_count'] == 2
        assert counts['critical_unread_count'] == 1



@pytest.mark.django_db
class TestNotificationPreferences:
    def test_default_notification_preferences_creation(self, shipper_user):
        pref, created = NotificationPreference.objects.get_or_create(user=shipper_user)
        assert pref.route_alerts_enabled is True
        assert pref.incident_alerts_enabled is True
        assert pref.critical_alerts_enabled is True

    def test_preference_filtering_disables_normal_notification(self, active_shipment, shipper_user):
        pref, _ = NotificationPreference.objects.get_or_create(user=shipper_user)
        pref.route_alerts_enabled = False
        pref.save()

        event = OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.MEDIUM,
            shipment=active_shipment,
            title='Route Deviation',
            description='Normal deviation alert'
        )

        notifs = Notification.objects.filter(event=event, recipient=shipper_user)
        assert notifs.count() == 0

    def test_critical_severity_overrides_normal_preference_disables(self, active_shipment, shipper_user):
        pref, _ = NotificationPreference.objects.get_or_create(user=shipper_user)
        pref.route_alerts_enabled = False
        pref.critical_alerts_enabled = True
        pref.save()

        event = OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.CRITICAL,
            shipment=active_shipment,
            title='Critical Corridor Deviation',
            description='Severe route deviation'
        )

        notifs = Notification.objects.filter(event=event, recipient=shipper_user)
        assert notifs.count() == 1


@pytest.mark.django_db
class TestPhaseIntegrations:
    def test_incident_report_triggers_operational_event(self, active_shipment, driver_user):
        from apps.marketplace.services import IncidentReportService
        report = IncidentReportService.create_incident_report(
            shipment=active_shipment,
            driver_user=driver_user,
            incident_data={
                "incident_type": IncidentType.ROAD_PROBLEM,
                "description": "Landslide near Bahir Dar corridor",
                "location_name": "Bahir Dar"
            }
        )

        events = OperationalEvent.objects.filter(shipment=active_shipment, event_type=OperationalEventType.INCIDENT_REPORTED)
        assert events.count() >= 1
        event = events.first()
        assert "Landslide near Bahir Dar" in event.description



@pytest.mark.django_db
class TestRealtimeRESTAPIs:
    @pytest.fixture
    def api_client(self):
        return APIClient()

    def test_notification_list_endpoint(self, api_client, shipper_user):
        event = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='API Test Alert', description='Desc', idempotency_key='api-notif-1')
        Notification.objects.create(recipient=shipper_user, event=event, notification_type=NotificationType.SYSTEM_ALERT, title='API Test Alert', message='Desc')

        api_client.force_authenticate(user=shipper_user)
        response = api_client.get('/api/v1/notifications/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] >= 1
        assert response.data['results'][0]['title'] == 'API Test Alert'

    def test_notification_unread_count_endpoint(self, api_client, shipper_user):
        event = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='Count Alert', description='Desc', idempotency_key='api-notif-2')
        Notification.objects.create(recipient=shipper_user, event=event, notification_type=NotificationType.SYSTEM_ALERT, title='Count Alert', message='Desc')

        api_client.force_authenticate(user=shipper_user)
        response = api_client.get('/api/v1/notifications/unread-count/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['unread_count'] >= 1

    def test_notification_read_and_read_all_endpoints(self, api_client, shipper_user):
        event1 = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='Read API 1', description='Desc', idempotency_key='api-notif-3')
        event2 = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='Read API 2', description='Desc', idempotency_key='api-notif-4')
        n1 = Notification.objects.create(recipient=shipper_user, event=event1, notification_type=NotificationType.SYSTEM_ALERT, title='N1', message='M1')
        n2 = Notification.objects.create(recipient=shipper_user, event=event2, notification_type=NotificationType.SYSTEM_ALERT, title='N2', message='M2')

        api_client.force_authenticate(user=shipper_user)
        resp1 = api_client.post(f'/api/v1/notifications/{n1.id}/read/')
        assert resp1.status_code == status.HTTP_200_OK
        assert resp1.data['is_read'] is True

        resp2 = api_client.post('/api/v1/notifications/read-all/')
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2.data['marked_read_count'] >= 1

    def test_notification_acknowledge_endpoint(self, api_client, shipper_user):
        event = OperationalEvent.objects.create(event_type=OperationalEventType.HIGH_OPERATIONAL_RISK, severity=EventSeverity.CRITICAL, title='Ack API', description='Desc', idempotency_key='api-notif-5')
        n = Notification.objects.create(recipient=shipper_user, event=event, notification_type=NotificationType.RISK_ALERT, priority=EventSeverity.CRITICAL, title='Ack Title', message='Msg')

        api_client.force_authenticate(user=shipper_user)
        response = api_client.post(f'/api/v1/notifications/{n.id}/acknowledge/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['is_acknowledged'] is True

    def test_shipment_events_list_endpoint(self, api_client, shipper_user, active_shipment):
        OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.HIGH,
            shipment=active_shipment,
            title='Shipment Event REST',
            description='Dev details'
        )

        api_client.force_authenticate(user=shipper_user)
        response = api_client.get(f'/api/v1/shipments/{active_shipment.id}/events/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] >= 1

    def test_notification_preferences_get_patch_endpoint(self, api_client, shipper_user):
        api_client.force_authenticate(user=shipper_user)
        get_resp = api_client.get('/api/v1/notification-preferences/')
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.data['route_alerts_enabled'] is True

        patch_resp = api_client.patch('/api/v1/notification-preferences/', {'route_alerts_enabled': False}, format='json')
        assert patch_resp.status_code == status.HTTP_200_OK
        assert patch_resp.data['route_alerts_enabled'] is False

    def test_unauthenticated_api_access_rejected(self, api_client):
        resp1 = api_client.get('/api/v1/notifications/')
        assert resp1.status_code == status.HTTP_401_UNAUTHORIZED

        resp2 = api_client.get('/api/v1/notification-preferences/')
        assert resp2.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthorized_user_cannot_access_other_user_notifications_or_events(self, api_client, unrelated_user, shipper_user, active_shipment):
        event = OperationalEvent.objects.create(event_type=OperationalEventType.SYSTEM_ALERT, title='Secret', description='Desc', idempotency_key='api-notif-6')
        n = Notification.objects.create(recipient=shipper_user, event=event, notification_type=NotificationType.SYSTEM_ALERT, title='Secret', message='Secret')

        api_client.force_authenticate(user=unrelated_user)
        resp1 = api_client.post(f'/api/v1/notifications/{n.id}/read/')
        assert resp1.status_code == status.HTTP_403_FORBIDDEN

        resp2 = api_client.get(f'/api/v1/shipments/{active_shipment.id}/events/')
        assert resp2.status_code == status.HTTP_403_FORBIDDEN



import asyncio


@pytest.mark.django_db(transaction=True)
class TestChannelsAndWebSockets:

    def test_jwt_websocket_auth_middleware_valid_token(self, shipper_user):
        async def run():
            from rest_framework_simplejwt.tokens import AccessToken
            token = str(AccessToken.for_user(shipper_user))
            inner_called = False

            async def inner_app(scope, receive, send):
                nonlocal inner_called
                inner_called = True
                assert scope['user'].id == shipper_user.id

            middleware = JWTAuthMiddleware(inner_app)
            scope = {
                "type": "websocket",
                "query_string": f"token={token}".encode('utf-8'),
                "headers": []
            }
            await middleware(scope, None, None)
            assert inner_called
        asyncio.run(run())

    def test_jwt_websocket_auth_middleware_invalid_token_anonymous(self):
        async def run():
            inner_called = False

            async def inner_app(scope, receive, send):
                nonlocal inner_called
                inner_called = True
                assert scope['user'].is_authenticated is False

            middleware = JWTAuthMiddleware(inner_app)
            scope = {
                "type": "websocket",
                "query_string": b"token=invalid.jwt.token",
                "headers": []
            }
            await middleware(scope, None, None)
            assert inner_called
        asyncio.run(run())

    def test_shipment_participant_authorization_check(self, shipper_user, unrelated_user, active_shipment):
        from apps.marketplace.consumers import is_authorized_shipment_participant
        async def run():
            auth_shipper = await is_authorized_shipment_participant(active_shipment.id, shipper_user)
            assert auth_shipper is True

            auth_unrelated = await is_authorized_shipment_participant(active_shipment.id, unrelated_user)
            assert auth_unrelated is False
        asyncio.run(run())




@pytest.mark.django_db
class TestNonMutationGuarantees:
    def test_event_and_notification_generation_does_not_mutate_business_state(self, active_shipment, shipper_user):
        initial_status = active_shipment.status
        initial_price = active_shipment.load.target_price

        event = OperationalEventService.create_event(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.CRITICAL,
            shipment=active_shipment,
            actor=shipper_user,
            title='Non Mutation Test',
            description='Test description'
        )

        active_shipment.refresh_from_db()
        assert active_shipment.status == initial_status
        assert active_shipment.load.target_price == initial_price
