from rest_framework import serializers
from apps.marketplace.models import (
    AutomationRule,
    AutomationRecommendation,
    AutomationExecution,
)


class AutomationRuleSerializer(serializers.ModelSerializer):
    """
    Serializer for AutomationRule.
    """
    rule_type_display = serializers.CharField(source='get_rule_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model = AutomationRule
        fields = [
            'id',
            'name',
            'rule_type',
            'rule_type_display',
            'description',
            'is_active',
            'priority',
            'priority_display',
            'configuration',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AutomationExecutionSerializer(serializers.ModelSerializer):
    """
    Serializer for AutomationExecution audit record.
    """
    executed_by_email = serializers.EmailField(source='executed_by.email', read_only=True, default=None)

    class Meta:
        model = AutomationExecution
        fields = [
            'id',
            'recommendation',
            'executed_by',
            'executed_by_email',
            'action_type',
            'status',
            'result',
            'executed_at',
        ]
        read_only_fields = fields


class AutomationRecommendationSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for AutomationRecommendation.
    """
    recommendation_type_display = serializers.CharField(source='get_recommendation_type_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True, default=None)
    rule_name = serializers.CharField(source='rule.name', read_only=True, default=None)
    executions = AutomationExecutionSerializer(many=True, read_only=True)

    class Meta:
        model = AutomationRecommendation
        fields = [
            'id',
            'shipment',
            'rule',
            'rule_name',
            'recommendation_type',
            'recommendation_type_display',
            'priority',
            'priority_display',
            'status',
            'status_display',
            'title',
            'description',
            'recommended_action',
            'context_snapshot',
            'reviewed_by',
            'reviewed_by_email',
            'reviewed_at',
            'rejection_reason',
            'execution_result',
            'executions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'shipment',
            'rule',
            'rule_name',
            'recommendation_type',
            'priority',
            'status',
            'reviewed_by',
            'reviewed_at',
            'rejection_reason',
            'execution_result',
            'executions',
            'created_at',
            'updated_at',
        ]


class AutomationRecommendationListSerializer(serializers.ModelSerializer):
    """
    Compact list serializer for AutomationRecommendation.
    """
    recommendation_type_display = serializers.CharField(source='get_recommendation_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AutomationRecommendation
        fields = [
            'id',
            'shipment',
            'recommendation_type',
            'recommendation_type_display',
            'priority',
            'status',
            'status_display',
            'title',
            'created_at',
        ]
        read_only_fields = fields


class AutomationEvaluationResponseSerializer(serializers.Serializer):
    """
    Response serializer for evaluate shipment automation endpoint.
    """
    shipment_id = serializers.IntegerField()
    evaluated_rules = serializers.IntegerField()
    recommendations_created = serializers.IntegerField()
    recommendations_existing = serializers.IntegerField()
    recommendations = AutomationRecommendationSerializer(many=True)


class AutomationReviewInputSerializer(serializers.Serializer):
    """
    Input serializer for rejecting a recommendation.
    """
    reason = serializers.CharField(required=False, allow_blank=True, default="Rejected during manual operational review.")
