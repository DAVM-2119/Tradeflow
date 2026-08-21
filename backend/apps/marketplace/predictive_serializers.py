from rest_framework import serializers
from apps.marketplace.models import PredictiveModel, PredictionRecord, PredictionType, RiskLevel


class PredictiveModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PredictiveModel
        fields = (
            'id',
            'name',
            'model_type',
            'version',
            'algorithm',
            'description',
            'is_active',
            'trained_at',
            'created_at',
            'updated_at',
        )


class PredictionRecordSerializer(serializers.ModelSerializer):
    prediction_model_details = PredictiveModelSerializer(source='prediction_model', read_only=True)

    class Meta:
        model = PredictionRecord
        fields = (
            'id',
            'shipment',
            'route',
            'prediction_model',
            'prediction_model_details',
            'prediction_type',
            'prediction_value',
            'risk_score',
            'risk_level',
            'confidence_score',
            'prediction_horizon_hours',
            'input_features',
            'explanation',
            'created_at',
            'expires_at',
        )


class ETAPredictionResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    prediction_available = serializers.BooleanField()
    prediction_type = serializers.CharField(default=PredictionType.ETA_DELAY)
    predicted_delay_minutes = serializers.IntegerField()
    delay_probability = serializers.FloatField()
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    factors = serializers.ListField(child=serializers.DictField(), required=False)
    reason = serializers.CharField(required=False)
    generated_at = serializers.CharField(required=False)


class ShipmentRiskResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    prediction_available = serializers.BooleanField()
    prediction_type = serializers.CharField(default=PredictionType.SHIPMENT_RISK)
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    explanation = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class RouteRiskResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    prediction_available = serializers.BooleanField()
    prediction_type = serializers.CharField(default=PredictionType.ROUTE_RISK)
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    major_risk_factors = serializers.ListField(child=serializers.DictField(), required=False)
    reason = serializers.CharField(required=False)
    generated_at = serializers.CharField(required=False)


class FuelPredictionResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    prediction_available = serializers.BooleanField()
    prediction_type = serializers.CharField(default=PredictionType.FUEL_CONSUMPTION)
    predicted_fuel_liters = serializers.FloatField()
    predicted_fuel_cost_etb = serializers.FloatField()
    fuel_efficiency_score = serializers.IntegerField()
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    generated_at = serializers.CharField()


class IncidentRiskResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    prediction_available = serializers.BooleanField()
    prediction_type = serializers.CharField(default=PredictionType.INCIDENT_RISK)
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    risk_factors = serializers.ListField(child=serializers.DictField())
    generated_at = serializers.CharField()


class OverallRiskSummarySerializer(serializers.Serializer):
    score = serializers.IntegerField()
    level = serializers.CharField()
    confidence = serializers.FloatField()


class ETASummarySerializer(serializers.Serializer):
    delay_probability = serializers.FloatField()
    predicted_delay_minutes = serializers.IntegerField()


class RouteSummarySerializer(serializers.Serializer):
    risk_score = serializers.IntegerField()
    level = serializers.CharField()


class FuelSummarySerializer(serializers.Serializer):
    predicted_liters = serializers.FloatField()
    predicted_cost_etb = serializers.FloatField()


class IncidentSummarySerializer(serializers.Serializer):
    risk_score = serializers.IntegerField()
    level = serializers.CharField()


class DeviationSummarySerializer(serializers.Serializer):
    status = serializers.CharField()
    distance_from_route_km = serializers.FloatField()


class OperationalRiskResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    overall_risk = OverallRiskSummarySerializer()
    eta = ETASummarySerializer()
    route = RouteSummarySerializer()
    fuel = FuelSummarySerializer()
    incident = IncidentSummarySerializer()
    deviation = DeviationSummarySerializer()
    generated_at = serializers.CharField()


class PredictionHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    prediction_type = serializers.CharField()
    model_name = serializers.CharField(source='prediction_model.name', allow_null=True)
    model_version = serializers.CharField(source='prediction_model.version', allow_null=True)
    risk_score = serializers.IntegerField()
    risk_level = serializers.CharField()
    confidence_score = serializers.FloatField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
