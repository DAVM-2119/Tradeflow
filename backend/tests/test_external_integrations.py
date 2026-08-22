import hmac
import hashlib
import json
from unittest.mock import patch, MagicMock
import pytest

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role
from apps.marketplace.models import (
    ExternalIntegration, IntegrationType, IntegrationStatus,
    WebhookEndpoint, WebhookDelivery, WebhookDeliveryStatus,
    InboundWebhookEvent, InboundWebhookStatus,
    CargoLoad, Shipment
)
from apps.marketplace.integration_services import IntegrationService

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_p18@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_p18@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.filter(email="user_p18@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="user_p18@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.fixture
def test_integration(admin_user):
    return IntegrationService.create_integration(admin_user, {
        "name": "ERP Integration Test",
        "integration_type": IntegrationType.ERP,
        "base_url": "https://erp.enterprise.et/api",
        "webhook_secret": "secret_key_1234567890"
    })


@pytest.fixture
def test_endpoint(test_integration, admin_user):
    return IntegrationService.create_webhook_endpoint(test_integration.id, admin_user, {
        "name": "ERP Webhook Receiver",
        "url": "https://erp.enterprise.et/webhooks/receive/",
        "event_types": ["SHIPMENT_CREATED", "INCIDENT_REPORTED"],
        "secret": "endpoint_secret_987654321"
    })


@pytest.mark.django_db
class TestExternalIntegrationManagement:
    def test_integration_creation(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        payload = {
            "name": "Accounting Sync",
            "integration_type": "ACCOUNTING",
            "base_url": "https://accounting.et"
        }
        res = client.post("/api/v1/integrations/", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["name"] == "Accounting Sync"
        assert res.data["webhook_secret"] == "********"

    def test_integration_update(self, admin_user, test_integration):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.patch(f"/api/v1/integrations/{test_integration.id}/", {"name": "Updated ERP Name"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["name"] == "Updated ERP Name"

    def test_integration_authorization(self, regular_user):
        client = APIClient()
        client.force_authenticate(user=regular_user)
        res = client.get("/api/v1/integrations/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_integration_activation_deactivation(self, admin_user, test_integration):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        res_deact = client.post(f"/api/v1/integrations/{test_integration.id}/deactivate/")
        assert res_deact.status_code == status.HTTP_200_OK
        assert res_deact.data["status"] == IntegrationStatus.INACTIVE

        res_act = client.post(f"/api/v1/integrations/{test_integration.id}/activate/")
        assert res_act.status_code == status.HTTP_200_OK
        assert res_act.data["status"] == IntegrationStatus.ACTIVE

    def test_integration_health(self, admin_user, test_integration):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get(f"/api/v1/integrations/{test_integration.id}/health/")
        assert res.status_code == status.HTTP_200_OK
        assert "success_rate" in res.data
        assert res.data["integration_id"] == test_integration.id


@pytest.mark.django_db
class TestWebhookEndpointManagement:
    def test_webhook_endpoint_creation(self, admin_user, test_integration):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        payload = {
            "name": "Logistics Dispatch Hook",
            "url": "https://logistics.et/webhook/",
            "event_types": ["SHIPMENT_CREATED"]
        }
        res = client.post(f"/api/v1/integrations/{test_integration.id}/webhooks/", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["name"] == "Logistics Dispatch Hook"
        assert res.data["secret"] == "********"

    def test_webhook_endpoint_detail_and_update(self, admin_user, test_endpoint):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get(f"/api/v1/webhooks/{test_endpoint.id}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["name"] == test_endpoint.name

        res_upd = client.patch(f"/api/v1/webhooks/{test_endpoint.id}/", {"name": "Renamed Endpoint"}, format="json")
        assert res_upd.status_code == status.HTTP_200_OK
        assert res_upd.data["name"] == "Renamed Endpoint"

    def test_webhook_endpoint_activation_deactivation(self, admin_user, test_endpoint):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res_deact = client.post(f"/api/v1/webhooks/{test_endpoint.id}/deactivate/")
        assert res_deact.status_code == status.HTTP_200_OK
        assert res_deact.data["is_active"] is False

        res_act = client.post(f"/api/v1/webhooks/{test_endpoint.id}/activate/")
        assert res_act.status_code == status.HTTP_200_OK
        assert res_act.data["is_active"] is True

    def test_invalid_url_rejection(self, admin_user, test_integration):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        payload = {
            "name": "Invalid Hook",
            "url": "ftp://malicious.et/webhook/"
        }
        res = client.post(f"/api/v1/integrations/{test_integration.id}/webhooks/", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_secret_rotation(self, admin_user, test_endpoint):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        old_secret = test_endpoint.secret
        res = client.post(f"/api/v1/webhooks/{test_endpoint.id}/rotate-secret/")
        assert res.status_code == status.HTTP_200_OK
        test_endpoint.refresh_from_db()
        assert test_endpoint.secret != old_secret


@pytest.mark.django_db
class TestOutboundEventPublishingAndDelivery:
    def test_event_publishing_and_subscription_filtering(self, test_endpoint):
        deliveries_pub = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=1, data={"status": "CREATED"})
        assert len(deliveries_pub) == 1
        assert deliveries_pub[0].event_type == "SHIPMENT_CREATED"

        deliveries_unsub = IntegrationService.publish_event("UNSUBSCRIBED_EVENT", shipment_id=1)
        assert len(deliveries_unsub) == 0

    def test_duplicate_delivery_prevention(self, test_endpoint):
        deliv1 = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=10, data={"key": "val"})
        deliv2 = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=10, data={"key": "val"})
        assert len(deliv1) == 1
        assert len(deliv2) == 0

    @patch("urllib.request.urlopen")
    def test_successful_delivery_execution(self, mock_urlopen, test_endpoint):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'{"status": "received"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        deliveries = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=5)
        d = IntegrationService.process_delivery(deliveries[0].id)

        assert d.status == WebhookDeliveryStatus.DELIVERED
        assert d.response_status == 200
        assert d.attempt_count == 1

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_failed_delivery_and_retry_scheduling(self, mock_urlopen, test_endpoint):
        deliveries = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=8)
        d = IntegrationService.process_delivery(deliveries[0].id)

        assert d.status == WebhookDeliveryStatus.RETRYING
        assert d.attempt_count == 1
        assert d.next_retry_at is not None

    def test_exponential_backoff_retry_calculation(self):
        t1 = IntegrationService.calculate_next_retry(1)
        t2 = IntegrationService.calculate_next_retry(2)
        t3 = IntegrationService.calculate_next_retry(3)
        assert t2 > t1
        assert t3 > t2

    @patch("urllib.request.urlopen")
    def test_delivery_detail_and_retry_views(self, mock_urlopen, admin_user, test_endpoint):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        deliveries = IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=20)
        deliv_id = deliveries[0].id

        client = APIClient()
        client.force_authenticate(user=admin_user)
        res_det = client.get(f"/api/v1/webhook-deliveries/{deliv_id}/")
        assert res_det.status_code == status.HTTP_200_OK

        res_retry = client.post(f"/api/v1/webhook-deliveries/{deliv_id}/retry/")
        assert res_retry.status_code == status.HTTP_200_OK
        assert res_retry.data["status"] == WebhookDeliveryStatus.DELIVERED

    @patch("urllib.request.urlopen")
    def test_integration_event_publish_api_view(self, mock_urlopen, admin_user, test_endpoint):
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'{"status": "ok"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        client = APIClient()
        client.force_authenticate(user=admin_user)
        payload = {
            "event_type": "INCIDENT_REPORTED",
            "shipment_id": 99,
            "data": {"severity": "HIGH"}
        }
        res = client.post("/api/v1/integrations/events/publish/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) == 1
        assert res.data[0]["status"] == WebhookDeliveryStatus.DELIVERED


@pytest.mark.django_db
class TestInboundWebhooksAndSigning:
    def test_hmac_signature_generation_and_verification(self, test_integration):
        body_data = json.dumps({"event_type": "ERP_UPDATE", "event_id": "erp_evt_1001", "status": "SYNCED"})
        secret = test_integration.webhook_secret
        valid_sig = hmac.new(secret.encode('utf-8'), body_data.encode('utf-8'), hashlib.sha256).hexdigest()

        evt = IntegrationService.process_inbound_webhook(test_integration.id, body_data, valid_sig, {})
        assert evt.signature_valid is True
        assert evt.processing_status == InboundWebhookStatus.PROCESSED

    def test_invalid_signature_rejection(self, test_integration):
        body_data = json.dumps({"event_type": "ERP_UPDATE", "event_id": "erp_evt_1002"})
        invalid_sig = "invalid_signature_hash"

        evt = IntegrationService.process_inbound_webhook(test_integration.id, body_data, invalid_sig, {})
        assert evt.signature_valid is False
        assert evt.processing_status == InboundWebhookStatus.REJECTED

    def test_inbound_webhook_receiver_api_view(self, test_integration):
        body_data = json.dumps({"event_type": "INBOUND_SYNC", "event_id": "inb_api_01", "data": "test"})
        secret = test_integration.webhook_secret
        sig = hmac.new(secret.encode('utf-8'), body_data.encode('utf-8'), hashlib.sha256).hexdigest()

        client = APIClient()
        res = client.post(
            f"/api/v1/webhooks/inbound/{test_integration.id}/",
            data=body_data,
            content_type="application/json",
            HTTP_X_TRADEFLOW_SIGNATURE=sig
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["signature_valid"] is True

    def test_duplicate_inbound_event_detection(self, test_integration):
        body_data = json.dumps({"event_type": "ERP_UPDATE", "event_id": "erp_evt_dup_999"})
        secret = test_integration.webhook_secret
        sig = hmac.new(secret.encode('utf-8'), body_data.encode('utf-8'), hashlib.sha256).hexdigest()

        evt1 = IntegrationService.process_inbound_webhook(test_integration.id, body_data, sig, {})
        assert evt1.processing_status == InboundWebhookStatus.PROCESSED

        evt2 = IntegrationService.process_inbound_webhook(test_integration.id, body_data, sig, {})
        assert evt2.processing_status == InboundWebhookStatus.DUPLICATE


@pytest.mark.django_db
class TestNonMutationAndSecurity:
    def test_unauthenticated_access_rejected(self):
        client = APIClient()
        res = client.get("/api/v1/integrations/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_integration_requests_do_not_mutate_business_state(self, admin_user, test_endpoint):
        load_count_before = CargoLoad.objects.count()
        shipment_count_before = Shipment.objects.count()

        IntegrationService.publish_event("SHIPMENT_CREATED", shipment_id=1, data={"status": "UPDATED"})

        client = APIClient()
        client.force_authenticate(user=admin_user)
        client.get("/api/v1/integrations/")
        client.get(f"/api/v1/integrations/{test_endpoint.integration.id}/health/")

        assert CargoLoad.objects.count() == load_count_before
        assert Shipment.objects.count() == shipment_count_before

