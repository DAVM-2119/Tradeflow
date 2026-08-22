from rest_framework import serializers
from apps.marketplace.models import (
    SecurityAuditEvent, SecurityIncident, SecurityPolicy,
    SecurityAuditEventSeverity, SecurityAuditEventType,
    SecurityIncidentStatus, SecurityIncidentType
)


class SecurityAuditEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.ReadOnlyField(source='actor.email')
    target_user_email = serializers.ReadOnlyField(source='target_user.email')

    class Meta:
        model = SecurityAuditEvent
        fields = [
            'id', 'event_type', 'severity', 'actor', 'actor_email', 'actor_role',
            'target_user', 'target_user_email', 'target_model', 'target_object_id',
            'action', 'description', 'request_id', 'ip_address', 'user_agent',
            'endpoint', 'http_method', 'metadata', 'previous_hash', 'event_hash', 'created_at'
        ]
        read_only_fields = fields


class SecurityIncidentSerializer(serializers.ModelSerializer):
    detected_by_email = serializers.ReadOnlyField(source='detected_by.email')
    assigned_to_email = serializers.ReadOnlyField(source='assigned_to.email')

    class Meta:
        model = SecurityIncident
        fields = [
            'id', 'incident_type', 'severity', 'status', 'title', 'description',
            'detected_at', 'detected_by', 'detected_by_email', 'assigned_to',
            'assigned_to_email', 'resolved_at', 'resolution_notes', 'correlation_id',
            'metadata', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'detected_at', 'created_at', 'updated_at']


class SecurityIncidentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityIncident
        fields = ['status', 'severity', 'assigned_to', 'resolution_notes', 'metadata']


class SecurityPolicySerializer(serializers.ModelSerializer):
    created_by_email = serializers.ReadOnlyField(source='created_by.email')
    updated_by_email = serializers.ReadOnlyField(source='updated_by.email')

    class Meta:
        model = SecurityPolicy
        fields = [
            'id', 'name', 'policy_type', 'enabled', 'threshold', 'window_seconds',
            'severity', 'description', 'configuration', 'created_by', 'created_by_email',
            'updated_by', 'updated_by_email', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class SecurityPolicyCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityPolicy
        fields = [
            'name', 'policy_type', 'enabled', 'threshold', 'window_seconds',
            'severity', 'description', 'configuration'
        ]


class SecurityOverviewSerializer(serializers.Serializer):
    total_security_events = serializers.IntegerField()
    critical_events = serializers.IntegerField()
    high_severity_events = serializers.IntegerField()
    failed_logins = serializers.IntegerField()
    successful_logins = serializers.IntegerField()
    access_denials = serializers.IntegerField()
    open_security_incidents = serializers.IntegerField()
    investigating_incidents = serializers.IntegerField()
    resolved_incidents = serializers.IntegerField()
    privilege_changes = serializers.IntegerField()
    webhook_security_failures = serializers.IntegerField()
    audit_integrity_status = serializers.CharField()
    generated_at = serializers.DateTimeField()


class AuditIntegritySerializer(serializers.Serializer):
    status = serializers.CharField()
    events_checked = serializers.IntegerField()
    invalid_events = serializers.IntegerField()
    chain_valid = serializers.BooleanField()
    verified_at = serializers.DateTimeField()
    details = serializers.ListField(child=serializers.CharField(), default=list)


class ComplianceReportSerializer(serializers.Serializer):
    report_type = serializers.CharField()
    title = serializers.CharField()
    generated_at = serializers.DateTimeField()
    filters_applied = serializers.DictField()
    record_count = serializers.IntegerField()
    summary = serializers.DictField()
    records = serializers.ListField(child=serializers.DictField())


class UserSecurityHistorySerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_email = serializers.CharField()
    role = serializers.CharField()
    is_active = serializers.BooleanField()
    total_audit_events = serializers.IntegerField()
    recent_events = SecurityAuditEventSerializer(many=True)
