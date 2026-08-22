from rest_framework import serializers
from apps.marketplace.models import (
    AIInsight, AIRecommendation, AIGenerationRequest,
    AIModelConfiguration, AIPromptVersion, AIUsageRecord
)


class AIInsightSerializer(serializers.ModelSerializer):
    user_email = serializers.ReadOnlyField(source='user.email')

    class Meta:
        model = AIInsight
        fields = [
            'id', 'user', 'user_email', 'shipment', 'insight_type', 'title',
            'summary', 'detailed_analysis', 'confidence_score', 'severity',
            'evidence', 'model_name', 'prompt_version', 'request_id',
            'created_at', 'expires_at'
        ]
        read_only_fields = fields


class AIRecommendationSerializer(serializers.ModelSerializer):
    user_email = serializers.ReadOnlyField(source='user.email')

    class Meta:
        model = AIRecommendation
        fields = [
            'id', 'user', 'user_email', 'shipment', 'recommendation_type',
            'recommendation', 'rationale', 'evidence', 'confidence_score',
            'status', 'severity', 'model_name', 'prompt_version', 'request_id',
            'created_at', 'expires_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'expires_at']


class AIShipmentSummarySerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    tracking_number = serializers.CharField()
    status = serializers.CharField()
    operational_health = serializers.CharField()
    summary = serializers.CharField()
    key_findings = serializers.ListField(child=serializers.CharField(), default=list)
    risks = serializers.ListField(child=serializers.CharField(), default=list)
    recommended_attention = serializers.CharField()
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIRiskExplanationSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    risk_level = serializers.CharField()
    risk_score = serializers.FloatField()
    summary = serializers.CharField()
    contributing_factors = serializers.ListField(child=serializers.DictField(), default=list)
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    potential_consequences = serializers.ListField(child=serializers.CharField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIIncidentAnalysisSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    incident_count = serializers.IntegerField()
    summary = serializers.CharField()
    incidents_analyzed = serializers.ListField(child=serializers.DictField(), default=list)
    probable_causes = serializers.ListField(child=serializers.CharField(), default=list)
    operational_impact = serializers.CharField()
    suggested_human_actions = serializers.ListField(child=serializers.CharField(), default=list)
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIRouteExplanationSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    route_status = serializers.CharField()
    progress_percentage = serializers.FloatField()
    eta = serializers.DateTimeField(allow_null=True)
    summary = serializers.CharField()
    telemetry_quality = serializers.CharField()
    potential_delays = serializers.ListField(child=serializers.CharField(), default=list)

    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIPricingExplanationSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    market_pressure = serializers.CharField()
    recommended_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    summary = serializers.CharField()
    pricing_factors = serializers.ListField(child=serializers.DictField(), default=list)
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIExecutiveSummarySerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    summary = serializers.CharField()
    operational_health = serializers.CharField()
    shipment_metrics = serializers.DictField()
    financial_trends = serializers.DictField()
    risk_and_incidents = serializers.DictField()
    key_recommendations = serializers.ListField(child=serializers.CharField(), default=list)
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    request_id = serializers.CharField()


class AIQueryRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)


class AIQueryResponseSerializer(serializers.Serializer):
    question = serializers.CharField()
    answer = serializers.CharField()
    evidence = serializers.ListField(child=serializers.DictField(), default=list)
    confidence = serializers.FloatField()
    limitations = serializers.ListField(child=serializers.CharField(), default=list)
    model = serializers.CharField()
    prompt_version = serializers.CharField()
    generated_at = serializers.DateTimeField()
    request_id = serializers.CharField()


class AIUsageRecordSerializer(serializers.ModelSerializer):
    user_email = serializers.ReadOnlyField(source='user.email')

    class Meta:
        model = AIUsageRecord
        fields = [
            'id', 'user', 'user_email', 'request_id', 'provider', 'model',
            'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
            'estimated_cost', 'created_at'
        ]
        read_only_fields = fields


class AIOverviewSerializer(serializers.Serializer):
    total_requests = serializers.IntegerField()
    successful_generations = serializers.IntegerField()
    failed_generations = serializers.IntegerField()
    timeout_count = serializers.IntegerField()
    avg_latency_ms = serializers.FloatField()
    total_tokens = serializers.IntegerField()
    total_estimated_cost = serializers.DecimalField(max_digits=12, decimal_places=4)
    total_insights = serializers.IntegerField()
    total_recommendations = serializers.IntegerField()
    pending_recommendations = serializers.IntegerField()
    provider_health = serializers.CharField()
    generated_at = serializers.DateTimeField()


class AIHealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    provider = serializers.CharField()
    model = serializers.CharField()
    latency_ms = serializers.IntegerField()
    checked_at = serializers.DateTimeField()
