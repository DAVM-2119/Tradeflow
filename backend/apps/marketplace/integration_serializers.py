from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from apps.marketplace.models import (
    ExternalIntegration, WebhookEndpoint, WebhookDelivery, InboundWebhookEvent,
    IntegrationType, IntegrationStatus, WebhookDeliveryStatus, InboundWebhookStatus
)


class ExternalIntegrationSerializer(serializers.ModelSerializer):
    webhook_secret = serializers.SerializerMethodField()

    class Meta:
        model = ExternalIntegration
        fields = [
            'id', 'name', 'integration_type', 'status', 'base_url',
            'webhook_secret', 'api_key_reference', 'configuration',
            'created_by', 'created_at', 'updated_at', 'last_success_at', 'last_failure_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at', 'last_success_at', 'last_failure_at']

    @extend_schema_field(serializers.CharField)
    def get_webhook_secret(self, obj):
        if obj.webhook_secret:
            return "********"
        return ""


class ExternalIntegrationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalIntegration
        fields = [
            'id', 'name', 'integration_type', 'status', 'base_url',
            'webhook_secret', 'api_key_reference', 'configuration'
        ]


class ExternalIntegrationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalIntegration
        fields = [
            'name', 'integration_type', 'status', 'base_url',
            'webhook_secret', 'api_key_reference', 'configuration'
        ]


class WebhookEndpointSerializer(serializers.ModelSerializer):
    secret = serializers.SerializerMethodField()

    class Meta:
        model = WebhookEndpoint
        fields = [
            'id', 'integration', 'name', 'url', 'event_types',
            'is_active', 'secret', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    @extend_schema_field(serializers.CharField)
    def get_secret(self, obj):
        if obj.secret:
            return "********"
        return ""


    def validate_url(self, value):
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError("Webhook URL must start with http:// or https://")
        return value


class WebhookEndpointCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = ['id', 'integration', 'name', 'url', 'event_types', 'is_active', 'secret']

    def validate_url(self, value):
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError("Webhook URL must start with http:// or https://")
        return value


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            'id', 'webhook_endpoint', 'event_type', 'idempotency_key',
            'status', 'attempt_count', 'max_attempts', 'last_attempt_at',
            'next_retry_at', 'response_status', 'created_at', 'delivered_at'
        ]
        read_only_fields = ['id', 'created_at', 'delivered_at']


class WebhookDeliveryDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            'id', 'webhook_endpoint', 'event_type', 'payload', 'idempotency_key',
            'status', 'attempt_count', 'max_attempts', 'last_attempt_at',
            'next_retry_at', 'response_status', 'response_body', 'error_message',
            'created_at', 'updated_at', 'delivered_at'
        ]
        read_only_fields = fields


class InboundWebhookEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = InboundWebhookEvent
        fields = [
            'id', 'integration', 'event_type', 'external_event_id',
            'payload', 'signature_valid', 'processing_status',
            'idempotency_key', 'received_at', 'processed_at', 'error_message'
        ]
        read_only_fields = fields


class IntegrationHealthSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField()
    integration_name = serializers.CharField()
    status = serializers.CharField()
    total_endpoints = serializers.IntegerField()
    active_endpoints = serializers.IntegerField()
    successful_deliveries = serializers.IntegerField()
    failed_deliveries = serializers.IntegerField()
    pending_deliveries = serializers.IntegerField()
    success_rate = serializers.FloatField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    last_failure_at = serializers.DateTimeField(allow_null=True)
    generated_at = serializers.DateTimeField()


class IntegrationEventPublishSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=100)
    shipment_id = serializers.IntegerField(required=False, allow_null=True)
    data = serializers.DictField(default=dict)


class WebhookRetrySerializer(serializers.Serializer):
    message = serializers.CharField()
    delivery = WebhookDeliverySerializer()
