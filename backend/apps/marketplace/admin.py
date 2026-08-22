from django.contrib import admin
from apps.marketplace.models import (
    Vehicle,
    CargoLoad,
    Bid,
    Shipment,
    LocationUpdate,
    ShipmentMilestone,
    ShipmentDocument,
    ProofOfDelivery,
    FreightInvoice,
    FreightSettlement,
    Payment,
    TransporterPayout,
    PaymentDispute,
    OfflineSyncEvent,
    DriverIncidentReport,
    Rating,
    Route,
    RouteWaypoint,
    RouteRecalculation,
    PredictiveModel,
    PredictionRecord,
    PricingStrategy,
    PriceRecommendation,
    PricingMarketSnapshot,
    AutomationRule,
    AutomationRecommendation,
    AutomationExecution,
    OperationalEvent,
    Notification,
    NotificationPreference,
)


@admin.register(OperationalEvent)
class OperationalEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'severity', 'shipment', 'source', 'title', 'created_at')
    list_filter = ('event_type', 'severity', 'source', 'created_at')
    search_fields = ('title', 'description', 'idempotency_key', 'shipment__tracking_number')
    readonly_fields = ('event_type', 'severity', 'shipment', 'actor', 'source', 'title', 'description', 'payload', 'idempotency_key', 'created_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'recipient', 'notification_type', 'priority', 'title', 'is_read', 'is_acknowledged', 'created_at')
    list_filter = ('notification_type', 'priority', 'is_read', 'is_acknowledged', 'created_at')
    search_fields = ('recipient__email', 'title', 'message', 'shipment__tracking_number')
    readonly_fields = ('created_at',)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'route_alerts_enabled', 'eta_alerts_enabled', 'risk_alerts_enabled', 'incident_alerts_enabled', 'critical_alerts_enabled', 'updated_at')
    search_fields = ('user__email',)
    readonly_fields = ('updated_at',)


@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'rule_type', 'priority', 'is_active', 'created_at')
    list_filter = ('rule_type', 'priority', 'is_active', 'created_at')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AutomationRecommendation)
class AutomationRecommendationAdmin(admin.ModelAdmin):
    list_display = ('id', 'shipment', 'rule', 'recommendation_type', 'priority', 'status', 'created_at', 'reviewed_by')
    list_filter = ('status', 'priority', 'recommendation_type', 'created_at')
    search_fields = ('shipment__tracking_number', 'title', 'description')
    readonly_fields = (
        'shipment', 'rule', 'recommendation_type', 'priority', 'title', 'description',
        'recommended_action', 'context_snapshot', 'reviewed_by', 'reviewed_at',
        'rejection_reason', 'execution_result', 'created_at', 'updated_at'
    )


@admin.register(AutomationExecution)
class AutomationExecutionAdmin(admin.ModelAdmin):
    list_display = ('id', 'recommendation', 'action_type', 'status', 'executed_by', 'executed_at')
    list_filter = ('status', 'action_type', 'executed_at')
    search_fields = ('recommendation__shipment__tracking_number', 'action_type')
    readonly_fields = ('recommendation', 'executed_by', 'action_type', 'status', 'result', 'executed_at')







@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'transporter', 'vehicle_type', 'capacity_tonnes', 'fuel_type', 'is_active', 'created_at')
    list_filter = ('vehicle_type', 'fuel_type', 'is_active')
    search_fields = ('plate_number', 'transporter__company_name', 'insurance_policy_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CargoLoad)
class CargoLoadAdmin(admin.ModelAdmin):
    list_display = ('title', 'shipper', 'origin', 'destination', 'weight_tonnes', 'required_vehicle_type', 'target_price', 'status', 'created_at')
    list_filter = ('status', 'required_vehicle_type', 'origin', 'destination')
    search_fields = ('title', 'shipper__company_name', 'origin', 'destination', 'cargo_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('load', 'transporter', 'proposed_vehicle', 'amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('load__title', 'transporter__company_name', 'notes')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('tracking_number', 'load', 'transporter', 'vehicle', 'driver', 'status', 'estimated_arrival_at', 'eta_confidence', 'created_at')
    list_filter = ('status', 'origin', 'destination')
    search_fields = ('tracking_number', 'transporter__company_name', 'driver__user__email', 'origin', 'destination')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(LocationUpdate)
class LocationUpdateAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'latitude', 'longitude', 'speed_kmh', 'location_name', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('shipment__tracking_number', 'location_name')
    readonly_fields = ('timestamp',)


@admin.register(ShipmentMilestone)
class ShipmentMilestoneAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'status', 'location_name', 'updated_by', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('shipment__tracking_number', 'notes', 'location_name')
    readonly_fields = ('timestamp',)


@admin.register(ShipmentDocument)
class ShipmentDocumentAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'document_type', 'file_name', 'file_size_bytes', 'mime_type', 'uploaded_by', 'created_at')
    list_filter = ('document_type', 'created_at')
    search_fields = ('file_name', 'shipment__tracking_number', 'uploaded_by__email')
    readonly_fields = ('created_at', 'updated_at', 'checksum_sha256')


@admin.register(ProofOfDelivery)
class ProofOfDeliveryAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'recipient_name', 'cargo_condition', 'confirmation_status', 'confirmed_by_shipper', 'delivered_at')
    list_filter = ('cargo_condition', 'confirmation_status', 'delivered_at')
    search_fields = ('recipient_name', 'shipment__tracking_number', 'dispute_reason')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FreightInvoice)
class FreightInvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'shipment', 'payer', 'subtotal_amount', 'total_amount', 'status', 'issue_date', 'due_date')
    list_filter = ('status', 'currency', 'issue_date')
    search_fields = ('invoice_number', 'shipment__tracking_number', 'payer__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FreightSettlement)
class FreightSettlementAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'gross_freight_amount', 'commission_rate', 'platform_commission_amount', 'transporter_net_payable', 'status', 'settled_at')
    list_filter = ('status', 'created_at')
    search_fields = ('shipment__tracking_number', 'invoice__invoice_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('idempotency_key', 'shipment', 'payer', 'amount', 'currency', 'provider', 'provider_transaction_id', 'status', 'initiated_at')
    list_filter = ('status', 'provider', 'currency', 'initiated_at')
    search_fields = ('idempotency_key', 'provider_transaction_id', 'shipment__tracking_number', 'payer__email')
    readonly_fields = ('created_at', 'updated_at', 'idempotency_key', 'provider_transaction_id')


@admin.register(TransporterPayout)
class TransporterPayoutAdmin(admin.ModelAdmin):
    list_display = ('payout_reference', 'transporter', 'gross_amount', 'commission_amount', 'net_payout_amount', 'status', 'processed_at')
    list_filter = ('status', 'scheduled_at', 'processed_at')
    search_fields = ('payout_reference', 'transporter__company_name', 'settlement__shipment__tracking_number')
    readonly_fields = ('created_at', 'updated_at', 'payout_reference')


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    list_display = ('settlement', 'raised_by', 'status', 'resolved_by', 'created_at', 'resolved_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reason', 'resolution_notes', 'raised_by__email', 'settlement__shipment__tracking_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OfflineSyncEvent)
class OfflineSyncEventAdmin(admin.ModelAdmin):
    list_display = ('client_event_id', 'user', 'event_type', 'shipment', 'status', 'server_record_id', 'client_created_at', 'server_received_at')
    list_filter = ('event_type', 'status', 'server_received_at')
    search_fields = ('client_event_id', 'user__email', 'shipment__tracking_number', 'device_id')
    readonly_fields = ('client_event_id', 'server_received_at', 'processed_at', 'created_at', 'updated_at')


@admin.register(DriverIncidentReport)
class DriverIncidentReportAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'incident_type', 'driver', 'reported_by', 'location_name', 'reported_at')
    list_filter = ('incident_type', 'reported_at')
    search_fields = ('description', 'location_name', 'shipment__tracking_number', 'driver__user__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('rater', 'ratee', 'stars', 'shipment', 'created_at')
    list_filter = ('stars',)
    search_fields = ('rater__email', 'ratee__email', 'comment')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('id', 'shipment', 'origin', 'destination', 'total_distance_km', 'estimated_duration_hours', 'status', 'is_active', 'created_at')
    list_filter = ('status', 'is_active', 'created_at')
    search_fields = ('shipment__tracking_number', 'origin', 'destination')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(RouteWaypoint)
class RouteWaypointAdmin(admin.ModelAdmin):
    list_display = ('id', 'route', 'sequence', 'location_name', 'latitude', 'longitude', 'distance_from_previous_km', 'travel_time_from_previous_hours')
    list_filter = ('sequence',)
    search_fields = ('route__shipment__tracking_number', 'location_name')


@admin.register(RouteRecalculation)
class RouteRecalculationAdmin(admin.ModelAdmin):
    list_display = ('id', 'shipment', 'previous_route', 'new_route', 'triggered_by', 'incident', 'previous_distance_km', 'new_distance_km', 'recalculated_at')
    list_filter = ('recalculated_at',)
    search_fields = ('shipment__tracking_number', 'reason', 'triggered_by__email')
    readonly_fields = ('recalculated_at',)


@admin.register(PredictiveModel)
class PredictiveModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'model_type', 'algorithm', 'is_active', 'trained_at', 'created_at')
    list_filter = ('model_type', 'is_active', 'created_at')
    search_fields = ('name', 'version', 'algorithm', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PredictionRecord)
class PredictionRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'prediction_type', 'shipment', 'risk_level', 'risk_score', 'confidence_score', 'prediction_model', 'created_at')
    list_filter = ('prediction_type', 'risk_level', 'created_at')
    search_fields = ('shipment__tracking_number', 'prediction_model__name')
    readonly_fields = ('shipment', 'route', 'prediction_model', 'prediction_type', 'prediction_value', 'risk_score', 'risk_level', 'confidence_score', 'prediction_horizon_hours', 'input_features', 'explanation', 'created_at')


@admin.register(PricingStrategy)
class PricingStrategyAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'is_active', 'base_rate_per_km', 'minimum_rate_per_km', 'maximum_rate_per_km', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'version', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PriceRecommendation)
class PriceRecommendationAdmin(admin.ModelAdmin):
    list_display = ('id', 'shipment', 'recommended_price_etb', 'minimum_price_etb', 'maximum_price_etb', 'market_pressure', 'risk_level', 'pricing_confidence_score', 'created_at')
    list_filter = ('market_pressure', 'risk_level', 'created_at')
    search_fields = ('shipment__tracking_number',)
    readonly_fields = (
        'shipment', 'pricing_strategy', 'recommended_price_etb', 'minimum_price_etb', 'maximum_price_etb',
        'base_price_etb', 'distance_adjustment_etb', 'fuel_adjustment_etb', 'risk_adjustment_etb',
        'market_adjustment_etb', 'pricing_confidence_score', 'market_pressure', 'risk_level',
        'factors', 'calculation_snapshot', 'created_at'
    )


@admin.register(PricingMarketSnapshot)
class PricingMarketSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'origin_region', 'destination_region', 'market_pressure', 'active_load_count', 'active_bid_count', 'available_transporter_count', 'snapshot_at')
    list_filter = ('market_pressure', 'snapshot_at')
    search_fields = ('origin_region', 'destination_region')
    readonly_fields = ('snapshot_at', 'created_at')


# ============================================================================
# PHASE 18: EXTERNAL INTEGRATIONS & WEBHOOKS ADMIN REGISTRATIONS
# ============================================================================
from apps.marketplace.models import ExternalIntegration, WebhookEndpoint, WebhookDelivery, InboundWebhookEvent


@admin.register(ExternalIntegration)
class ExternalIntegrationAdmin(admin.ModelAdmin):
    list_display = ('name', 'integration_type', 'status', 'base_url', 'created_by', 'last_success_at', 'last_failure_at', 'created_at')
    list_filter = ('integration_type', 'status', 'created_at')
    search_fields = ('name', 'base_url', 'created_by__email')
    readonly_fields = ('created_at', 'updated_at', 'last_success_at', 'last_failure_at')


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ('name', 'integration', 'url', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'url', 'integration__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ('id', 'webhook_endpoint', 'event_type', 'status', 'attempt_count', 'max_attempts', 'response_status', 'created_at', 'delivered_at')
    list_filter = ('status', 'event_type', 'created_at')
    search_fields = ('event_type', 'idempotency_key', 'webhook_endpoint__name', 'webhook_endpoint__url')
    readonly_fields = ('webhook_endpoint', 'event_type', 'payload', 'idempotency_key', 'status', 'attempt_count', 'max_attempts', 'last_attempt_at', 'next_retry_at', 'response_status', 'response_body', 'error_message', 'created_at', 'updated_at', 'delivered_at')


@admin.register(InboundWebhookEvent)
class InboundWebhookEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'integration', 'event_type', 'external_event_id', 'signature_valid', 'processing_status', 'received_at', 'processed_at')
    list_filter = ('signature_valid', 'processing_status', 'event_type', 'received_at')
    search_fields = ('event_type', 'external_event_id', 'idempotency_key', 'integration__name')
    readonly_fields = ('integration', 'event_type', 'external_event_id', 'payload', 'signature_valid', 'processing_status', 'idempotency_key', 'received_at', 'processed_at', 'error_message')


# ============================================================================
# PHASE 19: SECURITY, COMPLIANCE & GOVERNANCE ADMIN REGISTRATIONS
# ============================================================================
from apps.marketplace.models import SecurityAuditEvent, SecurityIncident, SecurityPolicy


@admin.register(SecurityAuditEvent)
class SecurityAuditEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'severity', 'actor', 'actor_role', 'target_user', 'action', 'request_id', 'created_at')
    list_filter = ('severity', 'event_type', 'actor_role', 'created_at')
    search_fields = ('action', 'description', 'request_id', 'ip_address', 'actor__email', 'target_user__email')
    readonly_fields = ('event_type', 'severity', 'actor', 'actor_role', 'target_user', 'target_model', 'target_object_id', 'action', 'description', 'request_id', 'ip_address', 'user_agent', 'endpoint', 'http_method', 'metadata', 'previous_hash', 'event_hash', 'created_at')


@admin.register(SecurityIncident)
class SecurityIncidentAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'incident_type', 'severity', 'status', 'detected_by', 'assigned_to', 'detected_at', 'resolved_at')
    list_filter = ('severity', 'status', 'incident_type', 'detected_at')
    search_fields = ('title', 'description', 'correlation_id', 'resolution_notes')
    readonly_fields = ('detected_at', 'created_at', 'updated_at')


@admin.register(SecurityPolicy)
class SecurityPolicyAdmin(admin.ModelAdmin):
    list_display = ('name', 'policy_type', 'enabled', 'threshold', 'window_seconds', 'severity', 'updated_at')
    list_filter = ('enabled', 'severity', 'policy_type')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')





