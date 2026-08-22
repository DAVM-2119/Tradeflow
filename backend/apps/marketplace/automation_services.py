import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404

from apps.accounts.models import Role
from apps.marketplace.models import (
    Shipment,
    ShipmentStatus,
    LocationUpdate,
    DriverIncidentReport,
    AutomationRule,
    AutomationRecommendation,
    AutomationExecution,
    RecommendationPriority,
    RecommendationStatus,
    AutomationRuleType,
    AutomationRecommendationType,
)
from apps.marketplace.services import RouteOptimizationService
from apps.marketplace.predictive_services import OperationalRiskService, ETADelayPredictionService
from apps.marketplace.pricing_services import DynamicPricingService



logger = logging.getLogger(__name__)


class AutomationService:
    """
    Domain service for Phase 13 Automated Workflow & Smart Operations.
    Enforces rule evaluation, recommendation generation, duplicate prevention,
    and explicit authorization approval/execution lifecycles.
    """

    @classmethod
    def get_or_create_default_rules(cls):
        """
        Seeds standard default automation rules if none are present or active.
        """
        default_rules_data = [
            {
                "name": "High Operational Risk",
                "rule_type": AutomationRuleType.HIGH_OPERATIONAL_RISK,
                "description": "Trigger review recommendation when composite operational risk score exceeds threshold.",
                "priority": RecommendationPriority.HIGH,
                "configuration": {"minimum_risk_score": 70},
            },
            {
                "name": "Critical Operational Risk",
                "rule_type": AutomationRuleType.HIGH_OPERATIONAL_RISK,
                "description": "Trigger urgent review recommendation when composite operational risk score exceeds 90.",
                "priority": RecommendationPriority.CRITICAL,
                "configuration": {"minimum_risk_score": 90},
            },
            {
                "name": "Route Deviation Detected",
                "rule_type": AutomationRuleType.ROUTE_DEVIATION,
                "description": "Trigger route recalculation or review when vehicle deviates beyond configured km threshold.",
                "priority": RecommendationPriority.HIGH,
                "configuration": {"threshold_km": 10.0},
            },
            {
                "name": "High ETA Delay Predicted",
                "rule_type": AutomationRuleType.HIGH_ETA_DELAY,
                "description": "Trigger driver contact request when predicted arrival delay exceeds threshold.",
                "priority": RecommendationPriority.MEDIUM,
                "configuration": {"threshold_minutes": 60},
            },
            {
                "name": "Driver Incident Reported",
                "rule_type": AutomationRuleType.INCIDENT_REPORTED,
                "description": "Trigger incident review when driver files a road problem, breakdown, or security incident.",
                "priority": RecommendationPriority.HIGH,
                "configuration": {"severities": ["HIGH", "CRITICAL"]},
            },
            {
                "name": "High Fuel Consumption/Risk",
                "rule_type": AutomationRuleType.HIGH_FUEL_RISK,
                "description": "Trigger route review when predicted or actual fuel consumption exceeds tolerance.",
                "priority": RecommendationPriority.MEDIUM,
                "configuration": {"consumption_tolerance_pct": 25.0},
            },
            {
                "name": "High Corridor Market Pressure",
                "rule_type": AutomationRuleType.HIGH_MARKET_PRESSURE,
                "description": "Trigger freight pricing review when corridor demand pressure is HIGH.",
                "priority": RecommendationPriority.LOW,
                "configuration": {"market_pressure": "HIGH"},
            },
            {
                "name": "Stale GPS Telemetry",
                "rule_type": AutomationRuleType.STALE_GPS_DATA,
                "description": "Trigger driver contact or admin escalation when no GPS telemetry is received for configured hours.",
                "priority": RecommendationPriority.HIGH,
                "configuration": {"threshold_hours": 3},
            },
        ]

        created_rules = []
        for data in default_rules_data:
            rule, _ = AutomationRule.objects.get_or_create(
                name=data["name"],
                defaults={
                    "rule_type": data["rule_type"],
                    "description": data["description"],
                    "priority": data["priority"],
                    "configuration": data["configuration"],
                    "is_active": True,
                }
            )
            created_rules.append(rule)
        return created_rules

    @classmethod
    def evaluate_shipment(cls, shipment: Shipment) -> dict:
        """
        Inspects existing Phase 9-12 operational intelligence for a shipment,
        evaluates active automation rules, and creates recommendations for satisfied rules.
        Enforces duplicate prevention for pending recommendations.
        """
        cls.get_or_create_default_rules()
        active_rules = AutomationRule.objects.filter(is_active=True)

        evaluated_count = 0
        created_count = 0
        existing_count = 0
        created_recommendations = []

        # Gather operational intelligence ONCE
        risk_dashboard = OperationalRiskService.get_composite_dashboard(shipment)
        risk_score = risk_dashboard.get("composite_risk_score", 0)
        risk_level = risk_dashboard.get("risk_level", "LOW")

        deviation_data = RouteOptimizationService.detect_route_deviation(shipment)
        is_deviated = (deviation_data.get("status") == "DEVIATED")
        deviation_km = deviation_data.get("deviation_distance_km", 0.0)

        eta_prediction = ETADelayPredictionService.predict_eta_delay(shipment)
        predicted_delay_minutes = eta_prediction.get("predicted_delay_minutes", 0)

        incidents = DriverIncidentReport.objects.filter(shipment=shipment)
        incident_count = incidents.count()

        fuel_analytics = RouteOptimizationService.calculate_fuel_analytics(shipment)
        expected_fuel_liters = fuel_analytics.get("estimated_fuel_liters", 0.0)

        market_snapshot = DynamicPricingService.calculate_market_snapshot(shipment)
        market_pressure = getattr(market_snapshot, 'market_pressure', 'NORMAL')

        last_gps = LocationUpdate.objects.filter(shipment=shipment).order_by('-timestamp').first()
        hours_since_gps = 0.0
        if last_gps:
            hours_since_gps = (timezone.now() - last_gps.timestamp).total_seconds() / 3600.0
        elif shipment.status in [ShipmentStatus.DRIVER_ASSIGNED, ShipmentStatus.AT_PICKUP, ShipmentStatus.IN_TRANSIT, ShipmentStatus.AT_DESTINATION]:
            hours_since_gps = 24.0  # Default high stale count if in transit without telemetry

        with transaction.atomic():
            for rule in active_rules:
                evaluated_count += 1
                should_trigger = False
                title = ""
                description = ""
                recommended_action = ""
                rec_type = AutomationRecommendationType.REVIEW_SHIPMENT
                snapshot = {
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "deviation_km": deviation_km,
                    "is_deviated": is_deviated,
                    "predicted_delay_minutes": predicted_delay_minutes,
                    "incident_count": incident_count,
                    "market_pressure": market_pressure,
                    "hours_since_gps": round(hours_since_gps, 1),
                }

                config = rule.configuration or {}

                # Rule A: High Operational Risk
                if rule.rule_type == AutomationRuleType.HIGH_OPERATIONAL_RISK:
                    min_risk = config.get("minimum_risk_score", 70)
                    # To distinguish High vs Critical rules when both match:
                    if rule.priority == RecommendationPriority.CRITICAL and min_risk >= 90:
                        if risk_score >= min_risk:
                            should_trigger = True
                            rec_type = AutomationRecommendationType.ESCALATE_TO_ADMIN
                            title = f"Critical Operational Risk ({risk_score}/100)"
                            description = f"Shipment operational risk score is {risk_score}, exceeding critical threshold of {min_risk}."
                            recommended_action = "Escalate to platform admin for immediate operational intervention."
                    elif risk_score >= min_risk and risk_score < 90:
                        should_trigger = True
                        rec_type = AutomationRecommendationType.REVIEW_SHIPMENT
                        title = f"High Operational Risk ({risk_score}/100)"
                        description = f"Shipment operational risk score is {risk_score}, exceeding threshold of {min_risk}."
                        recommended_action = "Perform operational review on shipment status and driver telemetry."

                # Rule B: Route Deviation
                elif rule.rule_type == AutomationRuleType.ROUTE_DEVIATION:
                    thresh_km = config.get("threshold_km", 10.0)
                    if is_deviated or deviation_km >= thresh_km:
                        should_trigger = True
                        if deviation_km >= 25.0:
                            rec_type = AutomationRecommendationType.RECALCULATE_ROUTE
                            title = f"Significant Route Deviation ({deviation_km} km)"
                            description = f"Vehicle has deviated {deviation_km} km from planned corridor."
                            recommended_action = "Recalculate optimal route from current vehicle location."
                        else:
                            rec_type = AutomationRecommendationType.REVIEW_ROUTE
                            title = f"Route Deviation Detected ({deviation_km} km)"
                            description = f"Vehicle has deviated {deviation_km} km from planned corridor."
                            recommended_action = "Review route status and confirm corridor alignment."

                # Rule C: High ETA Delay
                elif rule.rule_type == AutomationRuleType.HIGH_ETA_DELAY:
                    thresh_min = config.get("threshold_minutes", 60)
                    if predicted_delay_minutes >= thresh_min:
                        should_trigger = True
                        rec_type = AutomationRecommendationType.CONTACT_DRIVER
                        title = f"Predicted Arrival Delay ({predicted_delay_minutes} min)"
                        description = f"Shipment is predicted to arrive approximately {predicted_delay_minutes} minutes late."
                        recommended_action = "Contact assigned driver to verify travel speed and corridor conditions."

                # Rule D: Incident Reported
                elif rule.rule_type == AutomationRuleType.INCIDENT_REPORTED:
                    if incident_count > 0:
                        latest_incident = incidents.order_by('-reported_at').first()
                        should_trigger = True
                        rec_type = AutomationRecommendationType.REVIEW_INCIDENT
                        title = f"Driver Incident: {latest_incident.incident_type}"
                        description = f"Driver reported incident ({latest_incident.incident_type}) with description: {latest_incident.description}"
                        recommended_action = "Review driver incident report and arrange operational support if necessary."

                # Rule E: High Fuel Risk
                elif rule.rule_type == AutomationRuleType.HIGH_FUEL_RISK:
                    if expected_fuel_liters > 350.0:  # High consumption threshold
                        should_trigger = True
                        rec_type = AutomationRecommendationType.REVIEW_ROUTE
                        title = "High Fuel Consumption Corridor"
                        description = f"Estimated fuel consumption is {expected_fuel_liters} L, exceeding corridor tolerance."
                        recommended_action = "Review route gradient and fuel efficiency parameters."

                # Rule F: High Market Pressure
                elif rule.rule_type == AutomationRuleType.HIGH_MARKET_PRESSURE:
                    target_pressure = config.get("market_pressure", "HIGH")
                    if market_pressure == target_pressure:
                        should_trigger = True
                        rec_type = AutomationRecommendationType.REVIEW_PRICING
                        title = "High Corridor Freight Market Pressure"
                        description = f"Demand/supply pressure along corridor {shipment.origin} -> {shipment.destination} is currently HIGH."
                        recommended_action = "Review freight price recommendation for market alignment."

                # Rule G: Stale GPS Telemetry
                elif rule.rule_type == AutomationRuleType.STALE_GPS_DATA:
                    thresh_hrs = config.get("threshold_hours", 3)
                    if hours_since_gps >= thresh_hrs and shipment.status in [ShipmentStatus.DRIVER_ASSIGNED, ShipmentStatus.AT_PICKUP, ShipmentStatus.IN_TRANSIT, ShipmentStatus.AT_DESTINATION]:
                        should_trigger = True
                        rec_type = AutomationRecommendationType.CONTACT_DRIVER
                        title = f"Stale GPS Telemetry ({round(hours_since_gps, 1)} hours)"
                        description = f"No GPS location update received for {round(hours_since_gps, 1)} hours while shipment is active."
                        recommended_action = "Contact driver to verify GPS connectivity and location status."

                if should_trigger:
                    # DUPLICATE PREVENTION: Check if a PENDING recommendation for same shipment+rule already exists
                    pending_exists = AutomationRecommendation.objects.filter(
                        shipment=shipment,
                        rule=rule,
                        status=RecommendationStatus.PENDING
                    ).exists()

                    if pending_exists:
                        existing_count += 1
                    else:
                        rec = AutomationRecommendation.objects.create(
                            shipment=shipment,
                            rule=rule,
                            recommendation_type=rec_type,
                            priority=rule.priority,
                            status=RecommendationStatus.PENDING,
                            title=title,
                            description=description,
                            recommended_action=recommended_action,
                            context_snapshot=snapshot,
                        )
                        created_count += 1
                        created_recommendations.append(rec)

        return {
            "shipment_id": shipment.id,
            "evaluated_rules": evaluated_count,
            "recommendations_created": created_count,
            "recommendations_existing": existing_count,
            "recommendations": created_recommendations,
        }

    @classmethod
    def check_user_authorization(cls, shipment: Shipment, user) -> bool:
        """
        Verifies if a user is an authorized participant (Shipper Load Owner, Transporter Owner, Assigned Driver, or Admin).
        """
        if not user or not user.is_authenticated:
            return False

        if user.role == Role.ADMIN or user.is_staff or user.is_superuser:
            return True

        if hasattr(user, 'shipper_profile') and shipment.load.shipper == user.shipper_profile:
            return True

        if hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile:
            return True

        if hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile:
            return True

        return False

    @classmethod
    def approve_recommendation(cls, recommendation_id: int, user) -> AutomationRecommendation:
        """
        Approves a PENDING recommendation. Uses atomic transaction and select_for_update.
        """
        with transaction.atomic():
            recommendation = AutomationRecommendation.objects.select_for_update().select_related('shipment').get(id=recommendation_id)

            if not cls.check_user_authorization(recommendation.shipment, user):
                raise PermissionDenied("You are not authorized to approve recommendations for this shipment.")

            if recommendation.status != RecommendationStatus.PENDING:
                raise ValidationError(f"Cannot approve recommendation in status '{recommendation.status}'. Only PENDING recommendations can be approved.")

            recommendation.status = RecommendationStatus.APPROVED
            recommendation.reviewed_by = user
            recommendation.reviewed_at = timezone.now()
            recommendation.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

            logger.info(f"Recommendation #{recommendation.id} APPROVED by user #{user.id}")
            return recommendation

    @classmethod
    def reject_recommendation(cls, recommendation_id: int, user, reason: str = "") -> AutomationRecommendation:
        """
        Rejects a PENDING recommendation with a reason. Uses atomic transaction and select_for_update.
        """
        with transaction.atomic():
            recommendation = AutomationRecommendation.objects.select_for_update().select_related('shipment').get(id=recommendation_id)

            if not cls.check_user_authorization(recommendation.shipment, user):
                raise PermissionDenied("You are not authorized to reject recommendations for this shipment.")

            if recommendation.status != RecommendationStatus.PENDING:
                raise ValidationError(f"Cannot reject recommendation in status '{recommendation.status}'. Only PENDING recommendations can be rejected.")

            recommendation.status = RecommendationStatus.REJECTED
            recommendation.rejection_reason = reason or "Rejected during manual review."
            recommendation.reviewed_by = user
            recommendation.reviewed_at = timezone.now()
            recommendation.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])

            logger.info(f"Recommendation #{recommendation.id} REJECTED by user #{user.id}")
            return recommendation

    @classmethod
    def execute_recommendation(cls, recommendation_id: int, user) -> AutomationExecution:
        """
        Executes an APPROVED recommendation safely. Creates an immutable AutomationExecution audit record.
        """
        with transaction.atomic():
            recommendation = AutomationRecommendation.objects.select_for_update().select_related('shipment').get(id=recommendation_id)

            if not cls.check_user_authorization(recommendation.shipment, user):
                raise PermissionDenied("You are not authorized to execute recommendations for this shipment.")

            if recommendation.status != RecommendationStatus.APPROVED:
                raise ValidationError(f"Cannot execute recommendation in status '{recommendation.status}'. Only APPROVED recommendations can be executed.")

            exec_result = {}
            rec_type = recommendation.recommendation_type

            if rec_type == AutomationRecommendationType.REVIEW_SHIPMENT:
                exec_result = {
                    "action": "REVIEW_SHIPMENT",
                    "message": "Shipment operational review acknowledged.",
                    "shipment_tracking_number": recommendation.shipment.tracking_number,
                }
            elif rec_type == AutomationRecommendationType.REVIEW_ROUTE:
                exec_result = {
                    "action": "REVIEW_ROUTE",
                    "message": "Route review acknowledged.",
                    "shipment_tracking_number": recommendation.shipment.tracking_number,
                }
            elif rec_type == AutomationRecommendationType.RECALCULATE_ROUTE:
                recalc_res = RouteOptimizationService.recalculate_route(recommendation.shipment, user=user)
                exec_result = {
                    "action": "RECALCULATE_ROUTE",
                    "message": "Route recalculated successfully via RouteOptimizationService.",
                    "recalculation_id": recalc_res.id,
                    "distance_km": float(recalc_res.distance_km),
                }
            elif rec_type == AutomationRecommendationType.CONTACT_DRIVER:
                exec_result = {
                    "action": "CONTACT_DRIVER",
                    "message": "Driver contact request recorded.",
                    "driver_email": recommendation.shipment.driver.user.email if recommendation.shipment.driver else "Unassigned",
                }
            elif rec_type == AutomationRecommendationType.REVIEW_INCIDENT:
                exec_result = {
                    "action": "REVIEW_INCIDENT",
                    "message": "Driver incident operational review logged.",
                    "shipment_tracking_number": recommendation.shipment.tracking_number,
                }
            elif rec_type == AutomationRecommendationType.REVIEW_PRICING:
                exec_result = {
                    "action": "REVIEW_PRICING",
                    "message": "Freight market pricing review logged.",
                    "shipment_tracking_number": recommendation.shipment.tracking_number,
                }
            elif rec_type == AutomationRecommendationType.ESCALATE_TO_ADMIN:
                exec_result = {
                    "action": "ESCALATE_TO_ADMIN",
                    "message": "Operational issue escalated to administration.",
                    "shipment_tracking_number": recommendation.shipment.tracking_number,
                }
            else:
                exec_result = {
                    "action": rec_type,
                    "message": f"Action {rec_type} acknowledged.",
                }

            execution = AutomationExecution.objects.create(
                recommendation=recommendation,
                executed_by=user,
                action_type=rec_type,
                status='SUCCESS',
                result=exec_result,
            )

            recommendation.status = RecommendationStatus.EXECUTED
            recommendation.execution_result = exec_result
            recommendation.save(update_fields=['status', 'execution_result', 'updated_at'])

            logger.info(f"Recommendation #{recommendation.id} EXECUTED by user #{user.id}")
            return execution

    @classmethod
    def get_recommendation_history(cls, shipment: Shipment):
        """
        Returns all historical recommendations for a shipment (-created_at).
        """
        return AutomationRecommendation.objects.filter(shipment=shipment).select_related('rule', 'reviewed_by').order_by('-created_at')
