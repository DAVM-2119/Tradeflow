from rest_framework import serializers
from apps.marketplace.models import (
    OperationalEvent, Notification, NotificationPreference
)


class OperationalEventSerializer(serializers.ModelSerializer):
    """
    Serializer for immutable operational events.
    """
    actor_email = serializers.SerializerMethodField()

    class Meta:
        model = OperationalEvent
        fields = [
            'id', 'event_type', 'severity', 'shipment', 'actor', 'actor_email',
            'source', 'title', 'description', 'payload', 'idempotency_key', 'created_at'
        ]
        read_only_fields = fields

    def get_actor_email(self, obj) -> str:
        return obj.actor.email if obj.actor else None


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for user notifications.
    """
    class Meta:
        model = Notification
        fields = [
            'id', 'recipient', 'event', 'shipment', 'notification_type',
            'priority', 'title', 'message', 'data', 'is_read', 'read_at',
            'is_acknowledged', 'acknowledged_at', 'created_at'
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for user notification delivery preferences.
    """
    class Meta:
        model = NotificationPreference
        fields = [
            'user', 'route_alerts_enabled', 'eta_alerts_enabled',
            'risk_alerts_enabled', 'incident_alerts_enabled',
            'fuel_alerts_enabled', 'market_alerts_enabled',
            'automation_alerts_enabled', 'shipment_updates_enabled',
            'system_alerts_enabled', 'critical_alerts_enabled',
            'updated_at'
        ]
        read_only_fields = ['user', 'updated_at']


class UnreadCountSerializer(serializers.Serializer):
    """
    Serializer for notification unread counts.
    """
    unread_count = serializers.IntegerField()
    critical_unread_count = serializers.IntegerField()
