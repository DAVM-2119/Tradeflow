from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q

from apps.marketplace.models import (
    Shipment, ShipmentStatus, Route, RouteStatus, RouteDeviationStatus, LocationUpdate,
    DriverIncidentReport, IncidentType, PredictiveModel, PredictionRecord, PredictionType, RiskLevel
)
from apps.marketplace.services import RouteOptimizationService, TrackingService


class PredictiveModelRegistryService:
    """
    Service for resolving and registering default predictive models.
    """
    @classmethod
    def get_or_create_default_model(cls, prediction_type: str) -> PredictiveModel:
        type_names = {
            PredictionType.ETA_DELAY: ("TradeFlow Baseline ETA Predictor", "1.0"),
            PredictionType.SHIPMENT_RISK: ("TradeFlow Delay Risk Scorer", "1.0"),
            PredictionType.ROUTE_RISK: ("TradeFlow Corridor Risk Evaluator", "1.0"),
            PredictionType.FUEL_CONSUMPTION: ("TradeFlow Fuel Analytics Predictor", "1.0"),
            PredictionType.INCIDENT_RISK: ("TradeFlow Incident Likelihood Model", "1.0"),
            PredictionType.OPERATIONAL_RISK: ("TradeFlow Composite Operational Risk Engine", "1.0"),
        }
        name, version = type_names.get(prediction_type, ("TradeFlow Generic Predictive Model", "1.0"))

        model_obj, _ = PredictiveModel.objects.get_or_create(
            name=name,
            version=version,
            defaults={
                'model_type': prediction_type,
                'algorithm': 'Rule-Based Weighted Empirical Heuristic',
                'description': f'Deterministic baseline risk model for {prediction_type}',
                'is_active': True,
                'trained_at': timezone.now(),
            }
        )
        return model_obj


class ETADelayPredictionService:
    """
    Predicts ETA delays, delay probabilities, and confidence scores based on GPS progress, waypoints, and deviations.
    """
    @classmethod
    def predict_eta_delay(cls, shipment: Shipment) -> dict:
        active_route = shipment.routes.filter(is_active=True).first()
        has_telemetry = shipment.location_updates.exists()

        # Handle insufficient data safely
        if not active_route and not has_telemetry:
            return {
                "shipment_id": shipment.id,
                "prediction_available": False,
                "reason": "Insufficient operational data: No active route or GPS telemetry found for shipment",
                "confidence_score": Decimal('0.00'),
                "predicted_delay_minutes": 0,
                "delay_probability": Decimal('0.00'),
                "risk_score": 0,
                "risk_level": RiskLevel.LOW,
            }

        # Extract features
        eta_data = RouteOptimizationService.calculate_eta(shipment)
        deviation_data = RouteOptimizationService.detect_route_deviation(shipment)

        total_distance = float(eta_data.get('total_route_distance_km') or 0.0)
        remaining_distance = float(eta_data.get('remaining_distance_km') or 0.0)
        average_speed = float(eta_data.get('average_speed_kmh') or 50.0)

        # Check latest telemetry timestamp for freshness
        latest_ping = shipment.location_updates.order_by('-timestamp').first()
        gps_freshness_minutes = (timezone.now() - latest_ping.timestamp).total_seconds() / 60.0 if latest_ping else 999.0

        # Calculate delay heuristic
        delay_minutes = 0
        factors = []
        risk_score = 10

        # 1. Route Deviation Factor
        if deviation_data.get('status') == RouteDeviationStatus.DEVIATED:
            dev_dist = float(deviation_data.get('min_distance_to_route_km') or 15.0)
            added_delay = int(dev_dist * 4.0)  # 4 min delay per km off-route
            delay_minutes += added_delay
            risk_score += 35
            factors.append({
                "factor": "route_deviation",
                "impact": 35,
                "description": f"Shipment is currently deviated {dev_dist:.1f} km from the planned corridor."
            })

        # 2. Incident Factor
        incidents_count = shipment.incident_reports.count()
        if incidents_count > 0:
            added_delay = incidents_count * 30  # 30 min per incident
            delay_minutes += added_delay
            risk_score += min(30, incidents_count * 15)
            factors.append({
                "factor": "incident_history",
                "impact": min(30, incidents_count * 15),
                "description": f"{incidents_count} incident(s) reported during transit."
            })

        # 3. GPS Freshness Factor
        if gps_freshness_minutes > 120.0:
            risk_score += 20
            factors.append({
                "factor": "stale_gps",
                "impact": 20,
                "description": f"No telemetry update received for over {int(gps_freshness_minutes)} minutes."
            })

        # Calculate confidence score based on data quality
        confidence = 0.85
        if not latest_ping:
            confidence -= 0.35
        elif gps_freshness_minutes > 180.0:
            confidence -= 0.25
        if not active_route:
            confidence -= 0.20
        confidence_score = Decimal(f"{max(0.10, min(0.99, confidence)):.2f}")

        risk_score = max(0, min(100, risk_score))
        risk_level = RiskLevel.from_score(risk_score)
        delay_prob = Decimal(f"{max(0.05, min(0.98, risk_score / 100.0)):.2f}")

        # Construct feature snapshot
        features = {
            "total_distance_km": total_distance,
            "remaining_distance_km": remaining_distance,
            "average_speed_kmh": average_speed,
            "gps_freshness_minutes": gps_freshness_minutes,
            "deviation_status": deviation_data.get('status'),
            "incidents_count": incidents_count,
        }

        # Persist prediction record
        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.ETA_DELAY)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.ETA_DELAY,
            prediction_value={
                "predicted_delay_minutes": delay_minutes,
                "delay_probability": float(delay_prob),
            },
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_score=confidence_score,
            input_features=features,
            explanation=factors
        )

        return {
            "shipment_id": shipment.id,
            "prediction_available": True,
            "prediction_type": PredictionType.ETA_DELAY,
            "predicted_delay_minutes": delay_minutes,
            "delay_probability": float(delay_prob),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence_score": float(confidence_score),
            "factors": factors,
            "generated_at": timezone.now().isoformat(),
        }


class ShipmentRiskPredictionService:
    """
    Evaluates delay-risk scoring for a shipment and provides explainable contributing factors.
    """
    @classmethod
    def predict_shipment_risk(cls, shipment: Shipment) -> dict:
        active_route = shipment.routes.filter(is_active=True).first()
        deviation_data = RouteOptimizationService.detect_route_deviation(shipment)

        risk_score = 15
        factors = []

        # Feature evaluation
        # 1. Route deviation
        if deviation_data.get('status') == RouteDeviationStatus.DEVIATED:
            risk_score += 30
            factors.append({
                "factor": "route_deviation",
                "impact": 30,
                "description": "Shipment has deviated from its active planned corridor route."
            })

        # 2. Incidents
        incident_count = shipment.incident_reports.count()
        if incident_count > 0:
            impact = min(35, incident_count * 18)
            risk_score += impact
            factors.append({
                "factor": "incidents_logged",
                "impact": impact,
                "description": f"Shipment has {incident_count} recorded incident report(s)."
            })

        # 3. Status checks
        if shipment.status in [ShipmentStatus.IN_TRANSIT, ShipmentStatus.AT_PICKUP] and incident_count > 0:
            risk_score += 25
            factors.append({
                "factor": "transit_disruption",
                "impact": 25,
                "description": "Active transit is experiencing operational incidents."
            })

        # 4. Telemetry freshness
        latest_ping = shipment.location_updates.order_by('-timestamp').first()
        if latest_ping:
            staleness_hours = (timezone.now() - latest_ping.timestamp).total_seconds() / 3600.0
            if staleness_hours > 3.0:
                risk_score += 15
                factors.append({
                    "factor": "stale_telemetry",
                    "impact": 15,
                    "description": f"No GPS telemetry update received for {staleness_hours:.1f} hours."
                })
        else:
            risk_score += 10
            factors.append({
                "factor": "no_telemetry",
                "impact": 10,
                "description": "No real-time GPS telemetry pings recorded yet for this shipment."
            })

        risk_score = max(0, min(100, risk_score))
        risk_level = RiskLevel.from_score(risk_score)

        confidence = 0.88 if latest_ping and active_route else 0.70
        confidence_score = Decimal(f"{confidence:.2f}")

        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.SHIPMENT_RISK)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.SHIPMENT_RISK,
            prediction_value={"risk_score": risk_score, "risk_level": risk_level},
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_score=confidence_score,
            input_features={
                "deviation_status": deviation_data.get('status'),
                "incident_count": incident_count,
                "shipment_status": shipment.status,
            },
            explanation=factors
        )

        return {
            "shipment_id": shipment.id,
            "prediction_available": True,
            "prediction_type": PredictionType.SHIPMENT_RISK,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence_score": float(confidence_score),
            "explanation": factors,
            "generated_at": timezone.now().isoformat(),
        }


class RouteRiskPredictionService:
    """
    Evaluates active corridor route risk based on waypoints, historical incidents, and deviations.
    """
    @classmethod
    def predict_route_risk(cls, shipment: Shipment) -> dict:
        active_route = shipment.routes.filter(is_active=True).first()

        if not active_route:
            return {
                "shipment_id": shipment.id,
                "prediction_available": False,
                "reason": "No active route created for this shipment",
                "confidence_score": Decimal('0.00'),
                "risk_score": 0,
                "risk_level": RiskLevel.LOW,
            }

        risk_score = 10
        factors = []

        # 1. Waypoint count & total distance
        distance = float(active_route.total_distance_km)
        if distance > 700.0:
            risk_score += 20
            factors.append({
                "factor": "long_distance_corridor",
                "impact": 20,
                "description": f"Long distance corridor route ({distance:.1f} km) increases transit risk exposure."
            })
        elif distance > 400.0:
            risk_score += 10
            factors.append({
                "factor": "medium_distance_corridor",
                "impact": 10,
                "description": f"Medium corridor route ({distance:.1f} km)."
            })

        # 2. Recalculation history count
        recalc_count = RouteOptimizationService.get_route_analytics(shipment).get('recalculation_count', 0)
        if recalc_count > 0:
            impact = min(30, recalc_count * 15)
            risk_score += impact
            factors.append({
                "factor": "route_recalculations",
                "impact": impact,
                "description": f"Route has been recalculated {recalc_count} time(s) due to corridor disruptions."
            })

        # 3. Deviation check
        dev_data = RouteOptimizationService.detect_route_deviation(shipment)
        if dev_data.get('status') == RouteDeviationStatus.DEVIATED:
            risk_score += 25
            factors.append({
                "factor": "active_deviation",
                "impact": 25,
                "description": "Active route deviation detected on current GPS coordinates."
            })

        risk_score = max(0, min(100, risk_score))
        risk_level = RiskLevel.from_score(risk_score)
        confidence_score = Decimal('0.85')

        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.ROUTE_RISK)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.ROUTE_RISK,
            prediction_value={"risk_score": risk_score, "risk_level": risk_level},
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_score=confidence_score,
            input_features={
                "total_distance_km": distance,
                "recalculation_count": recalc_count,
                "deviation_status": dev_data.get('status'),
            },
            explanation=factors
        )

        return {
            "shipment_id": shipment.id,
            "prediction_available": True,
            "prediction_type": PredictionType.ROUTE_RISK,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence_score": float(confidence_score),
            "major_risk_factors": factors,
            "generated_at": timezone.now().isoformat(),
        }


class FuelPredictionService:
    """
    Predicts fuel consumption, cost in ETB, efficiency score, and fuel risk score.
    """
    @classmethod
    def predict_fuel_consumption(
        cls,
        shipment: Shipment,
        fuel_efficiency: float = None,
        fuel_price: float = None
    ) -> dict:
        fuel_data = RouteOptimizationService.calculate_fuel_analytics(
            shipment=shipment,
            fuel_efficiency_km_per_liter=fuel_efficiency,
            fuel_price_per_liter=fuel_price
        )

        planned_distance = float(fuel_data['planned_distance_km'])
        actual_distance = float(fuel_data['actual_distance_km'])
        eff = float(fuel_data['fuel_efficiency_km_per_liter'])
        price = float(fuel_data['fuel_price_per_liter_etb'])

        # Predict total fuel requirement considering planned vs actual
        effective_distance = max(planned_distance, actual_distance)
        predicted_liters = round(effective_distance / eff, 2) if eff > 0 else 0.0
        predicted_cost_etb = round(predicted_liters * price, 2)

        # Efficiency & Risk Scoring
        fuel_efficiency_score = 85
        risk_score = 15

        if planned_distance > 0 and actual_distance > planned_distance * 1.1:
            variance_pct = ((actual_distance / planned_distance) - 1.0) * 100.0
            fuel_efficiency_score -= min(35, int(variance_pct))
            risk_score += min(45, int(variance_pct * 1.5))

        risk_score = max(0, min(100, risk_score))
        risk_level = RiskLevel.from_score(risk_score)
        confidence_score = Decimal('0.82')

        active_route = shipment.routes.filter(is_active=True).first()
        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.FUEL_CONSUMPTION)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.FUEL_CONSUMPTION,
            prediction_value={
                "predicted_fuel_liters": predicted_liters,
                "predicted_fuel_cost_etb": predicted_cost_etb,
                "fuel_efficiency_score": fuel_efficiency_score,
            },
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_score=confidence_score,
            input_features={
                "planned_distance_km": planned_distance,
                "actual_distance_km": actual_distance,
                "fuel_efficiency": eff,
                "fuel_price": price,
            },
            explanation=[
                {
                    "factor": "distance_variance",
                    "impact": risk_score,
                    "description": f"Predicted fuel cost calculated based on {eff} km/L efficiency at {price} ETB/L."
                }
            ]
        )

        return {
            "shipment_id": shipment.id,
            "prediction_available": True,
            "prediction_type": PredictionType.FUEL_CONSUMPTION,
            "predicted_fuel_liters": predicted_liters,
            "predicted_fuel_cost_etb": predicted_cost_etb,
            "fuel_efficiency_score": fuel_efficiency_score,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence_score": float(confidence_score),
            "generated_at": timezone.now().isoformat(),
        }


class IncidentRiskPredictionService:
    """
    Predicts incident likelihood and risk score based on corridor history, route deviation, and past driver breakdown pings.
    """
    @classmethod
    def predict_incident_risk(cls, shipment: Shipment) -> dict:
        active_route = shipment.routes.filter(is_active=True).first()

        risk_score = 10
        factors = []

        # 1. Existing incidents on this shipment
        incidents = shipment.incident_reports.all()
        if incidents.exists():
            count = incidents.count()
            impact = min(40, count * 20)
            risk_score += impact
            factors.append({
                "factor": "active_shipment_incidents",
                "impact": impact,
                "description": f"{count} incident report(s) already logged on this shipment."
            })

        # 2. Driver historical incident profile
        if shipment.driver:
            driver_past_incidents = DriverIncidentReport.objects.filter(
                driver=shipment.driver
            ).exclude(shipment=shipment).count()

            if driver_past_incidents > 0:
                impact = min(25, driver_past_incidents * 10)
                risk_score += impact
                factors.append({
                    "factor": "driver_history",
                    "impact": impact,
                    "description": f"Assigned driver has {driver_past_incidents} past incident(s) in corridor history."
                })

        # 3. Deviation impact
        dev_data = RouteOptimizationService.detect_route_deviation(shipment)
        if dev_data.get('status') == RouteDeviationStatus.DEVIATED:
            risk_score += 20
            factors.append({
                "factor": "route_deviation",
                "impact": 20,
                "description": "Route deviation increases security and breakdown vulnerability."
            })

        risk_score = max(0, min(100, risk_score))
        risk_level = RiskLevel.from_score(risk_score)
        confidence_score = Decimal('0.84')

        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.INCIDENT_RISK)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.INCIDENT_RISK,
            prediction_value={"risk_score": risk_score, "risk_level": risk_level},
            risk_score=risk_score,
            risk_level=risk_level,
            confidence_score=confidence_score,
            input_features={
                "active_incidents": incidents.count(),
                "deviation_status": dev_data.get('status'),
            },
            explanation=factors
        )

        return {
            "shipment_id": shipment.id,
            "prediction_available": True,
            "prediction_type": PredictionType.INCIDENT_RISK,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "confidence_score": float(confidence_score),
            "risk_factors": factors,
            "generated_at": timezone.now().isoformat(),
        }


class OperationalRiskService:
    """
    Aggregates component risk scores using transparent weighting:
      - ETA Risk: 30%
      - Route Risk: 20%
      - Incident Risk: 25%
      - Fuel Risk: 15%
      - Deviation Risk: 10%
    """
    WEIGHTS = {
        "eta": 0.30,
        "route": 0.20,
        "incident": 0.25,
        "fuel": 0.15,
        "deviation": 0.10,
    }

    @classmethod
    def get_composite_dashboard(cls, shipment: Shipment) -> dict:
        eta_pred = ETADelayPredictionService.predict_eta_delay(shipment)
        shipment_pred = ShipmentRiskPredictionService.predict_shipment_risk(shipment)
        route_pred = RouteRiskPredictionService.predict_route_risk(shipment)
        fuel_pred = FuelPredictionService.predict_fuel_consumption(shipment)
        incident_pred = IncidentRiskPredictionService.predict_incident_risk(shipment)
        deviation_data = RouteOptimizationService.detect_route_deviation(shipment)

        eta_score = eta_pred.get("risk_score", 0)
        route_score = route_pred.get("risk_score", 0)
        incident_score = incident_pred.get("risk_score", 0)
        fuel_score = fuel_pred.get("risk_score", 0)

        dev_status = deviation_data.get("status")
        deviation_score = 65 if dev_status == RouteDeviationStatus.DEVIATED else 10

        composite_score = int(
            (eta_score * cls.WEIGHTS["eta"]) +
            (route_score * cls.WEIGHTS["route"]) +
            (incident_score * cls.WEIGHTS["incident"]) +
            (fuel_score * cls.WEIGHTS["fuel"]) +
            (deviation_score * cls.WEIGHTS["deviation"])
        )

        composite_score = max(0, min(100, composite_score))
        composite_level = RiskLevel.from_score(composite_score)
        confidence_score = Decimal('0.85')

        active_route = shipment.routes.filter(is_active=True).first()
        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.OPERATIONAL_RISK)
        PredictionRecord.objects.create(
            shipment=shipment,
            route=active_route,
            prediction_model=model_obj,
            prediction_type=PredictionType.OPERATIONAL_RISK,
            prediction_value={
                "composite_score": composite_score,
                "composite_level": composite_level,
                "component_scores": {
                    "eta_score": eta_score,
                    "route_score": route_score,
                    "incident_score": incident_score,
                    "fuel_score": fuel_score,
                    "deviation_score": deviation_score,
                }
            },
            risk_score=composite_score,
            risk_level=composite_level,
            confidence_score=confidence_score,
            input_features={
                "weights": cls.WEIGHTS,
                "eta_score": eta_score,
                "route_score": route_score,
                "incident_score": incident_score,
                "fuel_score": fuel_score,
                "deviation_score": deviation_score,
            },
            explanation=[
                {
                    "factor": "composite_weighting",
                    "impact": composite_score,
                    "description": f"Aggregate risk calculated using transparent weights (ETA 30%, Incident 25%, Route 20%, Fuel 15%, Deviation 10%)."
                }
            ]
        )

        return {
            "shipment_id": shipment.id,
            "overall_risk": {
                "score": composite_score,
                "level": composite_level,
                "confidence": float(confidence_score),
            },
            "eta": {
                "delay_probability": eta_pred.get("delay_probability", 0.0),
                "predicted_delay_minutes": eta_pred.get("predicted_delay_minutes", 0),
            },
            "route": {
                "risk_score": route_score,
                "level": route_pred.get("risk_level", RiskLevel.LOW),
            },
            "fuel": {
                "predicted_liters": fuel_pred.get("predicted_fuel_liters", 0.0),
                "predicted_cost_etb": fuel_pred.get("predicted_fuel_cost_etb", 0.0),
            },
            "incident": {
                "risk_score": incident_score,
                "level": incident_pred.get("risk_level", RiskLevel.LOW),
            },
            "deviation": {
                "status": dev_status,
                "distance_from_route_km": float(deviation_data.get("min_distance_to_route_km") or 0.0),
            },
            "generated_at": timezone.now().isoformat(),
        }
