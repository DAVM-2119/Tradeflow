from rest_framework import serializers


class AnalyticsFilterSerializer(serializers.Serializer):
    period = serializers.ChoiceField(
        choices=['1h', '6h', '24h', '7d', '30d', '90d', 'custom'],
        default='30d',
        required=False
    )
    start_date = serializers.DateTimeField(required=False, allow_null=True)
    end_date = serializers.DateTimeField(required=False, allow_null=True)
    shipment_status = serializers.CharField(required=False, allow_blank=True)


class DashboardOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    period = serializers.DictField()
    shipments = serializers.DictField()
    delivery_performance = serializers.DictField()
    financial = serializers.DictField()
    risk = serializers.DictField()
    incidents = serializers.DictField()
    automation = serializers.DictField()


class ShipmentAnalyticsSerializer(serializers.Serializer):
    total_shipments = serializers.IntegerField()
    active_shipments = serializers.IntegerField()
    completed_shipments = serializers.IntegerField()
    cancelled_shipments = serializers.IntegerField()
    completion_rate = serializers.FloatField()
    average_duration_hours = serializers.FloatField()
    status_distribution = serializers.DictField()
    generated_at = serializers.DateTimeField()


class DeliveryPerformanceSerializer(serializers.Serializer):
    total_deliveries_evaluated = serializers.IntegerField()
    on_time_deliveries = serializers.IntegerField()
    late_deliveries = serializers.IntegerField()
    on_time_delivery_rate = serializers.FloatField()
    average_delay_minutes = serializers.FloatField()
    maximum_delay_minutes = serializers.FloatField()
    average_estimated_duration_hours = serializers.FloatField()
    generated_at = serializers.DateTimeField()


class FinancialAnalyticsSerializer(serializers.Serializer):
    total_invoiced_etb = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_settled_etb = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_paid_etb = serializers.DecimalField(max_digits=14, decimal_places=2)
    average_freight_value_etb = serializers.DecimalField(max_digits=14, decimal_places=2)
    average_settlement_value_etb = serializers.DecimalField(max_digits=14, decimal_places=2)
    payment_status_distribution = serializers.DictField()
    invoice_status_distribution = serializers.DictField()
    generated_at = serializers.DateTimeField()


class MarketAnalyticsSerializer(serializers.Serializer):
    data_available = serializers.BooleanField()
    total_recommendations = serializers.IntegerField()
    average_recommended_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    minimum_recommended_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    maximum_recommended_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    market_pressure_distribution = serializers.DictField(required=False)
    average_pricing_confidence = serializers.FloatField(required=False)
    generated_at = serializers.DateTimeField()


class RiskAnalyticsSerializer(serializers.Serializer):
    total_evaluated = serializers.IntegerField()
    average_risk_score = serializers.FloatField()
    high_risk_count = serializers.IntegerField()
    critical_risk_count = serializers.IntegerField()
    risk_distribution = serializers.DictField()
    trend = serializers.ListField(child=serializers.DictField(), required=False)
    generated_at = serializers.DateTimeField()


class IncidentAnalyticsSerializer(serializers.Serializer):
    total_incidents = serializers.IntegerField()
    critical_incidents = serializers.IntegerField()
    incidents_per_shipment = serializers.FloatField()
    incident_type_distribution = serializers.ListField(child=serializers.DictField())
    severity_distribution = serializers.DictField()
    generated_at = serializers.DateTimeField()


class RouteAnalyticsSerializer(serializers.Serializer):
    data_available = serializers.BooleanField()
    total_route_distance_km = serializers.FloatField(required=False)
    average_route_distance_km = serializers.FloatField(required=False)
    route_deviation_count = serializers.IntegerField(required=False)
    average_fuel_consumption_liters = serializers.FloatField(required=False)
    total_estimated_fuel_cost_etb = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    generated_at = serializers.DateTimeField()


class AutomationAnalyticsSerializer(serializers.Serializer):
    total_recommendations = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    approved_count = serializers.IntegerField()
    rejected_count = serializers.IntegerField()
    executed_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    approval_rate = serializers.FloatField()
    execution_rate = serializers.FloatField()
    rejection_rate = serializers.FloatField()
    failure_rate = serializers.FloatField()
    by_rule = serializers.ListField(child=serializers.DictField())
    by_priority = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.DateTimeField()


class EventAnalyticsSerializer(serializers.Serializer):
    total_operational_events = serializers.IntegerField()
    critical_events = serializers.IntegerField()
    event_type_distribution = serializers.ListField(child=serializers.DictField())
    severity_distribution = serializers.DictField()
    notification_delivery_count = serializers.IntegerField()
    notification_read_rate = serializers.FloatField()
    notification_acknowledgement_rate = serializers.FloatField()
    generated_at = serializers.DateTimeField()


class CorridorAnalyticsSerializer(serializers.Serializer):
    total_corridors = serializers.IntegerField()
    corridors = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.DateTimeField()


class TopPerformerSerializer(serializers.Serializer):
    top_transporters = serializers.ListField(child=serializers.DictField())
    top_drivers = serializers.ListField(child=serializers.DictField())
    top_corridors = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.DateTimeField()


class TrendAnalyticsSerializer(serializers.Serializer):
    metric = serializers.CharField()
    period = serializers.CharField()
    data = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.DateTimeField()


class GenericReportSerializer(serializers.Serializer):
    report_type = serializers.CharField()
    generated_at = serializers.DateTimeField()
    period = serializers.DictField()
    summary = serializers.DictField()
