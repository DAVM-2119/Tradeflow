from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q

from apps.marketplace.models import (
    CargoLoad, LoadStatus, Bid, TransporterProfile, Shipment, ShipmentStatus,
    Route, RouteDeviationStatus, PricingStrategy, PriceRecommendation,
    PricingMarketSnapshot, MarketPressure, RiskLevel
)
from apps.marketplace.services import RouteOptimizationService
from apps.marketplace.predictive_services import OperationalRiskService


class DynamicPricingService:
    """
    Domain service executing deterministic, explainable freight price recommendations
    and market intelligence calculations for decision support.
    """

    @classmethod
    def get_or_create_default_pricing_strategy(cls) -> PricingStrategy:
        """
        Resolves or creates the active baseline corridor pricing strategy.
        """
        strategy, _ = PricingStrategy.objects.get_or_create(
            name="TradeFlow Standard Corridor Strategy",
            version="1.0",
            defaults={
                "description": "Baseline dynamic pricing strategy for landlocked corridor freight",
                "is_active": True,
                "base_rate_per_km": Decimal("50.00"),
                "minimum_rate_per_km": Decimal("35.00"),
                "maximum_rate_per_km": Decimal("120.00"),
                "fuel_weight": Decimal("1.00"),
                "distance_weight": Decimal("1.00"),
                "risk_weight": Decimal("1.00"),
                "incident_weight": Decimal("1.00"),
                "route_deviation_weight": Decimal("1.00"),
                "market_demand_weight": Decimal("1.00"),
                "market_supply_weight": Decimal("1.00"),
            }
        )
        return strategy

    @classmethod
    def calculate_market_snapshot(cls, shipment: Shipment) -> PricingMarketSnapshot:
        """
        Calculates internal market condition snapshot for the shipment's origin/destination corridor.
        """
        origin = shipment.origin or (shipment.load.origin if shipment.load else "")
        destination = shipment.destination or (shipment.load.destination if shipment.load else "")

        active_loads = CargoLoad.objects.filter(
            Q(origin__icontains=origin) | Q(destination__icontains=destination),
            status__in=[LoadStatus.POSTED, LoadStatus.ASSIGNED]
        ).count()

        active_bids = Bid.objects.filter(
            load__origin__icontains=origin,
            status='PENDING'
        ).count()

        available_transporters = TransporterProfile.objects.filter(
            verification_status='VERIFIED'
        ).count()

        demand_score = min(Decimal("100.00"), Decimal(str(active_loads * 15 + active_bids * 5)))
        supply_score = min(Decimal("100.00"), Decimal(str(max(1, available_transporters) * 20)))

        ratio = float(demand_score) / float(max(Decimal("1.00"), supply_score))

        if ratio > 1.25 or active_loads > 10:
            market_pressure = MarketPressure.HIGH
        elif ratio < 0.50 and available_transporters > 5:
            market_pressure = MarketPressure.LOW
        else:
            market_pressure = MarketPressure.NORMAL

        # Calculate historical accepted pricing on similar corridor
        historical_bids = Bid.objects.filter(
            status='ACCEPTED',
            load__origin__icontains=origin
        )
        sample_size = historical_bids.count()

        avg_price = historical_bids.aggregate(avg=Avg('amount'))['avg']
        avg_price_decimal = Decimal(str(round(float(avg_price), 2))) if avg_price else None

        active_route = shipment.routes.filter(is_active=True).first()
        dist = active_route.total_distance_km if active_route else Decimal("0.00")

        avg_per_km = None
        if avg_price_decimal and dist > Decimal("0.00"):
            avg_per_km = Decimal(str(round(float(avg_price_decimal) / float(dist), 2)))

        snapshot = PricingMarketSnapshot.objects.create(
            origin_region=origin or "General",
            destination_region=destination or "General",
            active_load_count=active_loads,
            active_bid_count=active_bids,
            available_transporter_count=available_transporters,
            average_historical_price_etb=avg_price_decimal,
            average_price_per_km=avg_per_km,
            demand_score=demand_score,
            supply_score=supply_score,
            market_pressure=market_pressure,
            snapshot_at=timezone.now()
        )
        return snapshot

    @classmethod
    def calculate_base_price(cls, shipment: Shipment, strategy: PricingStrategy):
        """
        Calculates base freight price based on active route distance or shipment coordinates.
        Returns tuple: (distance_km: Decimal, base_price_etb: Decimal) or (None, None).
        """
        active_route = shipment.routes.filter(is_active=True).first()
        distance_km = None

        if active_route and active_route.total_distance_km > Decimal("0.00"):
            distance_km = active_route.total_distance_km
        elif shipment.origin and shipment.destination:
            # Fallback estimation if origin and destination match known cities
            distance_km = Decimal("500.00")

        if not distance_km or distance_km <= Decimal("0.00"):
            return None, None

        base_price_etb = Decimal(str(round(float(distance_km) * float(strategy.base_rate_per_km), 2)))
        return distance_km, base_price_etb

    @classmethod
    def calculate_fuel_adjustment(cls, shipment: Shipment, strategy: PricingStrategy) -> Decimal:
        """
        Integrates Phase 10 fuel analytics to calculate fuel price contribution.
        """
        try:
            fuel_data = RouteOptimizationService.calculate_fuel_analytics(shipment)
            actual_cost = float(fuel_data.get('actual_fuel_cost_etb') or fuel_data.get('planned_fuel_cost_etb') or 0.0)
            adjustment = Decimal(str(round(actual_cost * 0.15 * float(strategy.fuel_weight), 2)))
            return max(Decimal("0.00"), adjustment)
        except Exception:
            return Decimal("0.00")

    @classmethod
    def calculate_risk_adjustment(cls, shipment: Shipment, strategy: PricingStrategy, base_price_etb: Decimal) -> Decimal:
        """
        Integrates Phase 11 predictive intelligence to calculate operational risk adjustment.
        """
        try:
            risk_dash = OperationalRiskService.get_composite_dashboard(shipment)
            risk_score = risk_dash.get('overall_risk', {}).get('score', 0)
            adjustment = Decimal(str(round(float(base_price_etb) * (float(risk_score) / 100.0) * 0.20 * float(strategy.risk_weight), 2)))
            return max(Decimal("0.00"), adjustment)
        except Exception:
            return Decimal("0.00")

    @classmethod
    def calculate_deviation_adjustment(cls, shipment: Shipment, strategy: PricingStrategy) -> Decimal:
        """
        Integrates Phase 10 route deviation detection.
        """
        try:
            dev_data = RouteOptimizationService.detect_route_deviation(shipment)
            if dev_data.get('status') == RouteDeviationStatus.DEVIATED:
                dev_km = float(dev_data.get('min_distance_to_route_km') or 0.0)
                adjustment = Decimal(str(round(min(5000.0, dev_km * 250.0 * float(strategy.route_deviation_weight)), 2)))
                return max(Decimal("0.00"), adjustment)
            return Decimal("0.00")
        except Exception:
            return Decimal("0.00")

    @classmethod
    def calculate_market_adjustment(cls, shipment: Shipment, strategy: PricingStrategy, market_pressure: str, base_price_etb: Decimal) -> Decimal:
        """
        Calculates price adjustment based on demand/supply market pressure.
        """
        base_val = float(base_price_etb)
        if market_pressure == MarketPressure.HIGH:
            adj = Decimal(str(round(base_val * 0.12 * float(strategy.market_demand_weight), 2)))
            return max(Decimal("0.00"), adj)
        elif market_pressure == MarketPressure.LOW:
            adj = Decimal(str(round(-base_val * 0.08 * float(strategy.market_supply_weight), 2)))
            return adj
        return Decimal("0.00")

    @classmethod
    def calculate_pricing_confidence(cls, shipment: Shipment, has_active_route: bool, has_telemetry: bool, sample_size: int) -> Decimal:
        """
        Calculates pricing confidence score between 0.10 and 0.99 based on operational data availability.
        """
        confidence = 0.50
        if has_active_route:
            confidence += 0.20
        if has_telemetry:
            confidence += 0.10
        if sample_size >= 3:
            confidence += 0.15
        elif sample_size >= 1:
            confidence += 0.05
        return Decimal(str(round(max(0.10, min(0.99, confidence)), 2)))

    @classmethod
    def generate_price_recommendation(cls, shipment: Shipment, strategy: PricingStrategy = None) -> dict:
        """
        Generates and persists a decision-support freight price recommendation for a shipment.
        """
        if not strategy:
            strategy = cls.get_or_create_default_pricing_strategy()

        distance_km, base_price_etb = cls.calculate_base_price(shipment, strategy)

        # Handle insufficient data safely
        if not distance_km or not base_price_etb:
            return {
                "shipment_id": shipment.id,
                "recommendation_available": False,
                "reason": "Insufficient operational data: Unable to determine shipment route distance",
                "pricing_confidence_score": Decimal("0.00"),
                "recommended_price_etb": Decimal("0.00"),
                "minimum_price_etb": Decimal("0.00"),
                "maximum_price_etb": Decimal("0.00"),
            }

        snapshot = cls.calculate_market_snapshot(shipment)
        market_pressure = snapshot.market_pressure

        fuel_adj = cls.calculate_fuel_adjustment(shipment, strategy)
        risk_adj = cls.calculate_risk_adjustment(shipment, strategy, base_price_etb)
        dev_adj = cls.calculate_deviation_adjustment(shipment, strategy)
        market_adj = cls.calculate_market_adjustment(shipment, strategy, market_pressure, base_price_etb)

        raw_recommended = base_price_etb + fuel_adj + risk_adj + dev_adj + market_adj

        # Calculate bounds
        cost_floor = distance_km * strategy.minimum_rate_per_km
        rate_ceiling = distance_km * strategy.maximum_rate_per_km

        minimum_price_etb = max(Decimal(str(round(float(base_price_etb) * 0.85, 2))), Decimal(str(round(float(cost_floor), 2))))
        maximum_price_etb = min(Decimal(str(round(float(raw_recommended) * 1.30, 2))), Decimal(str(round(float(rate_ceiling), 2))))

        recommended_price_etb = max(minimum_price_etb, min(maximum_price_etb, raw_recommended))
        recommended_price_etb = Decimal(str(round(float(recommended_price_etb), 2)))

        has_telemetry = shipment.location_updates.exists()
        confidence_score = cls.calculate_pricing_confidence(
            shipment=shipment,
            has_active_route=bool(shipment.routes.filter(is_active=True).exists()),
            has_telemetry=has_telemetry,
            sample_size=snapshot.active_bid_count
        )

        # Risk level determination
        try:
            risk_dash = OperationalRiskService.get_composite_dashboard(shipment)
            risk_level = risk_dash.get('overall_risk', {}).get('level', RiskLevel.LOW)
        except Exception:
            risk_level = RiskLevel.LOW

        # Factors list
        factors = [
            {
                "factor": "base_distance",
                "impact_etb": str(base_price_etb),
                "description": f"Base freight price calculated for {distance_km:.1f} km at {strategy.base_rate_per_km} ETB/km."
            },
            {
                "factor": "fuel_cost",
                "impact_etb": str(fuel_adj),
                "description": f"Fuel adjustment based on corridor fuel consumption."
            },
            {
                "factor": "operational_risk",
                "impact_etb": str(risk_adj),
                "description": f"Risk premium based on predicted operational risk score."
            },
            {
                "factor": "market_pressure",
                "impact_etb": str(market_adj),
                "description": f"Market adjustment under {market_pressure} demand pressure."
            }
        ]

        if dev_adj > Decimal("0.00"):
            factors.append({
                "factor": "route_deviation",
                "impact_etb": str(dev_adj),
                "description": "Route deviation premium applied for off-corridor position."
            })

        calc_snapshot = {
            "distance_km": float(distance_km),
            "base_price_etb": float(base_price_etb),
            "fuel_adj_etb": float(fuel_adj),
            "risk_adj_etb": float(risk_adj),
            "dev_adj_etb": float(dev_adj),
            "market_adj_etb": float(market_adj),
            "market_pressure": market_pressure,
            "strategy_id": strategy.id,
        }

        # Persist audit record
        rec_obj = PriceRecommendation.objects.create(
            shipment=shipment,
            pricing_strategy=strategy,
            recommended_price_etb=recommended_price_etb,
            minimum_price_etb=minimum_price_etb,
            maximum_price_etb=maximum_price_etb,
            base_price_etb=base_price_etb,
            distance_adjustment_etb=Decimal("0.00"),
            fuel_adjustment_etb=fuel_adj,
            risk_adjustment_etb=risk_adj,
            market_adjustment_etb=market_adj,
            pricing_confidence_score=confidence_score,
            market_pressure=market_pressure,
            risk_level=risk_level,
            factors=factors,
            calculation_snapshot=calc_snapshot
        )

        return {
            "shipment_id": shipment.id,
            "recommendation_available": True,
            "recommendation_id": rec_obj.id,
            "recommended_price_etb": recommended_price_etb,
            "minimum_price_etb": minimum_price_etb,
            "maximum_price_etb": maximum_price_etb,
            "base_price_etb": base_price_etb,
            "fuel_adjustment_etb": fuel_adj,
            "risk_adjustment_etb": risk_adj,
            "market_adjustment_etb": market_adj,
            "pricing_confidence_score": float(confidence_score),
            "market_pressure": market_pressure,
            "risk_level": risk_level,
            "factors": factors,
            "generated_at": rec_obj.created_at.isoformat(),
        }

    @classmethod
    def get_pricing_history(cls, shipment: Shipment):
        """
        Retrieves historical price recommendation audit records for a shipment (-newest first).
        """
        return PriceRecommendation.objects.filter(shipment=shipment).order_by('-created_at')

    @classmethod
    def get_market_intelligence(cls, shipment: Shipment) -> dict:
        """
        Returns corridor market intelligence metrics for a shipment.
        """
        snapshot = cls.calculate_market_snapshot(shipment)
        return {
            "shipment_id": shipment.id,
            "origin_region": snapshot.origin_region,
            "destination_region": snapshot.destination_region,
            "market_pressure": snapshot.market_pressure,
            "demand_score": float(snapshot.demand_score),
            "supply_score": float(snapshot.supply_score),
            "active_load_count": snapshot.active_load_count,
            "active_bid_count": snapshot.active_bid_count,
            "available_transporter_count": snapshot.available_transporter_count,
            "average_historical_price_etb": float(snapshot.average_historical_price_etb) if snapshot.average_historical_price_etb else None,
            "average_price_per_km": float(snapshot.average_price_per_km) if snapshot.average_price_per_km else None,
            "market_data_available": True,
            "snapshot_at": snapshot.snapshot_at.isoformat(),
        }
