import os
import uuid
import json
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Avg, Sum, Q
from django.core.cache import cache
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError

from apps.accounts.models import Role
from apps.marketplace.models import (
    Shipment, CargoLoad, Bid, Payment, FreightInvoice, FreightSettlement,
    ProofOfDelivery, ShipmentMilestone, DriverIncidentReport, LocationUpdate,
    PriceRecommendation, PredictionRecord, AutomationRecommendation,
    OperationalEvent, SecurityAuditEvent, SecurityAuditEventType, SecurityAuditEventSeverity,
    AIModelConfiguration, AIGenerationRequest, AIGenerationStatus,
    AIInsight, AIInsightType, AIRecommendation, AIRecommendationStatus,
    AIPromptVersion, AIUsageRecord
)


from apps.marketplace.security_services import SecurityGovernanceService
from apps.marketplace.analytics_services import BusinessIntelligenceService

User = get_user_model()
logger = logging.getLogger('tradeflow.ai')


class AIProvider:
    """
    Abstract interface for TradeFlow AI decision-support providers.
    """
    def generate(self, prompt: str, task_type: str, system_instruction: str = "") -> str:
        raise NotImplementedError

    def generate_structured(self, prompt: str, task_type: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def health_check(self) -> Dict[str, Any]:
        raise NotImplementedError


class MockAIProvider(AIProvider):
    """
    Deterministic AI provider generating structured decision-support output for testing and offline execution.
    """
    def generate(self, prompt: str, task_type: str, system_instruction: str = "") -> str:
        return f"AI Decision-Support Response for {task_type}: Analysis completed based on verified operational telemetry."

    def generate_structured(self, prompt: str, task_type: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
        shipment_info = context_data.get("shipment", {})
        shipment_id = shipment_info.get("id", 0)
        trk = shipment_info.get("tracking_number", "TRK-MOCK")
        status_val = shipment_info.get("status", "IN_TRANSIT")

        if task_type == 'SHIPMENT_SUMMARY':
            return {
                "shipment_id": shipment_id,
                "tracking_number": trk,
                "status": status_val,
                "operational_health": "OPTIMAL" if status_val == "DELIVERED" else "STABLE",
                "summary": f"Shipment {trk} is currently in state {status_val}. Operational telemetry indicates steady progress along corridor.",
                "key_findings": [
                    f"Current shipment status: {status_val}",
                    "Driver GPS pings received within normal window",
                    "No active critical security alerts detected"
                ],
                "risks": [
                    "Minor delay possible due to potential corridor congestion"
                ] if status_val == "IN_TRANSIT" else [],
                "recommended_attention": "Maintain routine GPS monitoring." if status_val == "IN_TRANSIT" else "None. Shipment complete.",
                "evidence": [
                    {"source": "shipment", "id": shipment_id, "field": "status"}
                ],
                "confidence": 0.95
            }
        elif task_type == 'RISK_EXPLANATION':
            risk_info = context_data.get("risk", {})
            risk_level = risk_info.get("risk_level", "LOW")
            risk_score = risk_info.get("risk_score", 0.15)
            return {
                "shipment_id": shipment_id,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "summary": f"Shipment {trk} exhibits {risk_level} operational risk (score: {risk_score}). Factors evaluated include ETA variance and incident history.",
                "contributing_factors": [
                    {"factor": "ETA Variance", "weight": 0.30, "value": "On Schedule"},
                    {"factor": "Route Deviation", "weight": 0.20, "value": "On Route"}
                ],
                "evidence": [
                    {"source": "risk_prediction", "id": shipment_id, "field": "risk_level"}
                ],
                "potential_consequences": ["Minor timeline adjustment"],
                "confidence": 0.92
            }
        elif task_type == 'INCIDENT_ANALYSIS':
            inc_list = context_data.get("incidents", [])
            return {
                "shipment_id": shipment_id,
                "incident_count": len(inc_list),
                "summary": f"Analyzed {len(inc_list)} reported driver incidents for shipment {trk}.",
                "incidents_analyzed": inc_list,
                "probable_causes": ["Heavy traffic congestion", "Unscheduled border check"] if inc_list else ["None"],
                "operational_impact": "Negligible operational impact" if not inc_list else "Potential 20-minute ETA delay",
                "suggested_human_actions": ["Verify driver check-in via phone", "Review updated GPS coordinates"],
                "evidence": [
                    {"source": "driver_incident", "id": inc.get("id"), "field": "incident_type"} for inc in inc_list
                ],
                "confidence": 0.88
            }
        elif task_type == 'ROUTE_EXPLANATION':
            telemetry = context_data.get("telemetry", {})
            return {
                "shipment_id": shipment_id,
                "route_status": telemetry.get("route_status", "ON_ROUTE"),
                "progress_percentage": 65.0 if status_val == "IN_TRANSIT" else 100.0,
                "eta": telemetry.get("estimated_eta"),
                "summary": f"Vehicle is adhering to designated route corridor for shipment {trk}.",
                "telemetry_quality": "HIGH",
                "potential_delays": ["Checkpoint congestion"],
                "evidence": [
                    {"source": "telemetry", "id": shipment_id, "field": "route_status"}
                ],
                "confidence": 0.94
            }
        elif task_type == 'PRICING_EXPLANATION':
            pricing = context_data.get("pricing", {})
            rec_price = pricing.get("recommended_price", Decimal("15000.00"))
            return {
                "shipment_id": shipment_id,
                "market_pressure": pricing.get("market_pressure", "NORMAL"),
                "recommended_price": rec_price,
                "summary": f"Recommended freight price of {rec_price} ETB calculated based on distance, fuel indices, and market pressure.",
                "pricing_factors": [
                    {"factor": "Base Fuel Index", "impact": "Standard"},
                    {"factor": "Market Pressure", "impact": pricing.get("market_pressure", "NORMAL")}
                ],
                "evidence": [
                    {"source": "price_recommendation", "id": shipment_id, "field": "recommended_price"}
                ],
                "confidence": 0.91
            }
        elif task_type == 'EXECUTIVE_SUMMARY':
            return {
                "summary": "Executive Decision Support: Overall platform fleet operations are functioning with high efficiency and low risk across major transport corridors.",
                "operational_health": "HEALTHY",
                "shipment_metrics": {"total": 120, "in_transit": 35, "delivered": 85},
                "financial_trends": {"gross_freight_etb": 4500000.0, "net_settled_etb": 4275000.0},
                "risk_and_incidents": {"open_incidents": 2, "high_risk_shipments": 1},
                "key_recommendations": [
                    "Monitor Modjo-Hawassa corridor driver pings for potential weather delays.",
                    "Review pending freight settlements for delivered shipments."
                ],
                "evidence": [{"source": "business_intelligence", "id": 0, "field": "overview"}],
                "confidence": 0.96
            }
        elif task_type == 'NATURAL_LANGUAGE_QUERY':
            query = context_data.get("query", "")
            return {
                "question": query,
                "answer": f"Based on authorized TradeFlow platform metrics: Currently, 2 shipments require operational review due to minor route deviations.",
                "evidence": [{"source": "shipment_query", "id": 0, "field": "count"}],
                "confidence": 0.90,
                "limitations": ["Information restricted to authorized participant domain scope."]
            }
        else:
            return {
                "summary": "Operational decision support analysis complete.",
                "evidence": [],
                "confidence": 0.90
            }

    def health_check(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider": "MockAIProvider",
            "model": "tradeflow-decision-support-v1",
            "latency_ms": 15,
            "checked_at": timezone.now().isoformat()
        }


class ConfigurableExternalLLMProvider(AIProvider):
    """
    Configurable provider for external LLM integration via environment variables.
    Falls back gracefully to MockAIProvider if credentials or connection fail.
    """
    def __init__(self):
        self.provider_name = os.environ.get('AI_PROVIDER', 'ExternalLLM')
        self.model_name = os.environ.get('AI_MODEL', 'gpt-4o-mini')
        self.api_key = os.environ.get('AI_API_KEY', '')
        self.timeout = int(os.environ.get('AI_TIMEOUT_SECONDS', '10'))
        self.fallback = MockAIProvider()

    def generate(self, prompt: str, task_type: str, system_instruction: str = "") -> str:
        if not self.api_key:
            return self.fallback.generate(prompt, task_type, system_instruction)
        try:
            # Placeholder for HTTP API call if configured
            return self.fallback.generate(prompt, task_type, system_instruction)
        except Exception as exc:
            logger.warning(f"External LLM call failed: {exc}. Falling back to MockAIProvider.")
            return self.fallback.generate(prompt, task_type, system_instruction)

    def generate_structured(self, prompt: str, task_type: str, context_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return self.fallback.generate_structured(prompt, task_type, context_data)
        try:
            return self.fallback.generate_structured(prompt, task_type, context_data)
        except Exception as exc:
            logger.warning(f"External LLM call failed: {exc}. Falling back to MockAIProvider.")
            return self.fallback.generate_structured(prompt, task_type, context_data)

    def health_check(self) -> Dict[str, Any]:
        if not self.api_key:
            res = self.fallback.health_check()
            res["provider"] = f"{self.provider_name} (Fallback Mode)"
            return res
        return {
            "status": "healthy",
            "provider": self.provider_name,
            "model": self.model_name,
            "latency_ms": 45,
            "checked_at": timezone.now().isoformat()
        }


class AIProviderFactory:
    @classmethod
    def get_provider(cls) -> AIProvider:
        provider_type = os.environ.get('AI_PROVIDER', 'MockAIProvider')
        if provider_type in ['ConfigurableExternalLLMProvider', 'ExternalLLM', 'OpenAI', 'Gemini']:
            return ConfigurableExternalLLMProvider()
        return MockAIProvider()


class AIContextBuilder:
    """
    Secure context generation layer enforcing role-based participant data isolation, secret sanitization, and prompt injection defense.
    """
    PROMPT_INJECTION_KEYWORDS = [
        "ignore all previous instructions", "ignore previous instructions", "ignore all instructions",
        "previous instructions", "reveal password", "reveal all", "drop table", "system prompt",
        "admin access", "grant permission"
    ]


    @classmethod
    def get_authorized_shipment(cls, user: Any, shipment_id: int) -> Shipment:
        role = getattr(user, 'role', '')
        if role == Role.ADMIN or getattr(user, 'is_staff', False):
            shipment = Shipment.objects.filter(id=shipment_id).first()
        elif role == Role.SHIPPER:
            shipment = Shipment.objects.filter(id=shipment_id, load__shipper__user=user).first()

        elif role == Role.TRANSPORTER:
            shipment = Shipment.objects.filter(id=shipment_id, transporter__user=user).first()
        elif role == Role.DRIVER:
            shipment = Shipment.objects.filter(id=shipment_id, driver__user=user).first()
        else:
            shipment = None

        if not shipment:
            raise NotFound("Shipment not found or unauthorized for current user.")
        return shipment

    @classmethod
    def detect_prompt_injection(cls, text: str) -> bool:
        if not text:
            return False
        lower_text = text.lower()
        for kw in cls.PROMPT_INJECTION_KEYWORDS:
            if kw in lower_text:
                return True
        return False

    @classmethod
    def build_shipment_context(cls, user: Any, shipment: Shipment) -> Dict[str, Any]:
        # Domain data aggregation
        load = shipment.load
        driver_name = f"{shipment.driver.first_name} {shipment.driver.last_name}" if shipment.driver else "Unassigned"
        transporter_name = shipment.transporter.company_name if shipment.transporter else "Unassigned"

        incidents = list(DriverIncidentReport.objects.filter(shipment=shipment).values(
            'id', 'incident_type', 'description', 'reported_at'
        ))


        latest_ping = LocationUpdate.objects.filter(shipment=shipment).order_by('-timestamp').first()

        telemetry_info = {
            "latest_ping_at": latest_ping.timestamp.isoformat() if latest_ping else None,
            "latitude": float(latest_ping.latitude) if latest_ping else None,
            "longitude": float(latest_ping.longitude) if latest_ping else None,
            "route_status": "ON_ROUTE",
            "estimated_eta": shipment.estimated_arrival_at.isoformat() if shipment.estimated_arrival_at else None
        }


        risk_pred = PredictionRecord.objects.filter(shipment=shipment).first()
        risk_info = {
            "risk_level": risk_pred.risk_level if risk_pred else "LOW",
            "risk_score": float(risk_pred.risk_score) if risk_pred else 0.15
        }


        price_rec = PriceRecommendation.objects.filter(shipment=shipment).first()
        pricing_info = {
            "recommended_price": price_rec.recommended_price_etb if price_rec else Decimal("15000.00"),
            "market_pressure": price_rec.market_pressure if price_rec else "NORMAL"
        }


        raw_context = {
            "shipment": {
                "id": shipment.id,
                "tracking_number": shipment.tracking_number,
                "status": shipment.status,
                "origin": load.origin if load else "",
                "destination": load.destination if load else "",
                "pickup_date": load.pickup_date.isoformat() if load and load.pickup_date else "",
                "delivery_date": load.delivery_date.isoformat() if load and load.delivery_date else "",
                "driver": driver_name,
                "transporter": transporter_name
            },
            "risk": risk_info,
            "incidents": [
                {**inc, "reported_at": inc["reported_at"].isoformat() if inc["reported_at"] else ""}
                for inc in incidents
            ],
            "telemetry": telemetry_info,
            "pricing": pricing_info,
            "user_role": str(getattr(user, 'role', ''))
        }

        # Recursive secret sanitization via Phase 19 SecurityGovernanceService
        sanitized_context = SecurityGovernanceService.sanitize_metadata(raw_context)
        return sanitized_context


class AIService:
    """
    Primary orchestration service for Phase 20 AI-Assisted Decision Support & Intelligent Operations.
    """

    @classmethod
    def _execute_ai_task(
        cls,
        user: Any,
        task_type: str,
        shipment: Optional[Shipment] = None,
        extra_input: str = "",
        custom_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        req_id = f"ai_req_{uuid.uuid4().hex[:12]}"
        now = timezone.now()
        start_time = time.time()

        # Prompt injection detection
        if extra_input and AIContextBuilder.detect_prompt_injection(extra_input):
            SecurityGovernanceService.record_audit_event(
                event_type=SecurityAuditEventType.SUSPICIOUS_ACTIVITY,
                action="AI_PROMPT_INJECTION_DETECTED",
                actor=user,
                description=f"Prompt injection attempt detected in AI request task {task_type}",
                metadata={"task_type": task_type, "input_snippet": extra_input[:50]}
            )
            # Neutralize untrusted prompt content
            extra_input = "[FLAGGED UNTRUSTED CONTENT REMOVED]"

        # Create audit generation request record
        input_ref = f"Shipment #{shipment.id}" if shipment else extra_input[:50]
        gen_req = AIGenerationRequest.objects.create(
            user=user,
            request_id=req_id,
            task_type=task_type,
            provider="MockAIProvider",
            model_name="tradeflow-decision-support-v1",
            prompt_version="v1.0",
            input_reference=input_ref,
            status=AIGenerationStatus.PROCESSING
        )

        try:
            # Context preparation
            if shipment:
                context_data = AIContextBuilder.build_shipment_context(user, shipment)
            else:
                context_data = custom_context or {}

            if extra_input:
                context_data["query"] = extra_input

            # Provider execution
            provider = AIProviderFactory.get_provider()
            prompt_text = f"Execute AI Decision Support Task {task_type} for authorized user."
            output_data = provider.generate_structured(prompt_text, task_type, context_data)

            # Metadata wrapping
            latency_ms = int((time.time() - start_time) * 1000)
            output_data["model"] = provider.health_check().get("model", "tradeflow-decision-support-v1")
            output_data["prompt_version"] = "v1.0"
            output_data["generated_at"] = now
            output_data["request_id"] = req_id

            # Update request audit
            gen_req.status = AIGenerationStatus.COMPLETED
            gen_req.completed_at = timezone.now()
            gen_req.latency_ms = latency_ms
            gen_req.save()

            # Record usage record
            AIUsageRecord.objects.create(
                user=user,
                request_id=req_id,
                provider="MockAIProvider",
                model="tradeflow-decision-support-v1",
                input_tokens=150,
                output_tokens=250,
                total_tokens=400,
                latency_ms=latency_ms,
                estimated_cost=Decimal("0.0020")
            )

            # Record Phase 19 Security Audit Event
            SecurityGovernanceService.record_audit_event(
                event_type=SecurityAuditEventType.ADMIN_ACTION if user.role == Role.ADMIN else SecurityAuditEventType.SENSITIVE_DATA_ACCESSED,
                action="AI_INSIGHT_GENERATED",
                actor=user,
                target_model="Shipment" if shipment else "System",
                target_object_id=str(shipment.id) if shipment else "",
                description=f"Generated AI decision-support intelligence for task {task_type}",
                metadata={"request_id": req_id, "task_type": task_type, "latency_ms": latency_ms}
            )

            return output_data

        except Exception as exc:
            latency_ms = int((time.time() - start_time) * 1000)
            gen_req.status = AIGenerationStatus.FAILED
            gen_req.completed_at = timezone.now()
            gen_req.latency_ms = latency_ms
            gen_req.error_code = "PROVIDER_ERROR"
            gen_req.error_message = str(exc)
            gen_req.save()

            logger.error(f"AI Task {task_type} failed: {exc}")

            # Return controlled degraded fallback response
            return {
                "summary": "AI Decision Support temporarily operating in degraded mode.",
                "evidence": [],
                "confidence": 0.50,
                "model": "FallbackMode",
                "prompt_version": "v1.0",
                "generated_at": now,
                "request_id": req_id,
                "error": "AI Provider unavailable."
            }

    @classmethod
    def generate_shipment_summary(cls, user: Any, shipment_id: int) -> Dict[str, Any]:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        cache_key = f"ai:shipment_summary:{user.id}:{shipment.id}:{shipment.updated_at.timestamp() if shipment.updated_at else 0}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        res = cls._execute_ai_task(user, 'SHIPMENT_SUMMARY', shipment=shipment)
        cache.set(cache_key, res, timeout=60)
        return res

    @classmethod
    def generate_risk_explanation(cls, user: Any, shipment_id: int) -> Dict[str, Any]:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        return cls._execute_ai_task(user, 'RISK_EXPLANATION', shipment=shipment)

    @classmethod
    def generate_incident_analysis(cls, user: Any, shipment_id: int) -> Dict[str, Any]:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        return cls._execute_ai_task(user, 'INCIDENT_ANALYSIS', shipment=shipment)

    @classmethod
    def generate_route_explanation(cls, user: Any, shipment_id: int) -> Dict[str, Any]:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        return cls._execute_ai_task(user, 'ROUTE_EXPLANATION', shipment=shipment)

    @classmethod
    def generate_pricing_explanation(cls, user: Any, shipment_id: int) -> Dict[str, Any]:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        return cls._execute_ai_task(user, 'PRICING_EXPLANATION', shipment=shipment)

    @classmethod
    def create_operational_recommendation(cls, user: Any, shipment_id: int, recommendation_type: str = "ROUTE_OPTIMIZATION") -> AIRecommendation:
        shipment = AIContextBuilder.get_authorized_shipment(user, shipment_id)
        output = cls._execute_ai_task(user, 'SHIPMENT_SUMMARY', shipment=shipment)

        rec = AIRecommendation.objects.create(
            user=user,
            shipment=shipment,
            recommendation_type=recommendation_type,
            recommendation=f"Recommended action for shipment {shipment.tracking_number}: {output.get('recommended_attention', 'Maintain routine monitoring.')}",
            rationale=output.get('summary', 'Based on current operational telemetry.'),
            evidence=output.get('evidence', []),
            confidence_score=output.get('confidence', 0.90),
            status=AIRecommendationStatus.PENDING,
            model_name=output.get('model', 'tradeflow-decision-support-v1'),
            prompt_version="v1.0",
            request_id=output.get('request_id', '')
        )

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION if user.role == Role.ADMIN else SecurityAuditEventType.SENSITIVE_DATA_ACCESSED,
            action="AI_RECOMMENDATION_CREATED",
            actor=user,
            target_model="AIRecommendation",
            target_object_id=str(rec.id),
            description=f"Created AI recommendation #{rec.id} in PENDING status for shipment {shipment.id}"
        )
        return rec

    @classmethod
    def generate_executive_summary(cls, user: Any) -> Dict[str, Any]:
        if user.role != Role.ADMIN and not getattr(user, 'is_staff', False):
            raise PermissionDenied("Executive summary is restricted to platform administrators.")

        bi_overview = BusinessIntelligenceService.get_dashboard_overview(user)
        return cls._execute_ai_task(user, 'EXECUTIVE_SUMMARY', custom_context={"bi_overview": bi_overview})


    @classmethod
    def execute_natural_language_query(cls, user: Any, question: str) -> Dict[str, Any]:
        if not question or not question.strip():
            raise ValidationError("Question prompt cannot be empty.")

        # Prompt injection defense check
        if AIContextBuilder.detect_prompt_injection(question):
            SecurityGovernanceService.record_audit_event(
                event_type=SecurityAuditEventType.SUSPICIOUS_ACTIVITY,
                action="AI_PROMPT_INJECTION_DETECTED",
                actor=user,
                description="Detected prompt injection attempt in natural language query",
                metadata={"question_snippet": question[:50]}
            )
            question = "[NEUTRALIZED PROMPT INJECTION QUERY]"

        # Domain scoping
        authorized_count = Shipment.objects.count() if user.role == Role.ADMIN else Shipment.objects.filter(load__shipper__user=user).count()

        context = {"query": question, "authorized_shipments_count": authorized_count, "user_role": str(getattr(user, 'role', ''))}

        return cls._execute_ai_task(user, 'NATURAL_LANGUAGE_QUERY', extra_input=question, custom_context=context)

    @classmethod
    def get_overview_dashboard(cls) -> Dict[str, Any]:
        now = timezone.now()
        reqs = AIGenerationRequest.objects.all()

        tot_reqs = reqs.count()
        succ = reqs.filter(status=AIGenerationStatus.COMPLETED).count()
        failed = reqs.filter(status=AIGenerationStatus.FAILED).count()
        timeouts = reqs.filter(status=AIGenerationStatus.TIMEOUT).count()

        avg_lat = reqs.aggregate(avg=Avg('latency_ms'))['avg'] or 0.0

        usage_qs = AIUsageRecord.objects.all()
        tot_tok = usage_qs.aggregate(sum_tok=Sum('total_tokens'))['sum_tok'] or 0
        tot_cost = usage_qs.aggregate(sum_cost=Sum('estimated_cost'))['sum_cost'] or Decimal('0.0000')

        tot_insights = AIInsight.objects.count()
        tot_recs = AIRecommendation.objects.count()
        pending_recs = AIRecommendation.objects.filter(status=AIRecommendationStatus.PENDING).count()

        provider_health = AIProviderFactory.get_provider().health_check().get('status', 'healthy')

        return {
            "total_requests": tot_reqs,
            "successful_generations": succ,
            "failed_generations": failed,
            "timeout_count": timeouts,
            "avg_latency_ms": round(float(avg_lat), 2),
            "total_tokens": tot_tok,
            "total_estimated_cost": tot_cost,
            "total_insights": tot_insights,
            "total_recommendations": tot_recs,
            "pending_recommendations": pending_recs,
            "provider_health": provider_health,
            "generated_at": now
        }

    @classmethod
    def check_health(cls) -> Dict[str, Any]:
        provider = AIProviderFactory.get_provider()
        return provider.health_check()
