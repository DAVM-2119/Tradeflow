from rest_framework import serializers

class OperationalDashboardSerializer(serializers.Serializer):
    total_active_shipments = serializers.IntegerField()
    shipments_at_risk = serializers.IntegerField()
    high_risk_shipments = serializers.IntegerField()
    critical_risk_shipments = serializers.IntegerField()
    delayed_shipments = serializers.IntegerField()
    route_deviation_shipments = serializers.IntegerField()
    active_incidents = serializers.IntegerField()
    critical_incidents = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()
    critical_unacknowledged_notifications = serializers.IntegerField()
    pending_automation_recommendations = serializers.IntegerField()
    approved_automation_recommendations = serializers.IntegerField()
    high_market_pressure_shipments = serializers.IntegerField()
    stale_gps_shipments = serializers.IntegerField()
    failed_automation_executions = serializers.IntegerField()
    generated_at = serializers.CharField()


class OperationalHealthFactorSerializer(serializers.Serializer):
    factor = serializers.CharField()
    impact = serializers.FloatField()
    description = serializers.CharField()


class OperationalHealthSerializer(serializers.Serializer):
    score = serializers.FloatField()
    level = serializers.CharField()
    confidence = serializers.CharField()
    factors = OperationalHealthFactorSerializer(many=True)
    generated_at = serializers.CharField()


class OperationalAttentionItemSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    shipment_reference = serializers.CharField()
    priority = serializers.CharField()
    priority_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    risk_score = serializers.FloatField()
    attention_reasons = serializers.ListField(child=serializers.CharField())
    latest_event = serializers.DictField(required=False, allow_null=True)
    latest_notification = serializers.DictField(required=False, allow_null=True)
    route_deviation_status = serializers.CharField()
    eta_status = serializers.CharField()
    incident_status = serializers.CharField()
    automation_status = serializers.CharField()
    generated_at = serializers.CharField()


class OperationalAlertSerializer(serializers.Serializer):
    total_alerts = serializers.IntegerField()
    critical_alerts = serializers.IntegerField()
    high_alerts = serializers.IntegerField()
    medium_alerts = serializers.IntegerField()
    low_alerts = serializers.IntegerField()
    unacknowledged_critical_alerts = serializers.IntegerField()
    top_event_types = serializers.ListField(child=serializers.DictField())
    affected_shipments = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class TrendBucketSerializer(serializers.Serializer):
    timestamp = serializers.CharField()
    total = serializers.IntegerField()
    critical = serializers.IntegerField()
    high = serializers.IntegerField()
    medium = serializers.IntegerField()
    low = serializers.IntegerField()


class OperationalTrendSerializer(serializers.Serializer):
    period = serializers.CharField()
    buckets = TrendBucketSerializer(many=True)
    generated_at = serializers.CharField()


class RiskDistributionItemSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class OperationalRiskDistributionSerializer(serializers.Serializer):
    total_shipments_evaluated = serializers.IntegerField()
    distribution = serializers.DictField(child=RiskDistributionItemSerializer())
    generated_at = serializers.CharField()


class OperationalIncidentSummarySerializer(serializers.Serializer):
    total_active_incidents = serializers.IntegerField()
    incidents_by_type = serializers.ListField(child=serializers.DictField())
    critical_unresolved_incidents = serializers.ListField(child=serializers.DictField())
    recently_reported_incidents = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class OperationalTelemetrySummarySerializer(serializers.Serializer):
    shipments_currently_deviated = serializers.IntegerField()
    average_deviation_distance_km = serializers.FloatField()
    maximum_deviation_distance_km = serializers.FloatField()
    stale_gps_shipment_count = serializers.IntegerField()
    recent_telemetry_timestamp = serializers.CharField(allow_null=True)
    missing_telemetry_count = serializers.IntegerField()
    high_eta_delay_shipment_count = serializers.IntegerField()
    generated_at = serializers.CharField()


class OperationalMarketSummarySerializer(serializers.Serializer):
    high_market_pressure_count = serializers.IntegerField()
    normal_market_pressure_count = serializers.IntegerField()
    low_market_pressure_count = serializers.IntegerField()
    average_pricing_confidence = serializers.FloatField()
    shipments_with_low_pricing_confidence = serializers.IntegerField()
    latest_market_snapshot_timestamp = serializers.CharField(allow_null=True)
    generated_at = serializers.CharField()


class OperationalAutomationSummarySerializer(serializers.Serializer):
    pending_recommendations = serializers.IntegerField()
    approved_recommendations = serializers.IntegerField()
    rejected_recommendations = serializers.IntegerField()
    executed_recommendations = serializers.IntegerField()
    failed_executions = serializers.IntegerField()
    critical_pending_recommendations = serializers.IntegerField()
    high_pending_recommendations = serializers.IntegerField()
    recommendations_by_priority = serializers.ListField(child=serializers.DictField())
    recommendations_by_rule_type = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class EventCorrelationSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    correlation_key = serializers.CharField()
    correlation_level = serializers.CharField()
    score = serializers.FloatField()
    signals = serializers.ListField(child=serializers.CharField())
    explanation = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class ShipmentOperationalSummarySerializer(serializers.Serializer):
    shipment = serializers.DictField()
    risk = serializers.DictField()
    eta = serializers.DictField()
    route = serializers.DictField()
    fuel = serializers.DictField()
    incidents = serializers.DictField()
    pricing = serializers.DictField()
    automation = serializers.DictField()
    notifications = serializers.DictField()
    latest_events = serializers.ListField(child=serializers.DictField())
    event_correlation = EventCorrelationSerializer()
    generated_at = serializers.CharField()
