import hmac
import hashlib
import json
import logging
import secrets
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from datetime import timedelta

from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from apps.accounts.models import Role
from apps.marketplace.models import (
    ExternalIntegration, IntegrationType, IntegrationStatus,
    WebhookEndpoint, WebhookDelivery, WebhookDeliveryStatus,
    InboundWebhookEvent, InboundWebhookStatus, Shipment
)

logger = logging.getLogger('tradeflow.integrations')


class IntegrationService:
    """
    Primary orchestration service for Phase 18 External Integrations, Webhooks & Enterprise Data Exchange.
    """

    @classmethod
    def generate_secret(cls, prefix: str = "tf_sec_") -> str:
        return f"{prefix}{secrets.token_hex(24)}"

    @classmethod
    def create_integration(cls, user, data: Dict[str, Any]) -> ExternalIntegration:
        if not user.is_superuser and user.role != Role.ADMIN:
            raise PermissionDenied("Only administrators can create external integrations.")

        webhook_secret = data.get('webhook_secret') or cls.generate_secret("tf_intsec_")

        integration = ExternalIntegration.objects.create(
            name=data['name'],
            integration_type=data.get('integration_type', IntegrationType.CUSTOM),
            status=data.get('status', IntegrationStatus.ACTIVE),
            base_url=data.get('base_url', ''),
            webhook_secret=webhook_secret,
            api_key_reference=data.get('api_key_reference', ''),
            configuration=data.get('configuration', {}),
            created_by=user
        )
        return integration

    @classmethod
    def update_integration(cls, integration_id: int, user, data: Dict[str, Any]) -> ExternalIntegration:
        if not user.is_superuser and user.role != Role.ADMIN:
            raise PermissionDenied("Only administrators can update external integrations.")

        integration = ExternalIntegration.objects.filter(id=integration_id).first()
        if not integration:
            raise NotFound("External integration not found.")

        for attr in ['name', 'integration_type', 'status', 'base_url', 'api_key_reference', 'configuration']:
            if attr in data:
                setattr(integration, attr, data[attr])

        if data.get('webhook_secret'):
            integration.webhook_secret = data['webhook_secret']

        integration.save()
        return integration

    @classmethod
    def activate_integration(cls, integration_id: int, user) -> ExternalIntegration:
        return cls.update_integration(integration_id, user, {'status': IntegrationStatus.ACTIVE})

    @classmethod
    def deactivate_integration(cls, integration_id: int, user) -> ExternalIntegration:
        return cls.update_integration(integration_id, user, {'status': IntegrationStatus.INACTIVE})

    @classmethod
    def create_webhook_endpoint(cls, integration_id: int, user, data: Dict[str, Any]) -> WebhookEndpoint:
        if not user.is_superuser and user.role != Role.ADMIN:
            raise PermissionDenied("Only administrators can create webhook endpoints.")

        integration = ExternalIntegration.objects.filter(id=integration_id).first()
        if not integration:
            raise NotFound("External integration not found.")

        url = data.get('url', '')
        if not url.startswith(('http://', 'https://')):
            raise ValidationError("Webhook URL must start with http:// or https://")

        secret = data.get('secret') or cls.generate_secret("tf_whsec_")

        endpoint = WebhookEndpoint.objects.create(
            integration=integration,
            name=data['name'],
            url=url,
            event_types=data.get('event_types', []),
            is_active=data.get('is_active', True),
            secret=secret
        )
        return endpoint

    @classmethod
    def update_webhook_endpoint(cls, endpoint_id: int, user, data: Dict[str, Any]) -> WebhookEndpoint:
        if not user.is_superuser and user.role != Role.ADMIN:
            raise PermissionDenied("Only administrators can update webhook endpoints.")

        endpoint = WebhookEndpoint.objects.filter(id=endpoint_id).first()
        if not endpoint:
            raise NotFound("Webhook endpoint not found.")

        if 'url' in data:
            url = data['url']
            if not url.startswith(('http://', 'https://')):
                raise ValidationError("Webhook URL must start with http:// or https://")
            endpoint.url = url

        for attr in ['name', 'event_types', 'is_active']:
            if attr in data:
                setattr(endpoint, attr, data[attr])

        if data.get('secret'):
            endpoint.secret = data['secret']

        endpoint.save()
        return endpoint

    @classmethod
    def rotate_webhook_secret(cls, endpoint_id: int, user) -> WebhookEndpoint:
        new_secret = cls.generate_secret("tf_whsec_")
        return cls.update_webhook_endpoint(endpoint_id, user, {'secret': new_secret})

    @classmethod
    def publish_event(cls, event_type: str, shipment_id: Optional[int] = None, data: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None) -> List[WebhookDelivery]:
        """
        Publishes operational event to subscribed webhook endpoints and creates deduplicated WebhookDelivery records.
        """
        data = data or {}
        now = timezone.now()

        endpoints = WebhookEndpoint.objects.filter(
            is_active=True,
            integration__status=IntegrationStatus.ACTIVE
        )

        data_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
        data_hash = hashlib.md5(data_bytes).hexdigest()

        deliveries = []
        for ep in endpoints:
            if not ep.event_types or '*' in ep.event_types or event_type in ep.event_types:
                idempotency_key = f"idemp_{ep.id}_{event_type}_{shipment_id or 0}_{data_hash}"

                payload = {
                    "event_id": f"evt_{idempotency_key}",
                    "event_type": event_type,
                    "occurred_at": now.isoformat(),
                    "shipment_id": shipment_id,
                    "data": data,
                    "request_id": request_id or f"req_{secrets.token_hex(8)}"
                }

                try:
                    with transaction.atomic():
                        delivery, created = WebhookDelivery.objects.get_or_create(
                            webhook_endpoint=ep,
                            idempotency_key=idempotency_key,
                            defaults={
                                'event_type': event_type,
                                'payload': payload,
                                'status': WebhookDeliveryStatus.PENDING,
                                'max_attempts': 5
                            }
                        )
                        if created:
                            deliveries.append(delivery)
                except IntegrityError:
                    # Duplicate idempotency key ignored
                    pass

        return deliveries


    @classmethod
    def calculate_next_retry(cls, attempt_count: int) -> timezone.datetime:
        """
        Calculates bounded exponential backoff retry timestamp.
        Attempt 1: 0s, 2: 60s, 3: 300s (5m), 4: 900s (15m), 5: 3600s (1h).
        """
        backoff_seconds = [0, 60, 300, 900, 3600]
        idx = min(max(0, attempt_count - 1), len(backoff_seconds) - 1)
        return timezone.now() + timedelta(seconds=backoff_seconds[idx])

    @classmethod
    def process_delivery(cls, delivery_id: int) -> WebhookDelivery:
        """
        Executes HTTP delivery for a WebhookDelivery record with HMAC SHA-256 signing and correlation headers.
        """
        with transaction.atomic():
            delivery = WebhookDelivery.objects.select_for_update().filter(id=delivery_id).first()
            if not delivery:
                raise NotFound("Webhook delivery record not found.")

            if delivery.status in [WebhookDeliveryStatus.DELIVERED, WebhookDeliveryStatus.CANCELLED]:
                return delivery

            delivery.status = WebhookDeliveryStatus.PROCESSING
            delivery.attempt_count += 1
            delivery.last_attempt_at = timezone.now()
            delivery.save()

        ep = delivery.webhook_endpoint
        secret = ep.secret or ep.integration.webhook_secret or ""
        raw_payload = json.dumps(delivery.payload, sort_keys=True)

        signature = hmac.new(secret.encode('utf-8'), raw_payload.encode('utf-8'), hashlib.sha256).hexdigest()

        headers = {
            'Content-Type': 'application/json',
            'X-TradeFlow-Signature': signature,
            'X-TradeFlow-Event': delivery.event_type,
            'X-TradeFlow-Delivery-ID': str(delivery.id),
            'X-Request-ID': delivery.payload.get('request_id', ''),
            'User-Agent': 'TradeFlow-Webhook-Publisher/1.0'
        }

        try:
            req = urllib.request.Request(
                ep.url,
                data=raw_payload.encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                res_code = response.getcode()
                res_body = response.read().decode('utf-8', errors='ignore')[:2000]

                delivery.response_status = res_code
                delivery.response_body = res_body
                delivery.status = WebhookDeliveryStatus.DELIVERED
                delivery.delivered_at = timezone.now()
                delivery.error_message = ""
                delivery.save()

                ep.integration.last_success_at = timezone.now()
                ep.integration.save(update_fields=['last_success_at'])

        except urllib.error.HTTPError as exc:
            res_code = exc.code
            res_body = exc.read().decode('utf-8', errors='ignore')[:2000]

            delivery.response_status = res_code
            delivery.response_body = res_body
            delivery.error_message = f"HTTP Error {res_code}: {exc.reason}"

            if delivery.attempt_count < delivery.max_attempts:
                delivery.status = WebhookDeliveryStatus.RETRYING
                delivery.next_retry_at = cls.calculate_next_retry(delivery.attempt_count + 1)
            else:
                delivery.status = WebhookDeliveryStatus.FAILED

            delivery.save()
            ep.integration.last_failure_at = timezone.now()
            ep.integration.save(update_fields=['last_failure_at'])

        except Exception as exc:
            delivery.response_status = 500
            delivery.error_message = f"Delivery Connection Exception: {str(exc)[:500]}"

            if delivery.attempt_count < delivery.max_attempts:
                delivery.status = WebhookDeliveryStatus.RETRYING
                delivery.next_retry_at = cls.calculate_next_retry(delivery.attempt_count + 1)
            else:
                delivery.status = WebhookDeliveryStatus.FAILED

            delivery.save()
            ep.integration.last_failure_at = timezone.now()
            ep.integration.save(update_fields=['last_failure_at'])

        return delivery

    @classmethod
    def retry_delivery(cls, delivery_id: int, user) -> WebhookDelivery:
        if not user.is_superuser and user.role != Role.ADMIN:
            raise PermissionDenied("Only administrators can retry failed webhook deliveries.")

        delivery = WebhookDelivery.objects.filter(id=delivery_id).first()
        if not delivery:
            raise NotFound("Webhook delivery record not found.")

        if delivery.status == WebhookDeliveryStatus.DELIVERED:
            return delivery

        return cls.process_delivery(delivery.id)

    @classmethod
    def process_inbound_webhook(cls, integration_id: int, raw_body: str, signature: str, headers: Dict[str, Any]) -> InboundWebhookEvent:
        integration = ExternalIntegration.objects.filter(id=integration_id).first()
        if not integration:
            raise NotFound("External integration not found.")

        if integration.status != IntegrationStatus.ACTIVE:
            raise ValidationError("External integration is inactive or disabled.")

        expected_sig = hmac.new(integration.webhook_secret.encode('utf-8'), raw_body.encode('utf-8'), hashlib.sha256).hexdigest()
        is_valid = hmac.compare_digest(signature or '', expected_sig)

        try:
            payload = json.loads(raw_body)
        except Exception:
            payload = {}
            is_valid = False

        event_type = payload.get('event_type', 'INBOUND_EVENT')
        ext_event_id = payload.get('event_id') or payload.get('id') or f"inb_{hashlib.md5(raw_body.encode('utf-8')).hexdigest()}"

        idemp_key = f"inb_idemp_{integration.id}_{ext_event_id}"

        try:
            with transaction.atomic():
                inbound_evt = InboundWebhookEvent.objects.create(
                    integration=integration,
                    event_type=event_type,
                    external_event_id=ext_event_id,
                    payload=payload,
                    signature_valid=is_valid,
                    processing_status=InboundWebhookStatus.PROCESSED if is_valid else InboundWebhookStatus.REJECTED,
                    idempotency_key=idemp_key,
                    processed_at=timezone.now() if is_valid else None,
                    error_message="" if is_valid else "Invalid HMAC signature or malformed JSON body"
                )
                return inbound_evt
        except IntegrityError:
            dup_evt = InboundWebhookEvent.objects.filter(integration=integration, external_event_id=ext_event_id).first()
            if dup_evt:
                dup_evt.processing_status = InboundWebhookStatus.DUPLICATE
                dup_evt.save(update_fields=['processing_status'])
                return dup_evt
            raise ValidationError("Duplicate inbound webhook event.")

    @classmethod
    def get_integration_health(cls, integration_id: int) -> Dict[str, Any]:
        integration = ExternalIntegration.objects.filter(id=integration_id).first()
        if not integration:
            raise NotFound("External integration not found.")

        endpoints = WebhookEndpoint.objects.filter(integration=integration)
        tot_endpoints = endpoints.count()
        act_endpoints = endpoints.filter(is_active=True).count()

        deliveries = WebhookDelivery.objects.filter(webhook_endpoint__integration=integration)
        succ = deliveries.filter(status=WebhookDeliveryStatus.DELIVERED).count()
        failed = deliveries.filter(status=WebhookDeliveryStatus.FAILED).count()
        pending = deliveries.filter(status__in=[WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.RETRYING, WebhookDeliveryStatus.PROCESSING]).count()

        evaluated = succ + failed
        succ_rate = round(succ / evaluated, 4) if evaluated > 0 else 1.0

        return {
            "integration_id": integration.id,
            "integration_name": integration.name,
            "status": integration.status,
            "total_endpoints": tot_endpoints,
            "active_endpoints": act_endpoints,
            "successful_deliveries": succ,
            "failed_deliveries": failed,
            "pending_deliveries": pending,
            "success_rate": succ_rate,
            "last_success_at": integration.last_success_at,
            "last_failure_at": integration.last_failure_at,
            "generated_at": timezone.now()
        }
