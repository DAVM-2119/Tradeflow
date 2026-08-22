from rest_framework import serializers
from decimal import Decimal
from apps.marketplace.models import PricingStrategy, PriceRecommendation, PricingMarketSnapshot, MarketPressure, RiskLevel


class PricingStrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingStrategy
        fields = [
            'id', 'name', 'version', 'description', 'is_active',
            'base_rate_per_km', 'minimum_rate_per_km', 'maximum_rate_per_km',
            'fuel_weight', 'distance_weight', 'risk_weight', 'incident_weight',
            'route_deviation_weight', 'market_demand_weight', 'market_supply_weight',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PricingFactorSerializer(serializers.Serializer):
    factor = serializers.CharField()
    impact_etb = serializers.CharField()
    description = serializers.CharField()


class PriceRecommendationSerializer(serializers.ModelSerializer):
    factors = PricingFactorSerializer(many=True, read_only=True)

    class Meta:
        model = PriceRecommendation
        fields = [
            'id', 'shipment', 'pricing_strategy', 'recommended_price_etb',
            'minimum_price_etb', 'maximum_price_etb', 'base_price_etb',
            'fuel_adjustment_etb', 'risk_adjustment_etb', 'market_adjustment_etb',
            'pricing_confidence_score', 'market_pressure', 'risk_level',
            'factors', 'calculation_snapshot', 'created_at'
        ]
        read_only_fields = fields


class PricingRecommendationResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    recommendation_available = serializers.BooleanField()
    recommendation_id = serializers.IntegerField(required=False)
    recommended_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2)
    minimum_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2)
    maximum_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2)
    base_price_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    fuel_adjustment_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    risk_adjustment_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    market_adjustment_etb = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    pricing_confidence_score = serializers.FloatField()
    market_pressure = serializers.ChoiceField(choices=MarketPressure.choices)
    risk_level = serializers.ChoiceField(choices=RiskLevel.choices)
    factors = PricingFactorSerializer(many=True)
    generated_at = serializers.CharField()


class PricingMarketSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingMarketSnapshot
        fields = [
            'id', 'origin_region', 'destination_region', 'active_load_count',
            'active_bid_count', 'available_transporter_count',
            'average_historical_price_etb', 'average_price_per_km',
            'demand_score', 'supply_score', 'market_pressure',
            'snapshot_at', 'created_at'
        ]
        read_only_fields = fields


class MarketIntelligenceResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    origin_region = serializers.CharField()
    destination_region = serializers.CharField()
    market_pressure = serializers.ChoiceField(choices=MarketPressure.choices)
    demand_score = serializers.FloatField()
    supply_score = serializers.FloatField()
    active_load_count = serializers.IntegerField()
    active_bid_count = serializers.IntegerField()
    available_transporter_count = serializers.IntegerField()
    average_historical_price_etb = serializers.FloatField(allow_null=True)
    average_price_per_km = serializers.FloatField(allow_null=True)
    market_data_available = serializers.BooleanField()
    snapshot_at = serializers.CharField()
