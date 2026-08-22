import logging
import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional

from django.db import models
from django.db.models import Q, Count, Avg, Max, Min, Case, When, F, Value, IntegerField, FloatField
from django.utils import timezone
from django.core.cache import cache

from apps.accounts.models import Role
from apps.marketplace.models import (
    Shipment, ShipmentStatus, CargoLoad, DriverIncidentReport,
    Route, RouteStatus, RouteDeviationStatus, LocationUpdate,
    PredictionRecord, PredictionType, RiskLevel,
    PriceRecommendation, MarketPressure,
    AutomationRecommendation, RecommendationPriority, RecommendationStatus, AutomationExecution,
    OperationalEvent, OperationalEventType, EventSeverity,
    Notification, NotificationPreference
)
from apps.marketplace.predictive_services import OperationalRiskService, ETADelayPredictionService, ShipmentRiskPredictionService
from apps.marketplace.services import RouteOptimizationService
from apps.marketplace.pricing_services import DynamicPricingService
from apps.marketplace.automation_services import AutomationService

logger = logging.getLogger(__name__)

CACHE_TTL = 15  # 15 seconds short TTL for read-heavy command center aggregates


class OperationalCommandCenterService:
    """
    Domain service for Phase 15 Operational Command Center & Alert Intelligence.
    Aggregates existing Phase 9-14 data sources into read-only decision-support intelligence.
    """

    @classmethod
    def _get_authorized_shipments_queryset(cls, user) -> models.QuerySet:
        """
        Returns queryset of shipments the user is authorized to access.
        Admins see all shipments.
        Shippers see shipments for their loads.
        Transporters see shipments assigned to their fleet.
        Drivers see shipments assigned to them.
        """
        if not user or not user.is_authenticated:
            return Shipment.objects.none()

        if user.is_superuser or user.role == Role.ADMIN:
            return Shipment.objects.all()

        if user.role == Role.SHIPPER and hasattr(user, 'shipper_profile'):
            return Shipment.objects.filter(load__shipper=user.shipper_profile)

        if user.role == Role.TRANSPORTER and hasattr(user, 'transporter_profile'):
            return Shipment.objects.filter(transporter=user.transporter_profile)

        if user.role == Role.DRIVER and hasattr(user, 'driver_profile'):
            return Shipment.objects.filter(driver=user.driver_profile)

        return Shipment.objects.none()

    @classmethod
    def get_realtime_summary(cls, user) -> Dict[str, Any]:
        """
        Produces real-time operational summary metrics aggregated from authoritative DB records.
        Applies Redis caching with graceful fallback if Redis is unavailable.
        """
        cache_key = f"cmd_center:summary:user_{user.id}"
        try:
            cached_data = cache.get(cache_key)
            if cached_data:
                return cached_data
        except Exception as e:
            logger.warning(f"Redis cache access error in get_realtime_summary: {e}")

        shipments_qs = cls._get_authorized_shipments_queryset(user)
        active_shipments_qs = shipments_qs.exclude(
            status__in=[ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]
        )

        total_active_shipments = active_shipments_qs.count()

        # Phase 11 Risk Aggregation
        active_shipment_ids = list(active_shipments_qs.values_list('id', flat=True))

        latest_predictions = PredictionRecord.objects.filter(
            shipment_id__in=active_shipment_ids,
            prediction_type=PredictionType.OPERATIONAL_RISK
        ).order_by('shipment_id', '-created_at')

        # Distinct latest operational risk per shipment
        latest_risk_by_shipment = {}
        for pred in latest_predictions:
            if pred.shipment_id not in latest_risk_by_shipment:
                latest_risk_by_shipment[pred.shipment_id] = pred.risk_level

        high_risk_shipments = sum(1 for lvl in latest_risk_by_shipment.values() if lvl == RiskLevel.HIGH)
        critical_risk_shipments = sum(1 for lvl in latest_risk_by_shipment.values() if lvl == RiskLevel.CRITICAL)
        shipments_at_risk = high_risk_shipments + critical_risk_shipments

        # Delayed shipments (Phase 11 delay > 15 mins or Phase 10 status)
        eta_predictions = PredictionRecord.objects.filter(
            shipment_id__in=active_shipment_ids,
            prediction_type=PredictionType.ETA_DELAY
        ).order_by('shipment_id', '-created_at')

        delayed_shipment_set = set()
        for eta_pred in eta_predictions:
            if eta_pred.shipment_id not in delayed_shipment_set:
                delay_mins = eta_pred.prediction_value.get('predicted_delay_minutes', 0)
                if delay_mins > 15:
                    delayed_shipment_set.add(eta_pred.shipment_id)
        delayed_shipments = len(delayed_shipment_set)

        # Phase 10 Route Deviations
        route_deviation_shipments = 0
        active_routes = Route.objects.filter(shipment_id__in=active_shipment_ids, is_active=True).select_related('shipment')
        for route in active_routes:
            dev_res = RouteOptimizationService.detect_route_deviation(route.shipment)
            if dev_res.get("status") == RouteDeviationStatus.DEVIATED:
                route_deviation_shipments += 1


        # Phase 9 Active Incidents
        active_incidents_qs = DriverIncidentReport.objects.filter(
            shipment_id__in=active_shipment_ids
        )
        active_incidents = active_incidents_qs.count()
        critical_incidents = active_incidents_qs.filter(
            Q(incident_type__in=['ACCIDENT', 'SECURITY_INCIDENT', 'VEHICLE_BREAKDOWN'])
        ).count()

        # Phase 14 Notifications
        user_notifs_qs = Notification.objects.filter(recipient=user)
        unread_notifications = user_notifs_qs.filter(is_read=False).count()
        critical_unacknowledged_notifications = user_notifs_qs.filter(
            event__severity=EventSeverity.CRITICAL,
            is_acknowledged=False
        ).count()

        # Phase 13 Automation Workflow
        pending_automation_recommendations = AutomationRecommendation.objects.filter(
            shipment_id__in=active_shipment_ids,
            status=RecommendationStatus.PENDING
        ).count()

        approved_automation_recommendations = AutomationRecommendation.objects.filter(
            shipment_id__in=active_shipment_ids,
            status=RecommendationStatus.APPROVED
        ).count()

        failed_automation_executions = AutomationExecution.objects.filter(
            recommendation__shipment_id__in=active_shipment_ids,
            status='FAILED'
        ).count()

        # Phase 12 High Market Pressure
        latest_pricing = PriceRecommendation.objects.filter(
            shipment_id__in=active_shipment_ids
        ).order_by('shipment_id', '-created_at')

        high_market_pressure_set = set()
        for price_rec in latest_pricing:
            if price_rec.shipment_id not in high_market_pressure_set:
                if price_rec.market_pressure == MarketPressure.HIGH:
                    high_market_pressure_set.add(price_rec.shipment_id)
        high_market_pressure_shipments = len(high_market_pressure_set)

        # Telemetry Freshness (stale if no location update in last 30 minutes)
        thirty_mins_ago = timezone.now() - timedelta(minutes=30)
        recent_telemetry_shipment_ids = set(
            LocationUpdate.objects.filter(
                shipment_id__in=active_shipment_ids,
                timestamp__gte=thirty_mins_ago
            ).values_list('shipment_id', flat=True)
        )
        stale_gps_shipments = max(0, total_active_shipments - len(recent_telemetry_shipment_ids))

        summary_data = {
            "total_active_shipments": total_active_shipments,
            "shipments_at_risk": shipments_at_risk,
            "high_risk_shipments": high_risk_shipments,
            "critical_risk_shipments": critical_risk_shipments,
            "delayed_shipments": delayed_shipments,
            "route_deviation_shipments": route_deviation_shipments,
            "active_incidents": active_incidents,
            "critical_incidents": critical_incidents,
            "unread_notifications": unread_notifications,
            "critical_unacknowledged_notifications": critical_unacknowledged_notifications,
            "pending_automation_recommendations": pending_automation_recommendations,
            "approved_automation_recommendations": approved_automation_recommendations,
            "high_market_pressure_shipments": high_market_pressure_shipments,
            "stale_gps_shipments": stale_gps_shipments,
            "failed_automation_executions": failed_automation_executions,
            "generated_at": timezone.now().isoformat()
        }

        try:
            cache.set(cache_key, summary_data, timeout=CACHE_TTL)
        except Exception as e:
            logger.warning(f"Redis cache write error in get_realtime_summary: {e}")

        return summary_data

    @classmethod
    def calculate_operational_health_score(cls, user, shipment_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculates a deterministic, explainable Operational Health Score (0-100).
        0-24: HEALTHY
        25-49: STABLE
        50-74: WARNING
        75-89: CRITICAL
        90-100: SEVERE
        """
        summary = cls.get_realtime_summary(user)
        total_active = summary["total_active_shipments"]

        factors = []
        score = 0.0

        if total_active == 0 and not shipment_id:
            return {
                "score": 0.0,
                "level": "HEALTHY",
                "confidence": "HIGH",
                "factors": [{"factor": "no_active_shipments", "impact": 0, "description": "No active shipments in system."}],
                "generated_at": timezone.now().isoformat()
            }

        # 1. Critical Incidents (+25 pts max)
        crit_incidents = summary["critical_incidents"]
        if crit_incidents > 0:
            impact = min(25.0, crit_incidents * 12.5)
            score += impact
            factors.append({
                "factor": "critical_incidents",
                "impact": round(impact, 1),
                "description": f"{crit_incidents} critical incident(s) reported."
            })

        # 2. Route Deviations (+20 pts max)
        deviated = summary["route_deviation_shipments"]
        if deviated > 0:
            impact = min(20.0, (deviated / max(1, total_active)) * 40.0)
            score += impact
            factors.append({
                "factor": "route_deviations",
                "impact": round(impact, 1),
                "description": f"{deviated} active shipment(s) currently deviated from planned route."
            })

        # 3. High Risk Shipments (+20 pts max)
        crit_risk = summary["critical_risk_shipments"]
        high_risk = summary["high_risk_shipments"]
        if crit_risk > 0 or high_risk > 0:
            impact = min(20.0, (crit_risk * 10.0) + (high_risk * 5.0))
            score += impact
            factors.append({
                "factor": "operational_risk",
                "impact": round(impact, 1),
                "description": f"{crit_risk} critical-risk and {high_risk} high-risk shipment(s)."
            })

        # 4. Critical Unacknowledged Notifications (+15 pts max)
        unack = summary["critical_unacknowledged_notifications"]
        if unack > 0:
            impact = min(15.0, unack * 5.0)
            score += impact
            factors.append({
                "factor": "unacknowledged_critical_alerts",
                "impact": round(impact, 1),
                "description": f"{unack} unacknowledged critical notification(s)."
            })

        # 5. Stale Telemetry (+10 pts max)
        stale = summary["stale_gps_shipments"]
        if stale > 0:
            impact = min(10.0, (stale / max(1, total_active)) * 20.0)
            score += impact
            factors.append({
                "factor": "stale_gps_telemetry",
                "impact": round(impact, 1),
                "description": f"{stale} shipment(s) with stale GPS telemetry (>30m old)."
            })

        # 6. Pending Critical Automations (+10 pts max)
        pending_recs = summary["pending_automation_recommendations"]
        if pending_recs > 0:
            impact = min(10.0, pending_recs * 2.5)
            score += impact
            factors.append({
                "factor": "pending_automation_recommendations",
                "impact": round(impact, 1),
                "description": f"{pending_recs} pending automation workflow recommendation(s)."
            })

        score = min(100.0, max(0.0, score))

        if score < 25.0:
            level = "HEALTHY"
        elif score < 50.0:
            level = "STABLE"
        elif score < 75.0:
            level = "WARNING"
        elif score < 90.0:
            level = "CRITICAL"
        else:
            level = "SEVERE"

        if not factors:
            factors.append({"factor": "optimal_operations", "impact": 0, "description": "All operational metrics within normal limits."})

        return {
            "score": round(score, 1),
            "level": level,
            "confidence": "HIGH",
            "factors": factors,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_shipments_requiring_attention(cls, user) -> List[Dict[str, Any]]:
        """
        Ranks active shipments requiring operational review by urgency.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user).exclude(
            status__in=[ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]
        ).select_related('load', 'transporter', 'driver')

        attention_items = []
        for shipment in shipments_qs:
            reasons = []
            priority_pts = 0

            # Incident check
            incidents = DriverIncidentReport.objects.filter(shipment=shipment)
            inc_count = incidents.count()
            crit_inc_count = incidents.filter(incident_type__in=['ACCIDENT', 'SECURITY_INCIDENT', 'VEHICLE_BREAKDOWN']).count()

            if crit_inc_count > 0:
                reasons.append(f"Critical incident reported ({crit_inc_count})")
                priority_pts += 40
            elif inc_count > 0:
                reasons.append(f"Active incident reported ({inc_count})")
                priority_pts += 20

            # Route deviation check
            active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
            dev_info = RouteOptimizationService.detect_route_deviation(shipment)
            deviation_status = dev_info.get("status", RouteDeviationStatus.UNKNOWN)
            if active_route and deviation_status == RouteDeviationStatus.DEVIATED:
                reasons.append("Shipment deviated from planned route")
                priority_pts += 30


            # ETA delay check
            eta_pred = PredictionRecord.objects.filter(shipment=shipment, prediction_type=PredictionType.ETA_DELAY).order_by('-created_at').first()
            predicted_delay = eta_pred.prediction_value.get('predicted_delay_minutes', 0) if eta_pred else 0
            if predicted_delay > 30:
                reasons.append(f"Significant ETA delay ({predicted_delay} mins)")
                priority_pts += 25
            elif predicted_delay > 15:
                reasons.append(f"Moderate ETA delay ({predicted_delay} mins)")
                priority_pts += 10

            # Operational risk check
            risk_pred = PredictionRecord.objects.filter(shipment=shipment, prediction_type=PredictionType.OPERATIONAL_RISK).order_by('-created_at').first()
            risk_score = risk_pred.risk_score if risk_pred else 0.0
            risk_lvl = risk_pred.risk_level if risk_pred else RiskLevel.LOW
            if risk_lvl == RiskLevel.CRITICAL:
                reasons.append("Critical operational risk level")
                priority_pts += 35
            elif risk_lvl == RiskLevel.HIGH:
                reasons.append("High operational risk level")
                priority_pts += 20

            # Pending automation recommendation check
            pending_rec = AutomationRecommendation.objects.filter(shipment=shipment, status=RecommendationStatus.PENDING).order_by('-priority', '-created_at').first()
            if pending_rec:
                reasons.append(f"Pending recommendation: {pending_rec.title}")
                priority_pts += 15

            # Stale GPS telemetry
            latest_gps = LocationUpdate.objects.filter(shipment=shipment).order_by('-timestamp').first()
            is_stale = False
            if not latest_gps or (timezone.now() - latest_gps.timestamp) > timedelta(minutes=30):
                is_stale = True
                reasons.append("Stale or missing GPS telemetry (>30m)")
                priority_pts += 15

            if priority_pts > 0 or reasons:
                priority = "CRITICAL" if priority_pts >= 50 else ("HIGH" if priority_pts >= 30 else "MEDIUM")
                latest_event = OperationalEvent.objects.filter(shipment=shipment).order_by('-created_at').first()
                latest_notif = Notification.objects.filter(event__shipment=shipment, recipient=user).order_by('-created_at').first()

                attention_items.append({
                    "shipment_id": shipment.id,
                    "shipment_reference": shipment.tracking_number,
                    "priority": priority,
                    "priority_score": priority_pts,
                    "risk_level": risk_lvl,
                    "risk_score": float(risk_score),
                    "attention_reasons": reasons,
                    "latest_event": {
                        "id": latest_event.id,
                        "type": latest_event.event_type,
                        "title": latest_event.title,
                        "created_at": latest_event.created_at.isoformat()
                    } if latest_event else None,
                    "latest_notification": {
                        "id": latest_notif.id,
                        "title": latest_notif.title,
                        "is_read": latest_notif.is_read,
                        "is_acknowledged": latest_notif.is_acknowledged
                    } if latest_notif else None,
                    "route_deviation_status": deviation_status,
                    "eta_status": f"DELAYED (+{predicted_delay}m)" if predicted_delay > 15 else "ON_SCHEDULE",
                    "incident_status": f"{inc_count} INCIDENT(S)" if inc_count > 0 else "NO_INCIDENTS",
                    "automation_status": pending_rec.status if pending_rec else "NO_PENDING",
                    "generated_at": timezone.now().isoformat()
                })

        attention_items.sort(key=lambda x: x["priority_score"], reverse=True)
        return attention_items

    @classmethod
    def get_alert_intelligence(cls, user, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analyzes operational events and notifications for alert breakdowns.
        """
        user_notifs_qs = Notification.objects.filter(recipient=user).select_related('event', 'event__shipment')

        total_alerts = user_notifs_qs.count()
        critical_alerts = user_notifs_qs.filter(event__severity=EventSeverity.CRITICAL).count()
        high_alerts = user_notifs_qs.filter(event__severity=EventSeverity.HIGH).count()
        medium_alerts = user_notifs_qs.filter(event__severity=EventSeverity.MEDIUM).count()
        low_alerts = user_notifs_qs.filter(event__severity=EventSeverity.LOW).count()

        unacknowledged_critical = user_notifs_qs.filter(
            event__severity=EventSeverity.CRITICAL,
            is_acknowledged=False
        ).count()

        top_events = user_notifs_qs.values('event__event_type').annotate(count=Count('id')).order_by('-count')[:5]
        top_event_types = [{"event_type": item['event__event_type'], "count": item['count']} for item in top_events]

        affected_shipments = user_notifs_qs.filter(event__shipment__isnull=False).values('event__shipment_id', 'event__shipment__tracking_number').annotate(alert_count=Count('id')).order_by('-alert_count')[:10]
        affected_list = [{
            "shipment_id": item['event__shipment_id'],
            "tracking_number": item['event__shipment__tracking_number'],
            "alert_count": item['alert_count']
        } for item in affected_shipments]

        return {
            "total_alerts": total_alerts,
            "critical_alerts": critical_alerts,
            "high_alerts": high_alerts,
            "medium_alerts": medium_alerts,
            "low_alerts": low_alerts,
            "unacknowledged_critical_alerts": unacknowledged_critical,
            "top_event_types": top_event_types,
            "affected_shipments": affected_list,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_alert_trends(cls, user, time_window: str = "24h") -> Dict[str, Any]:
        """
        Calculates time-bucketed operational alert trends for windows: 1h, 6h, 24h, 7d, 30d.
        """
        now = timezone.now()
        if time_window == "1h":
            start_time = now - timedelta(hours=1)
            bucket_delta = timedelta(minutes=10)
        elif time_window == "6h":
            start_time = now - timedelta(hours=6)
            bucket_delta = timedelta(hours=1)
        elif time_window == "7d":
            start_time = now - timedelta(days=7)
            bucket_delta = timedelta(days=1)
        elif time_window == "30d":
            start_time = now - timedelta(days=30)
            bucket_delta = timedelta(days=5)
        else:  # default 24h
            start_time = now - timedelta(hours=24)
            bucket_delta = timedelta(hours=3)

        events_qs = OperationalEvent.objects.filter(
            created_at__gte=start_time
        ).select_related('shipment')

        if not (user.is_superuser or user.role == Role.ADMIN):
            authorized_ids = cls._get_authorized_shipments_queryset(user).values_list('id', flat=True)
            events_qs = events_qs.filter(shipment_id__in=authorized_ids)

        buckets = []
        curr_start = start_time
        while curr_start < now:
            curr_end = curr_start + bucket_delta
            b_events = events_qs.filter(created_at__gte=curr_start, created_at__lt=curr_end)

            total = b_events.count()
            crit = b_events.filter(severity=EventSeverity.CRITICAL).count()
            high = b_events.filter(severity=EventSeverity.HIGH).count()
            med = b_events.filter(severity=EventSeverity.MEDIUM).count()
            low = b_events.filter(severity=EventSeverity.LOW).count()

            buckets.append({
                "timestamp": curr_start.isoformat(),
                "total": total,
                "critical": crit,
                "high": high,
                "medium": med,
                "low": low
            })
            curr_start = curr_end

        return {
            "period": time_window,
            "buckets": buckets,
            "generated_at": now.isoformat()
        }

    @classmethod
    def get_risk_distribution(cls, user) -> Dict[str, Any]:
        """
        Calculates operational risk level distribution counts & percentages.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user).exclude(
            status__in=[ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]
        )
        total_eval = shipments_qs.count()

        if total_eval == 0:
            return {
                "total_shipments_evaluated": 0,
                "distribution": {
                    "LOW": {"count": 0, "percentage": 0.0},
                    "MEDIUM": {"count": 0, "percentage": 0.0},
                    "HIGH": {"count": 0, "percentage": 0.0},
                    "CRITICAL": {"count": 0, "percentage": 0.0}
                },
                "generated_at": timezone.now().isoformat()
            }

        shipment_ids = list(shipments_qs.values_list('id', flat=True))
        latest_preds = PredictionRecord.objects.filter(
            shipment_id__in=shipment_ids,
            prediction_type=PredictionType.OPERATIONAL_RISK
        ).order_by('shipment_id', '-created_at')

        counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        seen = set()
        for pred in latest_preds:
            if pred.shipment_id not in seen:
                seen.add(pred.shipment_id)
                lvl = pred.risk_level or "LOW"
                if lvl in counts:
                    counts[lvl] += 1

        unpredicted = total_eval - len(seen)
        counts["LOW"] += max(0, unpredicted)

        dist = {}
        for lvl, cnt in counts.items():
            dist[lvl] = {
                "count": cnt,
                "percentage": round((cnt / total_eval) * 100.0, 1)
            }

        return {
            "total_shipments_evaluated": total_eval,
            "distribution": dist,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_incident_intelligence(cls, user) -> Dict[str, Any]:
        """
        Aggregates Phase 9 driver incident data.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user)
        incidents_qs = DriverIncidentReport.objects.filter(
            shipment__in=shipments_qs
        ).select_related('shipment', 'driver', 'reported_by')

        total_active = incidents_qs.exclude(shipment__status=ShipmentStatus.DELIVERED).count()

        by_type_query = incidents_qs.values('incident_type').annotate(count=Count('id')).order_by('-count')
        by_type = [{"incident_type": item['incident_type'], "count": item['count']} for item in by_type_query]

        crit_unresolved = incidents_qs.filter(
            incident_type__in=['ACCIDENT', 'SECURITY_INCIDENT', 'VEHICLE_BREAKDOWN']
        ).order_by('-reported_at')[:5]

        crit_unresolved_list = [{
            "id": inc.id,
            "shipment_id": inc.shipment_id,
            "tracking_number": inc.shipment.tracking_number,
            "incident_type": inc.incident_type,
            "description": inc.description,
            "location_name": inc.location_name,
            "reported_at": inc.reported_at.isoformat()
        } for inc in crit_unresolved]

        recent_incidents = incidents_qs.order_by('-reported_at')[:10]
        recent_list = [{
            "id": inc.id,
            "shipment_id": inc.shipment_id,
            "tracking_number": inc.shipment.tracking_number,
            "incident_type": inc.incident_type,
            "description": inc.description,
            "location_name": inc.location_name,
            "reported_at": inc.reported_at.isoformat()
        } for inc in recent_incidents]

        return {
            "total_active_incidents": total_active,
            "incidents_by_type": by_type,
            "critical_unresolved_incidents": crit_unresolved_list,
            "recently_reported_incidents": recent_list,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_route_telemetry_intelligence(cls, user) -> Dict[str, Any]:
        """
        Aggregates Phase 10 route and telemetry intelligence.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user).exclude(
            status__in=[ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]
        )
        active_ids = list(shipments_qs.values_list('id', flat=True))

        active_routes = Route.objects.filter(shipment_id__in=active_ids, is_active=True).select_related('shipment')
        deviated_count = 0
        for r in active_routes:
            if RouteOptimizationService.detect_route_deviation(r.shipment).get("status") == RouteDeviationStatus.DEVIATED:
                deviated_count += 1


        # GPS Telemetry Freshness
        thirty_mins_ago = timezone.now() - timedelta(minutes=30)
        recent_gps_ids = set(
            LocationUpdate.objects.filter(
                shipment_id__in=active_ids,
                timestamp__gte=thirty_mins_ago
            ).values_list('shipment_id', flat=True)
        )
        stale_gps_count = max(0, len(active_ids) - len(recent_gps_ids))

        latest_telemetry = LocationUpdate.objects.filter(
            shipment_id__in=active_ids
        ).order_by('-timestamp').first()

        latest_timestamp = latest_telemetry.timestamp.isoformat() if latest_telemetry else None

        # High ETA delay check
        eta_preds = PredictionRecord.objects.filter(
            shipment_id__in=active_ids,
            prediction_type=PredictionType.ETA_DELAY
        ).order_by('shipment_id', '-created_at')

        high_delay_count = 0
        seen = set()
        for pred in eta_preds:
            if pred.shipment_id not in seen:
                seen.add(pred.shipment_id)
                if pred.prediction_value.get('predicted_delay_minutes', 0) > 30:
                    high_delay_count += 1

        return {
            "shipments_currently_deviated": deviated_count,
            "average_deviation_distance_km": 0.0,
            "maximum_deviation_distance_km": 0.0,
            "stale_gps_shipment_count": stale_gps_count,
            "recent_telemetry_timestamp": latest_timestamp,
            "missing_telemetry_count": stale_gps_count,
            "high_eta_delay_shipment_count": high_delay_count,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_market_pricing_intelligence(cls, user) -> Dict[str, Any]:
        """
        Aggregates Phase 12 market pressure & dynamic pricing intelligence.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user).exclude(
            status__in=[ShipmentStatus.DELIVERED, ShipmentStatus.CANCELLED]
        )
        active_ids = list(shipments_qs.values_list('id', flat=True))

        latest_pricing = PriceRecommendation.objects.filter(
            shipment_id__in=active_ids
        ).order_by('shipment_id', '-created_at')

        pressure_counts = {"HIGH": 0, "NORMAL": 0, "LOW": 0}
        conf_scores = []
        low_conf_count = 0
        seen = set()

        for rec in latest_pricing:
            if rec.shipment_id not in seen:
                seen.add(rec.shipment_id)
                press = rec.market_pressure or "NORMAL"
                if press in pressure_counts:
                    pressure_counts[press] += 1

                score = float(rec.pricing_confidence_score)
                conf_scores.append(score)
                if score < 0.60:
                    low_conf_count += 1

        avg_conf = round(sum(conf_scores) / max(1, len(conf_scores)), 2) if conf_scores else 1.0

        latest_snapshot_rec = PriceRecommendation.objects.order_by('-created_at').first()
        latest_snapshot_time = latest_snapshot_rec.created_at.isoformat() if latest_snapshot_rec else None

        return {
            "high_market_pressure_count": pressure_counts["HIGH"],
            "normal_market_pressure_count": pressure_counts["NORMAL"],
            "low_market_pressure_count": pressure_counts["LOW"],
            "average_pricing_confidence": avg_conf,
            "shipments_with_low_pricing_confidence": low_conf_count,
            "latest_market_snapshot_timestamp": latest_snapshot_time,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_automation_workflow_intelligence(cls, user) -> Dict[str, Any]:
        """
        Aggregates Phase 13 automation workflow recommendations & executions.
        """
        shipments_qs = cls._get_authorized_shipments_queryset(user)
        recs_qs = AutomationRecommendation.objects.filter(shipment__in=shipments_qs)

        pending = recs_qs.filter(status=RecommendationStatus.PENDING).count()
        approved = recs_qs.filter(status=RecommendationStatus.APPROVED).count()
        rejected = recs_qs.filter(status=RecommendationStatus.REJECTED).count()
        executed = recs_qs.filter(status=RecommendationStatus.EXECUTED).count()

        failed_executions = AutomationExecution.objects.filter(
            recommendation__shipment__in=shipments_qs,
            status='FAILED'
        ).count()

        by_priority_query = recs_qs.values('priority').annotate(count=Count('id')).order_by('-count')
        by_priority = [{"priority": item['priority'], "count": item['count']} for item in by_priority_query]

        by_rule_query = recs_qs.values('rule__rule_type').annotate(count=Count('id')).order_by('-count')
        by_rule_type = [{"rule_type": item['rule__rule_type'], "count": item['count']} for item in by_rule_query]

        crit_pending = recs_qs.filter(status=RecommendationStatus.PENDING, priority=RecommendationPriority.CRITICAL).count()
        high_pending = recs_qs.filter(status=RecommendationStatus.PENDING, priority=RecommendationPriority.HIGH).count()

        return {
            "pending_recommendations": pending,
            "approved_recommendations": approved,
            "rejected_recommendations": rejected,
            "executed_recommendations": executed,
            "failed_executions": failed_executions,
            "critical_pending_recommendations": crit_pending,
            "high_pending_recommendations": high_pending,
            "recommendations_by_priority": by_priority,
            "recommendations_by_rule_type": by_rule_type,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def correlate_shipment_events(cls, shipment: Shipment) -> Dict[str, Any]:
        """
        Performs deterministic multi-signal event correlation for a specific shipment.
        Combines signals from route deviation, incidents, risk predictions, ETA delay, market pressure, and telemetry.
        """
        signals = []
        factors = []
        score = 0.0

        # Signal 1: Route Deviation
        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        dev_info = RouteOptimizationService.detect_route_deviation(shipment)
        if active_route and dev_info.get("status") == RouteDeviationStatus.DEVIATED:
            signals.append("ROUTE_DEVIATION")
            score += 30.0
            factors.append({"signal": "ROUTE_DEVIATION", "impact": 30, "description": "Vehicle is off planned corridor."})

        # Signal 2: Active Incident
        incidents = DriverIncidentReport.objects.filter(shipment=shipment)
        if incidents.exists():
            signals.append("INCIDENT_REPORTED")
            score += 25.0
            factors.append({"signal": "INCIDENT_REPORTED", "impact": 25, "description": f"{incidents.count()} incident(s) logged."})

        # Signal 3: High Operational Risk
        risk_pred = PredictionRecord.objects.filter(shipment=shipment, prediction_type=PredictionType.OPERATIONAL_RISK).order_by('-created_at').first()
        if risk_pred and risk_pred.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            signals.append("HIGH_OPERATIONAL_RISK")
            score += 25.0
            factors.append({"signal": "HIGH_OPERATIONAL_RISK", "impact": 25, "description": f"Risk level: {risk_pred.risk_level}."})

        # Signal 4: Significant ETA Delay
        eta_pred = PredictionRecord.objects.filter(shipment=shipment, prediction_type=PredictionType.ETA_DELAY).order_by('-created_at').first()
        if eta_pred and eta_pred.prediction_value.get('predicted_delay_minutes', 0) > 30:
            signals.append("ETA_DELAY")
            score += 20.0
            factors.append({"signal": "ETA_DELAY", "impact": 20, "description": "Predicted delay exceeds 30 minutes."})

        # Signal 5: Stale GPS Telemetry
        latest_gps = LocationUpdate.objects.filter(shipment=shipment).order_by('-timestamp').first()
        if not latest_gps or (timezone.now() - latest_gps.timestamp) > timedelta(minutes=30):
            signals.append("STALE_GPS_DATA")
            score += 15.0
            factors.append({"signal": "STALE_GPS_DATA", "impact": 15, "description": "No GPS update in >30 minutes."})

        score = min(100.0, score)

        if score >= 70.0:
            level = "CRITICAL"
        elif score >= 40.0:
            level = "HIGH"
        elif score >= 20.0:
            level = "MEDIUM"
        else:
            level = "LOW"

        # Deterministic correlation key
        signal_str = ":".join(sorted(signals))
        raw_key = f"corr_{shipment.id}_{signal_str}"
        correlation_key = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()[:16]

        return {
            "shipment_id": shipment.id,
            "correlation_key": correlation_key,
            "correlation_level": level,
            "score": round(score, 1),
            "signals": signals,
            "explanation": factors,
            "generated_at": timezone.now().isoformat()
        }

    @classmethod
    def get_unified_shipment_operational_summary(cls, shipment_id: int, user) -> Dict[str, Any]:
        """
        Unified operational summary combining all Phase 9-14 intelligence for a single shipment.
        Enforces participant authorization.
        """
        shipment = cls._get_authorized_shipments_queryset(user).filter(id=shipment_id).first()
        if not shipment:
            return {}

        # Risk Intelligence
        risk_summary = OperationalRiskService.get_composite_dashboard(shipment)


        # ETA Delay Prediction
        eta_summary = ETADelayPredictionService.predict_eta_delay(shipment)


        # Route & Telemetry
        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        dev_info = RouteOptimizationService.detect_route_deviation(shipment)
        route_info = {
            "status": active_route.status if active_route else "PLANNED",
            "deviation_status": dev_info.get("status", "UNKNOWN"),
            "total_distance_km": float(active_route.total_distance_km) if active_route else 0.0,
            "estimated_duration_hours": float(active_route.estimated_duration_hours) if active_route else 0.0
        }


        # Fuel Analytics
        fuel_analytics = RouteOptimizationService.calculate_fuel_analytics(shipment)

        # Active Incidents
        incidents = DriverIncidentReport.objects.filter(shipment=shipment)
        incident_info = {
            "active_incidents_count": incidents.count(),
            "critical_incidents_count": incidents.filter(incident_type__in=['ACCIDENT', 'SECURITY_INCIDENT', 'VEHICLE_BREAKDOWN']).count(),
            "latest_incident": incidents.order_by('-reported_at').values('id', 'incident_type', 'description', 'reported_at').first()
        }

        # Pricing & Market Intelligence
        price_rec = DynamicPricingService.generate_price_recommendation(shipment)

        # Automation Recommendations
        pending_recs = AutomationRecommendation.objects.filter(shipment=shipment, status=RecommendationStatus.PENDING).order_by('-priority')
        highest_rec = pending_recs.first()

        automation_info = {
            "pending_count": pending_recs.count(),
            "highest_priority_recommendation": {
                "id": highest_rec.id,
                "title": highest_rec.title,
                "priority": highest_rec.priority,
                "recommendation_type": highest_rec.recommendation_type
            } if highest_rec else None
        }

        # Notifications
        user_notifs = Notification.objects.filter(event__shipment=shipment, recipient=user)
        unread_count = user_notifs.filter(is_read=False).count()
        unack_crit_count = user_notifs.filter(event__severity=EventSeverity.CRITICAL, is_acknowledged=False).count()

        # Operational Events
        recent_events = OperationalEvent.objects.filter(shipment=shipment).order_by('-created_at')[:5]
        events_list = [{
            "id": ev.id,
            "event_type": ev.event_type,
            "severity": ev.severity,
            "title": ev.title,
            "created_at": ev.created_at.isoformat()
        } for ev in recent_events]

        # Event Correlation
        correlation = cls.correlate_shipment_events(shipment)

        return {
            "shipment": {
                "id": shipment.id,
                "tracking_number": shipment.tracking_number,
                "status": shipment.status,
                "origin": shipment.load.origin,
                "destination": shipment.load.destination,
                "shipper": shipment.load.shipper.company_name if hasattr(shipment.load, 'shipper') else None,
                "transporter": shipment.transporter.company_name if hasattr(shipment, 'transporter') and shipment.transporter else None,
                "driver": shipment.driver.user.get_full_name() if hasattr(shipment, 'driver') and shipment.driver else None
            },
            "risk": risk_summary,
            "eta": eta_summary,
            "route": route_info,
            "fuel": fuel_analytics,
            "incidents": incident_info,
            "pricing": price_rec,
            "automation": automation_info,
            "notifications": {
                "unread_count": unread_count,
                "unacknowledged_critical_count": unack_crit_count
            },
            "latest_events": events_list,
            "event_correlation": correlation,
            "generated_at": timezone.now().isoformat()
        }
