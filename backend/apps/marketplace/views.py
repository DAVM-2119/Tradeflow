from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from django.shortcuts import get_object_or_404
from django.http import FileResponse, Http404
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.accounts.models import Role, VerificationStatus, TransporterProfile, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
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
)
from apps.marketplace.services import (
    VerificationService,
    FleetService,
    LoadService,
    BiddingService,
    TrackingService,
    ETAService,
    DocumentService,
    PODService,
    InvoiceService,
    SettlementService,
    PaymentService,
    ReconciliationService,
    PayoutService,
    DisputeService,
    IncidentReportService,
    OfflineSyncService,
    RouteOptimizationService,
)
from apps.marketplace.permissions import (
    IsTransporterVerified,
    IsVehicleOwnerOrAdmin,
    IsLoadOwnerOrAdmin,
    IsBidOwnerOrAdmin,
    IsShipmentParticipantOrAdmin,
    IsShipmentDocumentParticipantOrAdmin,
    IsPODConfirmableByShipper,
    IsPaymentParticipantOrAdmin,
    IsDisputeResolvableByAdmin,
    IsAssignedDriverOrAdmin,
)
from apps.marketplace.serializers import (
    VehicleSerializer,
    TransporterVerificationActionSerializer,
    TransporterVerificationAuditSerializer,
    TransporterDetailSerializer,
    CargoLoadSerializer,
    BidSerializer,
    BidCreateSerializer,
    LocationUpdateSerializer,
    ShipmentMilestoneSerializer,
    ShipmentSerializer,
    AssignDriverSerializer,
    ShipmentStatusUpdateSerializer,
    ShipmentDocumentSerializer,
    ShipmentDocumentUploadSerializer,
    ProofOfDeliverySerializer,
    PODCreateSerializer,
    PODDisputeSerializer,
    FreightInvoiceSerializer,
    FreightSettlementSerializer,
    PaymentSerializer,
    PaymentInitiateSerializer,
    TransporterPayoutSerializer,
    PaymentDisputeSerializer,
    DisputeRaiseSerializer,
    DisputeResolveSerializer,
    OfflineSyncEventInputSerializer,
    OfflineSyncBatchInputSerializer,
    OfflineSyncEventResultSerializer,
    OfflineSyncBatchResponseSerializer,
    DriverIncidentReportSerializer,
    RatingSerializer,
    RouteSerializer,
    RouteWaypointSerializer,
    RouteRecalculationSerializer,
    RouteCreateInputSerializer,
    RouteRecalculateInputSerializer,
    LiveETAResponseSerializer,
    FuelAnalyticsResponseSerializer,
    RouteDeviationResponseSerializer,
    RouteAnalyticsResponseSerializer,
)
from apps.marketplace.predictive_services import (
    ETADelayPredictionService,
    ShipmentRiskPredictionService,
    RouteRiskPredictionService,
    FuelPredictionService,
    IncidentRiskPredictionService,
    OperationalRiskService,
)
from apps.marketplace.predictive_serializers import (
    ETAPredictionResponseSerializer,
    ShipmentRiskResponseSerializer,
    RouteRiskResponseSerializer,
    FuelPredictionResponseSerializer,
    IncidentRiskResponseSerializer,
    OperationalRiskResponseSerializer,
    PredictionHistorySerializer,
)
from apps.marketplace.models import (
    AutomationRule,
    AutomationRecommendation,
    AutomationExecution,
    OperationalEvent,
    Notification,
    NotificationPreference,
)
from apps.marketplace.automation_services import AutomationService
from apps.marketplace.automation_serializers import (
    AutomationRuleSerializer,
    AutomationRecommendationSerializer,
    AutomationRecommendationListSerializer,
    AutomationEvaluationResponseSerializer,
    AutomationReviewInputSerializer,
    AutomationExecutionSerializer,
)
from apps.marketplace.realtime_services import OperationalEventService, NotificationService
from apps.marketplace.realtime_serializers import (
    OperationalEventSerializer,
    NotificationSerializer,
    NotificationPreferenceSerializer,
    UnreadCountSerializer,
)




# ============================================================================
# PHASE 4: TRANSPORTER & FLEET VIEWS
# ============================================================================

class TransporterListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransporterDetailSerializer
    queryset = TransporterProfile.objects.all()


class TransporterMeProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransporterDetailSerializer

    def get_object(self):
        user = self.request.user
        if not hasattr(user, 'transporter_profile'):
            raise NotFound("Transporter profile not found for this user.")
        return user.transporter_profile


class TransporterVehicleListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = VehicleSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Vehicle.objects.all()
        if hasattr(user, 'transporter_profile'):
            return Vehicle.objects.filter(transporter=user.transporter_profile)
        return Vehicle.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        if not hasattr(user, 'transporter_profile'):
            raise PermissionDenied("Only registered Transporters can add fleet vehicles.")

        FleetService.add_vehicle(
            transporter=user.transporter_profile,
            vehicle_data=serializer.validated_data
        )


class TransporterVehicleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsVehicleOwnerOrAdmin]
    serializer_class = VehicleSerializer
    queryset = Vehicle.objects.all()


class TransporterVerificationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=TransporterVerificationActionSerializer,
        responses={200: TransporterDetailSerializer}
    )
    def post(self, request, pk):
        if not (request.user.is_superuser or request.user.role == Role.ADMIN or request.user.is_staff):
            raise PermissionDenied("Only administrators can update transporter verification status.")

        transporter = get_object_or_404(TransporterProfile, pk=pk)
        serializer = TransporterVerificationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        status_val = serializer.validated_data['status']
        reason = serializer.validated_data.get('reason', '')

        if status_val == VerificationStatus.VERIFIED:
            VerificationService.verify_transporter(transporter, request.user, reason)
        elif status_val == VerificationStatus.SUSPENDED:
            VerificationService.suspend_transporter(transporter, request.user, reason)

        return Response(
            TransporterDetailSerializer(transporter).data,
            status=status.HTTP_200_OK
        )


class TransporterVerificationAuditListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransporterVerificationAuditSerializer

    def get_queryset(self):
        pk = self.kwargs['pk']
        transporter = get_object_or_404(TransporterProfile, pk=pk)
        user = self.request.user

        if user.is_superuser or user.role == Role.ADMIN or (hasattr(user, 'transporter_profile') and user.transporter_profile == transporter):
            return transporter.verification_audits.all()

        raise PermissionDenied("You do not have permission to view this verification audit log.")


# ============================================================================
# PHASE 5: LOAD & BIDDING VIEWS
# ============================================================================

class LoadListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CargoLoadSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            qs = CargoLoad.objects.all()
        elif hasattr(user, 'shipper_profile'):
            qs = CargoLoad.objects.filter(shipper=user.shipper_profile)
        else:
            qs = CargoLoad.objects.filter(status=LoadStatus.POSTED)

        origin = self.request.query_params.get('origin')
        destination = self.request.query_params.get('destination')
        required_vehicle_type = self.request.query_params.get('required_vehicle_type')

        if origin:
            qs = qs.filter(origin__icontains=origin)
        if destination:
            qs = qs.filter(destination__icontains=destination)
        if required_vehicle_type:
            qs = qs.filter(required_vehicle_type=required_vehicle_type)

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        if not hasattr(user, 'shipper_profile') and not (user.is_superuser or user.role == Role.ADMIN):
            raise PermissionDenied("Only registered Shippers can post cargo loads.")

        shipper_profile = getattr(user, 'shipper_profile', None)
        if not shipper_profile and (user.is_superuser or user.role == Role.ADMIN):
            from apps.accounts.models import ShipperProfile
            shipper_profile, _ = ShipperProfile.objects.get_or_create(
                user=user,
                defaults={'company_name': 'Admin Freight Service'}
            )

        load = LoadService.create_load(
            shipper_profile=shipper_profile,
            load_data=serializer.validated_data
        )
        serializer.instance = load


class LoadDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CargoLoadSerializer
    queryset = CargoLoad.objects.all()

    def perform_destroy(self, instance):
        LoadService.cancel_load(instance, self.request.user)


class LoadCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: CargoLoadSerializer})
    def post(self, request, pk):
        load = get_object_or_404(CargoLoad, pk=pk)
        cancelled = LoadService.cancel_load(load, request.user)
        return Response(CargoLoadSerializer(cancelled).data, status=status.HTTP_200_OK)


class LoadBidsListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BidCreateSerializer
        return BidSerializer

    def get_queryset(self):
        load_id = self.kwargs['pk']
        load = get_object_or_404(CargoLoad, pk=load_id)
        user = self.request.user

        if user.is_superuser or user.role == Role.ADMIN:
            return load.bids.all()

        if hasattr(user, 'shipper_profile') and load.shipper == user.shipper_profile:
            return load.bids.all()

        if hasattr(user, 'transporter_profile'):
            return load.bids.filter(transporter=user.transporter_profile)

        return Bid.objects.none()

    @extend_schema(
        request=BidCreateSerializer,
        responses={201: BidSerializer}
    )
    def create(self, request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'transporter_profile'):
            raise PermissionDenied("Only registered Transporters can submit bids.")

        if not IsTransporterVerified().has_permission(request, self):
            raise PermissionDenied(IsTransporterVerified.message)

        load_id = self.kwargs['pk']
        load = get_object_or_404(CargoLoad, pk=load_id)

        serializer = BidCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bid = BiddingService.submit_bid(
            transporter_user=user,
            load=load,
            bid_data=serializer.validated_data
        )

        return Response(
            BidSerializer(bid).data,
            status=status.HTTP_201_CREATED
        )


class BidAcceptView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: CargoLoadSerializer})
    def post(self, request, pk):
        bid = get_object_or_404(Bid, pk=pk)
        load = BiddingService.accept_bid(
            shipper_user=request.user,
            bid=bid
        )
        return Response(
            CargoLoadSerializer(load).data,
            status=status.HTTP_200_OK
        )


class BidWithdrawView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: BidSerializer})
    def post(self, request, pk):
        bid = get_object_or_404(Bid, pk=pk)
        bid = BiddingService.withdraw_bid(
            transporter_user=request.user,
            bid=bid
        )
        return Response(
            BidSerializer(bid).data,
            status=status.HTTP_200_OK
        )


class TransporterMyBidsView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BidSerializer

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'transporter_profile'):
            return Bid.objects.filter(transporter=user.transporter_profile)
        return Bid.objects.none()


# ============================================================================
# PHASE 6: SHIPMENT EXECUTION & TRACKING VIEWS
# ============================================================================

class ShipmentListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ShipmentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Shipment.objects.all()

        if hasattr(user, 'shipper_profile'):
            return Shipment.objects.filter(load__shipper=user.shipper_profile)

        if hasattr(user, 'transporter_profile'):
            return Shipment.objects.filter(transporter=user.transporter_profile)

        if hasattr(user, 'driver_profile'):
            return Shipment.objects.filter(driver=user.driver_profile)

        return Shipment.objects.none()


class ShipmentDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = ShipmentSerializer
    queryset = Shipment.objects.all()


class ShipmentAssignDriverView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=AssignDriverSerializer,
        responses={200: ShipmentSerializer}
    )
    def post(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        serializer = AssignDriverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver_id = serializer.validated_data['driver_id']
        driver = get_object_or_404(DriverProfile, pk=driver_id)

        if driver.transporter != shipment.transporter:
            raise ValidationError({'driver_id': 'The specified driver does not belong to your fleet.'})

        updated_shipment = TrackingService.assign_driver(
            shipment=shipment,
            driver=driver,
            user=request.user
        )
        return Response(
            ShipmentSerializer(updated_shipment).data,
            status=status.HTTP_200_OK
        )


class ShipmentStatusUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(
        request=ShipmentStatusUpdateSerializer,
        responses={200: ShipmentSerializer}
    )
    def post(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        serializer = ShipmentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']
        location_name = serializer.validated_data.get('location_name', '')
        notes = serializer.validated_data.get('notes', '')

        updated_shipment = TrackingService.update_status(
            shipment=shipment,
            new_status=new_status,
            user=request.user,
            location_name=location_name,
            notes=notes
        )
        return Response(
            ShipmentSerializer(updated_shipment).data,
            status=status.HTTP_200_OK
        )


class ShipmentLocationView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(
        request=LocationUpdateSerializer,
        responses={201: LocationUpdateSerializer}
    )
    def post(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        serializer = LocationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        location_update = TrackingService.record_location(
            shipment=shipment,
            latitude=serializer.validated_data['latitude'],
            longitude=serializer.validated_data['longitude'],
            speed_kmh=serializer.validated_data.get('speed_kmh'),
            heading_degrees=serializer.validated_data.get('heading_degrees'),
            location_name=serializer.validated_data.get('location_name', ''),
            user=request.user
        )
        return Response(
            LocationUpdateSerializer(location_update).data,
            status=status.HTTP_201_CREATED
        )

    def get(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        latest = shipment.location_updates.first()
        if not latest:
            raise NotFound("No location updates found for this shipment.")

        return Response(LocationUpdateSerializer(latest).data, status=status.HTTP_200_OK)


class ShipmentTrackingHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: ShipmentSerializer})
    def get(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        data = ShipmentSerializer(shipment).data
        data['location_updates'] = LocationUpdateSerializer(shipment.location_updates.all(), many=True).data
        return Response(data, status=status.HTTP_200_OK)


class ShipmentETAView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: ShipmentSerializer})
    def get(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)
        return Response(ShipmentSerializer(ETAService.recalculate(shipment)).data)


# ============================================================================
# PHASE 7: DOCUMENT MANAGEMENT & DIGITAL PROOF OF DELIVERY (e-POD) VIEWS
# ============================================================================

class ShipmentDocumentListUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentDocumentParticipantOrAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(responses={200: ShipmentDocumentSerializer(many=True)})
    def get(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)
        documents = shipment.documents.all()
        return Response(ShipmentDocumentSerializer(documents, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=ShipmentDocumentUploadSerializer,
        responses={201: ShipmentDocumentSerializer}
    )
    def post(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        serializer = ShipmentDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document = DocumentService.upload_document(
            shipment=shipment,
            file_obj=serializer.validated_data['file'],
            document_type=serializer.validated_data['document_type'],
            user=request.user,
            notes=serializer.validated_data.get('notes', '')
        )
        return Response(ShipmentDocumentSerializer(document).data, status=status.HTTP_201_CREATED)


class DocumentDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentDocumentParticipantOrAdmin]
    serializer_class = ShipmentDocumentSerializer
    queryset = ShipmentDocument.objects.all()

    def perform_destroy(self, instance):
        DocumentService.delete_document(instance, self.request.user)


class DocumentDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentDocumentParticipantOrAdmin]

    def get(self, request, pk):
        document = get_object_or_404(ShipmentDocument, pk=pk)
        self.check_object_permissions(request, document)

        if not document.file:
            raise Http404("Document file not found.")

        response = FileResponse(document.file.open('rb'), content_type=document.mime_type)
        response['Content-Disposition'] = f'attachment; filename="{document.file_name}"'
        return response


class ShipmentPODView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: ProofOfDeliverySerializer})
    def get(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        if not hasattr(shipment, 'pod'):
            raise NotFound("Proof of Delivery has not yet been submitted for this shipment.")

        return Response(ProofOfDeliverySerializer(shipment.pod).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=PODCreateSerializer,
        responses={201: ProofOfDeliverySerializer}
    )
    def post(self, request, pk):
        shipment = get_object_or_404(Shipment, pk=pk)
        self.check_object_permissions(request, shipment)

        serializer = PODCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pod = PODService.create_pod(
            shipment=shipment,
            driver_user=request.user,
            pod_data=serializer.validated_data
        )
        return Response(ProofOfDeliverySerializer(pod).data, status=status.HTTP_201_CREATED)


class PODConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsPODConfirmableByShipper]

    @extend_schema(responses={200: ProofOfDeliverySerializer})
    def post(self, request, pk):
        pod = get_object_or_404(ProofOfDelivery, pk=pk)
        self.check_object_permissions(request, pod)

        confirmed_pod = PODService.confirm_pod(pod, request.user)
        return Response(ProofOfDeliverySerializer(confirmed_pod).data, status=status.HTTP_200_OK)


class PODDisputeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsPODConfirmableByShipper]

    @extend_schema(
        request=PODDisputeSerializer,
        responses={200: ProofOfDeliverySerializer}
    )
    def post(self, request, pk):
        pod = get_object_or_404(ProofOfDelivery, pk=pk)
        self.check_object_permissions(request, pod)

        serializer = PODDisputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        disputed_pod = PODService.dispute_pod(
            pod=pod,
            shipper_user=request.user,
            dispute_reason=serializer.validated_data['dispute_reason']
        )
        return Response(ProofOfDeliverySerializer(disputed_pod).data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 8: PAYMENTS & FREIGHT SETTLEMENT VIEWS (FR-10)
# ============================================================================

class PaymentListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Payment.objects.all()
        return Payment.objects.filter(payer=user)


class PaymentDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated, IsPaymentParticipantOrAdmin]
    serializer_class = PaymentSerializer
    queryset = Payment.objects.all()


class PaymentInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=PaymentInitiateSerializer,
        responses={201: PaymentSerializer}
    )
    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        settlement_id = serializer.validated_data['settlement_id']
        idempotency_key = serializer.validated_data['idempotency_key']
        provider_name = serializer.validated_data.get('provider_name', 'MOCK')

        settlement = get_object_or_404(FreightSettlement, pk=settlement_id)
        if not (request.user.is_superuser or request.user.role == Role.ADMIN or (hasattr(request.user, 'shipper_profile') and settlement.shipment.load.shipper == request.user.shipper_profile)):
            raise PermissionDenied("Only the load-owning shipper or an administrator can initiate payment.")

        payment = PaymentService.initiate_payment(
            settlement=settlement,
            payer_user=request.user,
            idempotency_key=idempotency_key,
            provider_name=provider_name
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class PaymentVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: PaymentSerializer})
    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        verified = PaymentService.verify_and_confirm_payment(payment, request.user)
        return Response(PaymentSerializer(verified).data, status=status.HTTP_200_OK)


class PaymentReconcileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        result = ReconciliationService.reconcile_payment(payment)
        return Response(result, status=status.HTTP_200_OK)


class ShipmentPaymentsView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        shipment_id = self.kwargs['pk']
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(self.request, shipment)
        return shipment.payments.all()


class FreightInvoiceListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FreightInvoiceSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return FreightInvoice.objects.all()
        return FreightInvoice.objects.filter(payer=user)


class FreightInvoiceDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FreightInvoiceSerializer
    queryset = FreightInvoice.objects.all()


class FreightSettlementCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={201: FreightSettlementSerializer})
    def post(self, request):
        shipment_id = request.data.get('shipment_id')
        if not shipment_id:
            raise ValidationError({'shipment_id': 'shipment_id is required.'})

        shipment = get_object_or_404(Shipment, pk=shipment_id)
        settlement = SettlementService.create_settlement_for_shipment(shipment)
        return Response(FreightSettlementSerializer(settlement).data, status=status.HTTP_201_CREATED)


class FreightSettlementListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FreightSettlementSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return FreightSettlement.objects.all()
        if hasattr(user, 'shipper_profile'):
            return FreightSettlement.objects.filter(shipment__load__shipper=user.shipper_profile)
        if hasattr(user, 'transporter_profile'):
            return FreightSettlement.objects.filter(shipment__transporter=user.transporter_profile)
        return FreightSettlement.objects.none()


class FreightSettlementDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated, IsPaymentParticipantOrAdmin]
    serializer_class = FreightSettlementSerializer
    queryset = FreightSettlement.objects.all()


class FreightSettlementDisputeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=DisputeRaiseSerializer,
        responses={201: PaymentDisputeSerializer}
    )
    def post(self, request, pk):
        settlement = get_object_or_404(FreightSettlement, pk=pk)
        serializer = DisputeRaiseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dispute = DisputeService.raise_dispute(
            settlement=settlement,
            user=request.user,
            reason=serializer.validated_data['reason']
        )
        return Response(PaymentDisputeSerializer(dispute).data, status=status.HTTP_201_CREATED)


class TransporterPayoutListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransporterPayoutSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return TransporterPayout.objects.all()
        if hasattr(user, 'transporter_profile'):
            return TransporterPayout.objects.filter(transporter=user.transporter_profile)
        return TransporterPayout.objects.none()


class TransporterPayoutDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TransporterPayoutSerializer
    queryset = TransporterPayout.objects.all()


class TransporterPayoutProcessView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: TransporterPayoutSerializer})
    def post(self, request, pk):
        if not (request.user.is_superuser or request.user.role == Role.ADMIN or request.user.is_staff):
            raise PermissionDenied("Only administrators can process transporter payouts.")

        payout = get_object_or_404(TransporterPayout, pk=pk)
        processed = PayoutService.process_payout(payout, request.user)
        return Response(TransporterPayoutSerializer(processed).data, status=status.HTTP_200_OK)


class RatingListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RatingSerializer
    queryset = Rating.objects.all()

    def perform_create(self, serializer):
        serializer.save(rater=self.request.user)


# ============================================================================
# PHASE 9: OFFLINE-FIRST SYNCHRONIZATION VIEWS (SRS 2.4, 4.1, 5.2)
# ============================================================================

class OfflineSyncBatchView(APIView):
    """
    POST: Synchronize a batch of offline events queued by mobile driver clients.
    Supports GPS_UPDATE, WAYPOINT_CHECKIN, and INCIDENT_REPORT event types with per-event
    idempotency and atomic isolation.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=OfflineSyncBatchInputSerializer,
        responses={200: OfflineSyncBatchResponseSerializer}
    )
    def post(self, request):
        serializer = OfflineSyncBatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        events_data = serializer.validated_data['events']
        device_id = serializer.validated_data.get('device_id', '')

        batch_result = OfflineSyncService.process_batch(
            user=request.user,
            events_data=events_data,
            device_id=device_id
        )

        return Response(
            batch_result,
            status=status.HTTP_200_OK
        )


class DriverIncidentReportListView(generics.ListAPIView):
    """
    GET: List driver incident reports logged for a corridor shipment.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = DriverIncidentReportSerializer

    def get_queryset(self):
        shipment_id = self.kwargs['shipment_id']
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(self.request, shipment)

        return shipment.incident_reports.all()


# ============================================================================
# PHASE 10: ROUTE OPTIMIZATION, ETA & FUEL ANALYTICS VIEWS
# ============================================================================

class ShipmentRouteCreateListAPIView(APIView):
    """
    GET: Retrieve active route and waypoints for a corridor shipment.
    POST: Plan a new route for a shipment with ordered waypoints.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: RouteSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        active_route = shipment.routes.filter(is_active=True).first()
        if not active_route:
            raise NotFound(f"No active route planned for shipment #{shipment_id}.")

        serializer = RouteSerializer(active_route)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=RouteCreateInputSerializer, responses={201: RouteSerializer})
    def post(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        serializer = RouteCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        route = RouteOptimizationService.create_route(
            shipment=shipment,
            waypoints_data=serializer.validated_data['waypoints'],
            origin=serializer.validated_data.get('origin', ''),
            destination=serializer.validated_data.get('destination', ''),
            average_speed_kmh=serializer.validated_data.get('average_speed_kmh')
        )

        return Response(RouteSerializer(route).data, status=status.HTTP_201_CREATED)


class ShipmentRouteRecalculateAPIView(APIView):
    """
    POST: Recalculate route for a shipment while preserving historical route audit records.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(request=RouteRecalculateInputSerializer, responses={200: RouteRecalculationSerializer})
    def post(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        serializer = RouteRecalculateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        incident = None
        incident_id = serializer.validated_data.get('incident_id')
        if incident_id:
            incident = get_object_or_404(DriverIncidentReport, pk=incident_id)

        recalc = RouteOptimizationService.recalculate_route(
            shipment=shipment,
            waypoints_data=serializer.validated_data.get('waypoints'),
            reason=serializer.validated_data.get('reason', 'Route recalculation requested'),
            incident=incident,
            triggered_by=request.user
        )

        return Response(RouteRecalculationSerializer(recalc).data, status=status.HTTP_200_OK)


class ShipmentRouteAnalyticsAPIView(APIView):
    """
    GET: Comprehensive route efficiency analytics comparing planned vs actual metrics.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: RouteAnalyticsResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        analytics_data = RouteOptimizationService.get_route_analytics(shipment)
        return Response(analytics_data, status=status.HTTP_200_OK)


class ShipmentETAAPIView(APIView):
    """
    GET: Live ETA calculation based on real-time GPS progress and active route.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: LiveETAResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        speed_param = request.query_params.get('average_speed_kmh')
        average_speed = float(speed_param) if speed_param else None

        eta_data = RouteOptimizationService.calculate_eta(shipment, average_speed_kmh=average_speed)
        return Response(eta_data, status=status.HTTP_200_OK)


class ShipmentFuelAnalyticsAPIView(APIView):
    """
    GET: Fuel consumption and cost analytics for planned vs actual distance.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: FuelAnalyticsResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        efficiency_param = request.query_params.get('fuel_efficiency')
        price_param = request.query_params.get('fuel_price')

        efficiency = float(efficiency_param) if efficiency_param else None
        price = float(price_param) if price_param else None

        fuel_data = RouteOptimizationService.calculate_fuel_analytics(
            shipment=shipment,
            fuel_efficiency_km_per_liter=efficiency,
            fuel_price_per_liter=price
        )
        return Response(fuel_data, status=status.HTTP_200_OK)


class ShipmentRouteDeviationAPIView(APIView):
    """
    GET: Check if latest GPS telemetry ping deviates from planned route waypoints.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: RouteDeviationResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        threshold_param = request.query_params.get('threshold_km')
        threshold = float(threshold_param) if threshold_param else None

        deviation_data = RouteOptimizationService.detect_route_deviation(
            shipment=shipment,
            threshold_km=threshold
        )
        return Response(deviation_data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 11: AI PREDICTIVE LOGISTICS & RISK INTELLIGENCE VIEWS
# ============================================================================

class ShipmentPredictiveDashboardAPIView(APIView):
    """
    GET: Consolidated predictive logistics & operational risk summary dashboard.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: OperationalRiskResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        dashboard_data = OperationalRiskService.get_composite_dashboard(shipment)
        return Response(dashboard_data, status=status.HTTP_200_OK)


class ShipmentETAPredictionAPIView(APIView):
    """
    GET: Predicted ETA delay, delay probability, risk score, and confidence.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: ETAPredictionResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        eta_prediction = ETADelayPredictionService.predict_eta_delay(shipment)
        return Response(eta_prediction, status=status.HTTP_200_OK)


class ShipmentRiskPredictionAPIView(APIView):
    """
    GET: Overall shipment delay-risk scoring with explainable contributing factors.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: ShipmentRiskResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        risk_prediction = ShipmentRiskPredictionService.predict_shipment_risk(shipment)
        return Response(risk_prediction, status=status.HTTP_200_OK)


class ShipmentRouteRiskPredictionAPIView(APIView):
    """
    GET: Route risk score and major corridor risk factors.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: RouteRiskResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        route_risk = RouteRiskPredictionService.predict_route_risk(shipment)
        return Response(route_risk, status=status.HTTP_200_OK)


class ShipmentFuelPredictionAPIView(APIView):
    """
    GET: Fuel consumption and cost predictions.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: FuelPredictionResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        eff = request.query_params.get('fuel_efficiency')
        price = request.query_params.get('fuel_price')

        efficiency = float(eff) if eff else None
        fuel_price = float(price) if price else None

        fuel_pred = FuelPredictionService.predict_fuel_consumption(
            shipment=shipment,
            fuel_efficiency=efficiency,
            fuel_price=fuel_price
        )
        return Response(fuel_pred, status=status.HTTP_200_OK)


class ShipmentIncidentRiskPredictionAPIView(APIView):
    """
    GET: Incident risk prediction based on driver history and route deviation.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: IncidentRiskResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        incident_risk = IncidentRiskPredictionService.predict_incident_risk(shipment)
        return Response(incident_risk, status=status.HTTP_200_OK)


class ShipmentPredictionHistoryAPIView(APIView):
    """
    GET: Paginated historical prediction records for auditability.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: PredictionHistorySerializer(many=True)})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        qs = shipment.predictions.select_related('prediction_model').order_by('-created_at')
        serializer = PredictionHistorySerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 12: DYNAMIC PRICING & FREIGHT MARKET INTELLIGENCE VIEWS
# ============================================================================

from apps.marketplace.models import PricingStrategy, PriceRecommendation, PricingMarketSnapshot
from apps.marketplace.pricing_services import DynamicPricingService
from apps.marketplace.pricing_serializers import (
    PricingStrategySerializer, PriceRecommendationSerializer, PricingRecommendationResponseSerializer,
    MarketIntelligenceResponseSerializer
)


class PriceRecommendationAPIView(APIView):
    """
    GET: Calculate and persist a decision-support dynamic freight price recommendation for a shipment.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='strategy_id', description='Optional specific pricing strategy ID to evaluate', required=False, type=int)
        ],
        responses={200: PricingRecommendationResponseSerializer}
    )
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        strategy = None
        strategy_id = request.query_params.get('strategy_id')
        if strategy_id:
            try:
                strategy = PricingStrategy.objects.get(pk=int(strategy_id), is_active=True)
            except (ValueError, PricingStrategy.DoesNotExist):
                raise ValidationError({"strategy_id": "Invalid or inactive pricing strategy ID specified."})

        recommendation = DynamicPricingService.generate_price_recommendation(shipment, strategy=strategy)
        return Response(recommendation, status=status.HTTP_200_OK)


class PriceRecommendationHistoryAPIView(APIView):
    """
    GET: Paginated historical price recommendations for auditability (-newest first).
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: PriceRecommendationSerializer(many=True)})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        qs = DynamicPricingService.get_pricing_history(shipment)
        serializer = PriceRecommendationSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MarketIntelligenceAPIView(APIView):
    """
    GET: Freight market intelligence and corridor demand/supply statistics.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(responses={200: MarketIntelligenceResponseSerializer})
    def get(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        intelligence = DynamicPricingService.get_market_intelligence(shipment)
        return Response(intelligence, status=status.HTTP_200_OK)


class PricingStrategyListAPIView(generics.ListAPIView):
    """
    GET: List active pricing strategies (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = PricingStrategySerializer
    queryset = PricingStrategy.objects.all().order_by('-is_active', 'name', 'version')


# ============================================================================
# PHASE 13: AUTOMATED WORKFLOW & SMART OPERATIONS VIEWS
# ============================================================================

class EvaluateShipmentAutomationAPIView(APIView):
    """
    POST: Evaluate shipment operational conditions and generate decision-support recommendations.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(request=None, responses={200: AutomationEvaluationResponseSerializer})
    def post(self, request, shipment_id):
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(request, shipment)

        result = AutomationService.evaluate_shipment(shipment)
        serializer = AutomationEvaluationResponseSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ShipmentAutomationListAPIView(generics.ListAPIView):
    """
    GET: List pending and active recommendations for a shipment.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = AutomationRecommendationSerializer

    def get_queryset(self):
        shipment_id = self.kwargs.get('shipment_id')
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(self.request, shipment)
        return AutomationRecommendation.objects.filter(shipment=shipment).select_related('rule', 'reviewed_by').order_by('-created_at')


class ShipmentAutomationHistoryAPIView(generics.ListAPIView):
    """
    GET: Paginated recommendation history for a shipment.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = AutomationRecommendationSerializer

    def get_queryset(self):
        shipment_id = self.kwargs.get('shipment_id')
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(self.request, shipment)
        return AutomationService.get_recommendation_history(shipment)


class AutomationRecommendationDetailAPIView(generics.RetrieveAPIView):
    """
    GET: Retrieve recommendation detail by ID.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AutomationRecommendationSerializer
    queryset = AutomationRecommendation.objects.all().select_related('shipment', 'rule', 'reviewed_by')

    def get_object(self):
        obj = super().get_object()
        if not AutomationService.check_user_authorization(obj.shipment, self.request.user):
            raise PermissionDenied("You are not authorized to view this recommendation.")
        return obj


class AutomationRecommendationApproveAPIView(APIView):
    """
    POST: Approve a pending recommendation (Participant / Admin authorization required).
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: AutomationRecommendationSerializer})
    def post(self, request, pk):
        recommendation = get_object_or_404(AutomationRecommendation, pk=pk)
        if not AutomationService.check_user_authorization(recommendation.shipment, request.user):
            raise PermissionDenied("You are not authorized to approve recommendations for this shipment.")

        updated_rec = AutomationService.approve_recommendation(pk, request.user)
        serializer = AutomationRecommendationSerializer(updated_rec)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AutomationRecommendationRejectAPIView(APIView):
    """
    POST: Reject a pending recommendation with optional reason.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=AutomationReviewInputSerializer, responses={200: AutomationRecommendationSerializer})
    def post(self, request, pk):
        recommendation = get_object_or_404(AutomationRecommendation, pk=pk)
        if not AutomationService.check_user_authorization(recommendation.shipment, request.user):
            raise PermissionDenied("You are not authorized to reject recommendations for this shipment.")

        reason = request.data.get('reason', '')
        updated_rec = AutomationService.reject_recommendation(pk, request.user, reason=reason)
        serializer = AutomationRecommendationSerializer(updated_rec)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AutomationRecommendationExecuteAPIView(APIView):
    """
    POST: Execute an approved recommendation.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: AutomationExecutionSerializer})
    def post(self, request, pk):

        recommendation = get_object_or_404(AutomationRecommendation, pk=pk)
        if not AutomationService.check_user_authorization(recommendation.shipment, request.user):
            raise PermissionDenied("You are not authorized to execute recommendations for this shipment.")

        execution = AutomationService.execute_recommendation(pk, request.user)
        serializer = AutomationExecutionSerializer(execution)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AutomationRuleListAPIView(generics.ListCreateAPIView):
    """
    GET/POST: List or create automation detection rules (Admin only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = AutomationRuleSerializer
    queryset = AutomationRule.objects.all().order_by('name')


# ============================================================================
# PHASE 14: REAL-TIME OPERATIONS, NOTIFICATIONS & EVENT INTELLIGENCE VIEWS
# ============================================================================

class NotificationListAPIView(generics.ListAPIView):
    """
    GET: List notifications for the authenticated user (paginated, -created_at).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related('event', 'shipment').order_by('-created_at')


class NotificationUnreadCountAPIView(APIView):
    """
    GET: Return unread and critical unread notification counts for authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: UnreadCountSerializer})
    def get(self, request):
        data = NotificationService.get_unread_count(request.user)
        serializer = UnreadCountSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationDetailAPIView(generics.RetrieveAPIView):
    """
    GET: Retrieve details of a specific notification.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        if self.request.user.role == Role.ADMIN:
            return Notification.objects.all().select_related('event', 'shipment')
        return Notification.objects.filter(recipient=self.request.user).select_related('event', 'shipment')


class NotificationReadAPIView(APIView):
    """
    POST: Mark a single notification as read.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: NotificationSerializer})
    def post(self, request, pk):
        notification = NotificationService.mark_as_read(pk, request.user)
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationReadAllAPIView(APIView):
    """
    POST: Mark all unread notifications for authenticated user as read.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Count of notifications marked read")})
    def post(self, request):
        count = NotificationService.mark_all_as_read(request.user)
        return Response({"marked_read_count": count}, status=status.HTTP_200_OK)


class NotificationAcknowledgeAPIView(APIView):
    """
    POST: Acknowledge a critical notification.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: NotificationSerializer})
    def post(self, request, pk):
        notification = NotificationService.acknowledge_notification(pk, request.user)
        serializer = NotificationSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ShipmentEventListAPIView(generics.ListAPIView):
    """
    GET: List operational events logged for a specific shipment (paginated).
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]
    serializer_class = OperationalEventSerializer

    def get_queryset(self):
        shipment_id = self.kwargs.get('shipment_id')
        shipment = get_object_or_404(Shipment, pk=shipment_id)
        self.check_object_permissions(self.request, shipment)
        return OperationalEventService.get_shipment_events(shipment, self.request.user)


class EventDetailAPIView(APIView):
    """
    GET: Retrieve details of a specific operational event.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: OperationalEventSerializer})
    def get(self, request, pk):
        event = OperationalEventService.get_event(pk, request.user)
        serializer = OperationalEventSerializer(event)
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationPreferenceAPIView(generics.RetrieveUpdateAPIView):
    """
    GET/PATCH: Retrieve or update authenticated user notification preferences.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    def get_object(self):
        pref, _ = NotificationPreference.objects.get_or_create(user=self.request.user)
        return pref


# ============================================================================
# PHASE 15: OPERATIONAL COMMAND CENTER & ALERT INTELLIGENCE (SRS 2.4, 4.1)
# ============================================================================

from apps.marketplace.command_center_services import OperationalCommandCenterService
from apps.marketplace.command_center_serializers import (
    OperationalDashboardSerializer, OperationalHealthSerializer, OperationalAttentionItemSerializer,
    OperationalAlertSerializer, OperationalTrendSerializer, OperationalRiskDistributionSerializer,
    OperationalIncidentSummarySerializer, OperationalTelemetrySummarySerializer,
    OperationalMarketSummarySerializer, OperationalAutomationSummarySerializer,
    ShipmentOperationalSummarySerializer
)


class OperationalDashboardAPIView(APIView):
    """
    GET: Retrieve real-time operational command center dashboard summary.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalDashboardSerializer

    @extend_schema(request=None, responses={200: OperationalDashboardSerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_realtime_summary(request.user)
        serializer = OperationalDashboardSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalHealthAPIView(APIView):
    """
    GET: Retrieve transparent, deterministic operational health score (0-100) and factor breakdown.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalHealthSerializer

    @extend_schema(request=None, responses={200: OperationalHealthSerializer})
    def get(self, request):
        data = OperationalCommandCenterService.calculate_operational_health_score(request.user)
        serializer = OperationalHealthSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalAttentionQueueAPIView(APIView):
    """
    GET: Retrieve ranked shipment attention queue requiring operational review.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalAttentionItemSerializer

    @extend_schema(request=None, responses={200: OperationalAttentionItemSerializer(many=True)})
    def get(self, request):
        data = OperationalCommandCenterService.get_shipments_requiring_attention(request.user)
        serializer = OperationalAttentionItemSerializer(data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalAlertIntelligenceAPIView(APIView):
    """
    GET: Retrieve aggregated operational alert intelligence and notification breakdowns.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalAlertSerializer

    @extend_schema(request=None, responses={200: OperationalAlertSerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_alert_intelligence(request.user)
        serializer = OperationalAlertSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalAlertTrendsAPIView(APIView):
    """
    GET: Retrieve time-bucketed operational alert trend analysis (1h, 6h, 24h, 7d, 30d).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalTrendSerializer

    @extend_schema(request=None, responses={200: OperationalTrendSerializer})
    def get(self, request):
        time_window = request.query_params.get('time_window', '24h')
        data = OperationalCommandCenterService.get_alert_trends(request.user, time_window=time_window)
        serializer = OperationalTrendSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalRiskDistributionAPIView(APIView):
    """
    GET: Retrieve operational risk distribution counts and percentages.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalRiskDistributionSerializer

    @extend_schema(request=None, responses={200: OperationalRiskDistributionSerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_risk_distribution(request.user)
        serializer = OperationalRiskDistributionSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalIncidentIntelligenceAPIView(APIView):
    """
    GET: Retrieve aggregated driver incident intelligence.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalIncidentSummarySerializer

    @extend_schema(request=None, responses={200: OperationalIncidentSummarySerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_incident_intelligence(request.user)
        serializer = OperationalIncidentSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalTelemetryIntelligenceAPIView(APIView):
    """
    GET: Retrieve route deviation and GPS telemetry intelligence.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalTelemetrySummarySerializer

    @extend_schema(request=None, responses={200: OperationalTelemetrySummarySerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_route_telemetry_intelligence(request.user)
        serializer = OperationalTelemetrySummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalMarketIntelligenceAPIView(APIView):
    """
    GET: Retrieve market pressure and dynamic pricing operational intelligence.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalMarketSummarySerializer

    @extend_schema(request=None, responses={200: OperationalMarketSummarySerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_market_pricing_intelligence(request.user)
        serializer = OperationalMarketSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class OperationalAutomationIntelligenceAPIView(APIView):
    """
    GET: Retrieve automation workflow recommendations and execution operational intelligence.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OperationalAutomationSummarySerializer

    @extend_schema(request=None, responses={200: OperationalAutomationSummarySerializer})
    def get(self, request):
        data = OperationalCommandCenterService.get_automation_workflow_intelligence(request.user)
        serializer = OperationalAutomationSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ShipmentOperationalSummaryAPIView(APIView):
    """
    GET: Retrieve unified operational summary for a specific shipment combining all Phase 9-14 intelligence.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ShipmentOperationalSummarySerializer

    @extend_schema(request=None, responses={200: ShipmentOperationalSummarySerializer})
    def get(self, request, shipment_id):
        data = OperationalCommandCenterService.get_unified_shipment_operational_summary(shipment_id, request.user)
        if not data:
            return Response({"detail": "Shipment not found or access denied."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ShipmentOperationalSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 16: PRODUCTION RELIABILITY, OBSERVABILITY & RESILIENCE VIEWS
# ============================================================================
from apps.marketplace.health_services import DependencyHealthService
from apps.marketplace.observability import OperationalMetricsService
from apps.marketplace.observability_serializers import (
    SystemHealthSerializer,
    SystemReadinessSerializer,
    SystemMetricsSerializer,
    SystemStatusSerializer,
)


class HealthCheckAPIView(APIView):
    """
    GET: Retrieve application process liveness status.
    Answers: Is the API application process alive and responding to requests?
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = SystemHealthSerializer

    @extend_schema(request=None, responses={200: SystemHealthSerializer})
    def get(self, request):
        data = DependencyHealthService.get_system_health()
        serializer = SystemHealthSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ReadinessCheckAPIView(APIView):
    """
    GET: Retrieve application dependency readiness status.
    Verifies PostgreSQL database and Redis availability.
    Returns 200 OK when ready, 503 Service Unavailable when degraded.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = SystemReadinessSerializer

    @extend_schema(request=None, responses={200: SystemReadinessSerializer, 503: SystemReadinessSerializer})
    def get(self, request):
        data, status_code = DependencyHealthService.get_system_readiness()
        serializer = SystemReadinessSerializer(data)
        return Response(serializer.data, status=status_code)


class SystemMetricsAPIView(APIView):
    """
    GET: Retrieve internal operational reliability metrics (Admin Only).
    Exposes request counts, error rates, dependency failure metrics, and WebSocket auth stats.
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SystemMetricsSerializer

    @extend_schema(request=None, responses={200: SystemMetricsSerializer})
    def get(self, request):
        data = OperationalMetricsService.get_metrics_summary()
        serializer = SystemMetricsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SystemStatusAPIView(APIView):
    """
    GET: Retrieve safe diagnostic system metadata (Admin Only).
    Returns environment and component architectural metadata without exposing secrets, credentials, or internal stack traces.
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SystemStatusSerializer

    @extend_schema(request=None, responses={200: SystemStatusSerializer})
    def get(self, request):
        data = {
            "application": "TradeFlow",
            "environment": "production",
            "database": "PostgreSQL",
            "cache": "Redis",
            "websocket": "Django Channels",
            "api_version": "v1"
        }
        serializer = SystemStatusSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 17: ANALYTICS, REPORTING & BUSINESS INTELLIGENCE VIEWS
# ============================================================================
from django.http import HttpResponse
from apps.marketplace.analytics_services import BusinessIntelligenceService
from apps.marketplace.analytics_serializers import (
    AnalyticsFilterSerializer,
    DashboardOverviewSerializer,
    ShipmentAnalyticsSerializer,
    DeliveryPerformanceSerializer,
    FinancialAnalyticsSerializer,
    MarketAnalyticsSerializer,
    RiskAnalyticsSerializer,
    IncidentAnalyticsSerializer,
    RouteAnalyticsSerializer,
    AutomationAnalyticsSerializer,
    EventAnalyticsSerializer,
    CorridorAnalyticsSerializer,
    TopPerformerSerializer,
    TrendAnalyticsSerializer,
    GenericReportSerializer,
)


class AnalyticsDashboardAPIView(APIView):
    """
    GET: Retrieve unified executive analytics dashboard overview.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DashboardOverviewSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: DashboardOverviewSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_dashboard_overview(request.user, filters)
        serializer = DashboardOverviewSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsShipmentsAPIView(APIView):
    """
    GET: Retrieve shipment lifecycle analytics and status distribution metrics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ShipmentAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: ShipmentAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_shipment_analytics(request.user, filters)
        serializer = ShipmentAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsDeliveryPerformanceAPIView(APIView):
    """
    GET: Retrieve delivery performance metrics comparing estimated vs actual delivery durations.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DeliveryPerformanceSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: DeliveryPerformanceSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_delivery_performance(request.user, filters)
        serializer = DeliveryPerformanceSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsFinancialAPIView(APIView):
    """
    GET: Retrieve financial analytics aggregating invoiced, settled, and paid freight values.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FinancialAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: FinancialAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_financial_analytics(request.user, filters)
        serializer = FinancialAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsMarketAPIView(APIView):
    """
    GET: Retrieve market pressure and price recommendation analytics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MarketAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: MarketAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_market_analytics(request.user, filters)
        serializer = MarketAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsRiskAPIView(APIView):
    """
    GET: Retrieve operational risk level distribution and risk trend analytics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RiskAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: RiskAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_risk_analytics(request.user, filters)
        serializer = RiskAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsIncidentAPIView(APIView):
    """
    GET: Retrieve driver incident report analytics and severity distribution.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = IncidentAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: IncidentAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_incident_analytics(request.user, filters)
        serializer = IncidentAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsRouteAPIView(APIView):
    """
    GET: Retrieve route optimization distance, deviation, and fuel analytics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RouteAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: RouteAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_route_analytics(request.user, filters)
        serializer = RouteAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsAutomationAPIView(APIView):
    """
    GET: Retrieve automation workflow recommendation rates and execution metrics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AutomationAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: AutomationAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_automation_analytics(request.user, filters)
        serializer = AutomationAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsEventAPIView(APIView):
    """
    GET: Retrieve operational event distribution and notification privacy analytics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: EventAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_operational_event_analytics(request.user, filters)
        serializer = EventAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsCorridorAPIView(APIView):
    """
    GET: Retrieve aggregated freight corridor performance analytics.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CorridorAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: CorridorAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_corridor_analytics(request.user, filters)
        serializer = CorridorAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsTopPerformersAPIView(APIView):
    """
    GET: Retrieve deterministic top transporter, driver, and corridor performance rankings.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TopPerformerSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: TopPerformerSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        data = BusinessIntelligenceService.get_top_performers(request.user, filters)
        serializer = TopPerformerSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsTrendsAPIView(APIView):
    """
    GET: Retrieve time-series trend analytics for specified metric (shipments, incidents, risk, revenue, automation, events).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TrendAnalyticsSerializer

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: TrendAnalyticsSerializer})
    def get(self, request):
        filters = request.query_params.dict()
        metric = filters.get('metric', 'shipments')
        period = filters.get('period', '30d')
        data = BusinessIntelligenceService.get_trend_analytics(request.user, metric, period, filters)
        serializer = TrendAnalyticsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AnalyticsReportsAPIView(APIView):
    """
    GET: Generate dynamic analytics report (executive, operational, financial, risk, market, automation).
    Supports format=json and format=csv exports.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GenericReportSerializer

    def perform_content_negotiation(self, request, force=False):
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)

    @extend_schema(parameters=[AnalyticsFilterSerializer], responses={200: GenericReportSerializer})
    def get(self, request, report_type):


        export_format = (request.GET.get('format') or request.query_params.get('format') or 'json').lower()
        report_data = BusinessIntelligenceService.get_report(request.user, report_type, request.query_params.dict())


        if export_format == 'csv':
            csv_content = BusinessIntelligenceService.render_csv_report(report_data, report_type)
            response = HttpResponse(csv_content, content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="tradeflow_report_{report_type}.csv"'
            return response

        serializer = GenericReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 18: EXTERNAL INTEGRATIONS, WEBHOOKS & ENTERPRISE DATA EXCHANGE VIEWS
# ============================================================================
from apps.marketplace.models import (
    ExternalIntegration,
    WebhookEndpoint,
    WebhookDelivery,
    InboundWebhookEvent,
)
from apps.marketplace.integration_services import IntegrationService
from apps.marketplace.integration_serializers import (
    ExternalIntegrationSerializer,
    ExternalIntegrationCreateSerializer,
    ExternalIntegrationUpdateSerializer,
    WebhookEndpointSerializer,
    WebhookEndpointCreateSerializer,
    WebhookDeliverySerializer,
    WebhookDeliveryDetailSerializer,
    InboundWebhookEventSerializer,
    IntegrationHealthSerializer,
    IntegrationEventPublishSerializer,
    WebhookRetrySerializer,
)



class ExternalIntegrationListCreateAPIView(APIView):
    """
    GET: List external integrations (Admin Only).
    POST: Create new external integration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ExternalIntegrationSerializer

    @extend_schema(request=None, responses={200: ExternalIntegrationSerializer(many=True)})
    def get(self, request):
        qs = ExternalIntegration.objects.all()
        serializer = ExternalIntegrationSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=ExternalIntegrationCreateSerializer, responses={201: ExternalIntegrationSerializer})
    def post(self, request):
        serializer = ExternalIntegrationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        integration = IntegrationService.create_integration(request.user, serializer.validated_data)
        res_serializer = ExternalIntegrationSerializer(integration)
        return Response(res_serializer.data, status=status.HTTP_201_CREATED)


class ExternalIntegrationDetailAPIView(APIView):
    """
    GET: Retrieve external integration details (Admin Only).
    PATCH: Update external integration parameters (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ExternalIntegrationSerializer

    @extend_schema(request=None, responses={200: ExternalIntegrationSerializer})
    def get(self, request, pk):
        integration = ExternalIntegration.objects.filter(id=pk).first()
        if not integration:
            return Response({"detail": "External integration not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ExternalIntegrationSerializer(integration)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=ExternalIntegrationUpdateSerializer, responses={200: ExternalIntegrationSerializer})
    def patch(self, request, pk):
        serializer = ExternalIntegrationUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        integration = IntegrationService.update_integration(pk, request.user, serializer.validated_data)
        res_serializer = ExternalIntegrationSerializer(integration)
        return Response(res_serializer.data, status=status.HTTP_200_OK)


class ExternalIntegrationActivateAPIView(APIView):
    """
    POST: Activate an external integration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ExternalIntegrationSerializer

    @extend_schema(request=None, responses={200: ExternalIntegrationSerializer})
    def post(self, request, pk):
        integration = IntegrationService.activate_integration(pk, request.user)
        serializer = ExternalIntegrationSerializer(integration)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExternalIntegrationDeactivateAPIView(APIView):
    """
    POST: Deactivate an external integration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ExternalIntegrationSerializer

    @extend_schema(request=None, responses={200: ExternalIntegrationSerializer})
    def post(self, request, pk):
        integration = IntegrationService.deactivate_integration(pk, request.user)
        serializer = ExternalIntegrationSerializer(integration)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ExternalIntegrationHealthAPIView(APIView):
    """
    GET: Retrieve integration delivery health, success rate, and endpoint status (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = IntegrationHealthSerializer

    @extend_schema(request=None, responses={200: IntegrationHealthSerializer})
    def get(self, request, pk):
        health_data = IntegrationService.get_integration_health(pk)
        serializer = IntegrationHealthSerializer(health_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookEndpointListCreateAPIView(APIView):
    """
    GET: List webhook endpoints for an integration (Admin Only).
    POST: Create a new webhook endpoint for an integration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(request=None, responses={200: WebhookEndpointSerializer(many=True)})
    def get(self, request, pk):
        qs = WebhookEndpoint.objects.filter(integration_id=pk)
        serializer = WebhookEndpointSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=WebhookEndpointCreateSerializer, responses={201: WebhookEndpointSerializer})
    def post(self, request, pk):
        data = request.data.copy()
        data['integration'] = pk
        serializer = WebhookEndpointCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        endpoint = IntegrationService.create_webhook_endpoint(pk, request.user, serializer.validated_data)
        res_serializer = WebhookEndpointSerializer(endpoint)
        return Response(res_serializer.data, status=status.HTTP_201_CREATED)


class WebhookEndpointDetailAPIView(APIView):
    """
    GET: Retrieve webhook endpoint details (Admin Only).
    PATCH: Update webhook endpoint parameters (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(request=None, responses={200: WebhookEndpointSerializer})
    def get(self, request, pk):
        endpoint = WebhookEndpoint.objects.filter(id=pk).first()
        if not endpoint:
            return Response({"detail": "Webhook endpoint not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WebhookEndpointSerializer(endpoint)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=WebhookEndpointSerializer, responses={200: WebhookEndpointSerializer})
    def patch(self, request, pk):
        endpoint = IntegrationService.update_webhook_endpoint(pk, request.user, request.data)
        serializer = WebhookEndpointSerializer(endpoint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookEndpointActivateAPIView(APIView):
    """
    POST: Activate a webhook endpoint (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(request=None, responses={200: WebhookEndpointSerializer})
    def post(self, request, pk):
        endpoint = IntegrationService.update_webhook_endpoint(pk, request.user, {'is_active': True})
        serializer = WebhookEndpointSerializer(endpoint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookEndpointDeactivateAPIView(APIView):
    """
    POST: Deactivate a webhook endpoint (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(request=None, responses={200: WebhookEndpointSerializer})
    def post(self, request, pk):
        endpoint = IntegrationService.update_webhook_endpoint(pk, request.user, {'is_active': False})
        serializer = WebhookEndpointSerializer(endpoint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookEndpointRotateSecretAPIView(APIView):
    """
    POST: Rotate HMAC signing secret for a webhook endpoint (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookEndpointSerializer

    @extend_schema(request=None, responses={200: WebhookEndpointSerializer})
    def post(self, request, pk):
        endpoint = IntegrationService.rotate_webhook_secret(pk, request.user)
        serializer = WebhookEndpointSerializer(endpoint)
        return Response(serializer.data, status=status.HTTP_200_OK)


class IntegrationDeliveriesListAPIView(APIView):
    """
    GET: Retrieve outbound webhook delivery attempts for an integration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookDeliverySerializer

    @extend_schema(request=None, responses={200: WebhookDeliverySerializer(many=True)})
    def get(self, request, pk):
        qs = WebhookDelivery.objects.filter(webhook_endpoint__integration_id=pk)
        serializer = WebhookDeliverySerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookEndpointDeliveriesListAPIView(APIView):
    """
    GET: Retrieve outbound webhook delivery attempts for an endpoint (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookDeliverySerializer

    @extend_schema(request=None, responses={200: WebhookDeliverySerializer(many=True)})
    def get(self, request, pk):
        qs = WebhookDelivery.objects.filter(webhook_endpoint_id=pk)
        serializer = WebhookDeliverySerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookDeliveryDetailAPIView(APIView):
    """
    GET: Retrieve detailed delivery attempt diagnostic context (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookDeliveryDetailSerializer

    @extend_schema(request=None, responses={200: WebhookDeliveryDetailSerializer})
    def get(self, request, pk):
        delivery = WebhookDelivery.objects.filter(id=pk).first()
        if not delivery:
            return Response({"detail": "Webhook delivery not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = WebhookDeliveryDetailSerializer(delivery)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WebhookDeliveryRetryAPIView(APIView):
    """
    POST: Manually trigger retry delivery execution for a failed or retrying webhook delivery (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = WebhookDeliveryDetailSerializer

    @extend_schema(request=None, responses={200: WebhookDeliveryDetailSerializer})
    def post(self, request, pk):
        delivery = IntegrationService.retry_delivery(pk, request.user)
        serializer = WebhookDeliveryDetailSerializer(delivery)
        return Response(serializer.data, status=status.HTTP_200_OK)


class IntegrationEventPublishAPIView(APIView):
    """
    POST: Publish an operational event to external webhook subscribers (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = IntegrationEventPublishSerializer

    @extend_schema(request=IntegrationEventPublishSerializer, responses={200: WebhookDeliverySerializer(many=True)})
    def post(self, request):
        serializer = IntegrationEventPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        evt_type = serializer.validated_data['event_type']
        shp_id = serializer.validated_data.get('shipment_id')
        data = serializer.validated_data.get('data', {})

        deliveries = IntegrationService.publish_event(
            event_type=evt_type,
            shipment_id=shp_id,
            data=data,
            request_id=getattr(request, 'request_id', None)
        )

        # Process deliveries
        processed = []
        for d in deliveries:
            res_d = IntegrationService.process_delivery(d.id)
            processed.append(res_d)

        res_serializer = WebhookDeliverySerializer(processed, many=True)
        return Response(res_serializer.data, status=status.HTTP_200_OK)


class InboundWebhookReceiverAPIView(APIView):
    """
    POST: Receive and authenticate inbound webhooks from external enterprise systems via HMAC SHA-256 signatures.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = InboundWebhookEventSerializer

    @extend_schema(request=None, responses={200: InboundWebhookEventSerializer, 400: None, 401: None})
    def post(self, request, integration_id):
        raw_body = request.body.decode('utf-8', errors='ignore')
        sig = request.headers.get('X-TradeFlow-Signature') or request.headers.get('X-Signature') or ''

        headers = dict(request.headers)
        evt = IntegrationService.process_inbound_webhook(integration_id, raw_body, sig, headers)

        if not evt.signature_valid:
            return Response(
                {"detail": "Invalid HMAC signature or malformed body payload.", "event_id": evt.id},
                status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = InboundWebhookEventSerializer(evt)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================================================
# PHASE 19: ADVANCED SECURITY, COMPLIANCE & GOVERNANCE VIEWS
# ============================================================================
from apps.marketplace.security_services import SecurityGovernanceService
from apps.marketplace.security_serializers import (
    SecurityAuditEventSerializer,
    SecurityIncidentSerializer,
    SecurityIncidentUpdateSerializer,
    SecurityPolicySerializer,
    SecurityPolicyCreateSerializer,
    SecurityOverviewSerializer,
    AuditIntegritySerializer,
    ComplianceReportSerializer,
    UserSecurityHistorySerializer,
)
from django.utils import timezone
from django.db.models import Q
from django.contrib.auth import get_user_model
from apps.marketplace.models import SecurityAuditEvent, SecurityIncident, SecurityPolicy, SecurityIncidentStatus, SecurityAuditEventType

User = get_user_model()




class SecurityOverviewAPIView(APIView):
    """
    GET: Retrieve administrative security overview metrics, incident tallies, and audit integrity status (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityOverviewSerializer

    @extend_schema(request=None, responses={200: SecurityOverviewSerializer})
    def get(self, request):
        overview_data = SecurityGovernanceService.get_security_overview()
        serializer = SecurityOverviewSerializer(overview_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityAuditEventListAPIView(APIView):
    """
    GET: Query immutable security audit log events with filtering by type, severity, actor, and dates (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityAuditEventSerializer

    @extend_schema(request=None, responses={200: SecurityAuditEventSerializer(many=True)})
    def get(self, request):
        qs = SecurityAuditEvent.objects.all()

        evt_type = request.query_params.get('event_type')
        if evt_type:
            qs = qs.filter(event_type=evt_type)

        severity = request.query_params.get('severity')
        if severity:
            qs = qs.filter(severity=severity)

        actor_id = request.query_params.get('actor_id')
        if actor_id:
            qs = qs.filter(actor_id=actor_id)

        target_user_id = request.query_params.get('target_user_id')
        if target_user_id:
            qs = qs.filter(target_user_id=target_user_id)

        req_id = request.query_params.get('request_id')
        if req_id:
            qs = qs.filter(request_id=req_id)

        serializer = SecurityAuditEventSerializer(qs[:200], many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityAuditEventDetailAPIView(APIView):
    """
    GET: Retrieve detailed context and cryptographic hash parameters for a specific audit log record (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityAuditEventSerializer

    @extend_schema(request=None, responses={200: SecurityAuditEventSerializer})
    def get(self, request, pk):
        evt = SecurityAuditEvent.objects.filter(id=pk).first()
        if not evt:
            return Response({"detail": "Security audit event not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SecurityAuditEventSerializer(evt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityIncidentListAPIView(APIView):
    """
    GET: List detected security incidents and threat investigations (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityIncidentSerializer

    @extend_schema(request=None, responses={200: SecurityIncidentSerializer(many=True)})
    def get(self, request):
        qs = SecurityIncident.objects.all()

        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        severity = request.query_params.get('severity')
        if severity:
            qs = qs.filter(severity=severity)

        serializer = SecurityIncidentSerializer(qs[:100], many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityIncidentDetailAPIView(APIView):
    """
    GET: Retrieve security incident details (Admin Only).
    PATCH: Update security incident fields and metadata (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityIncidentSerializer

    @extend_schema(request=None, responses={200: SecurityIncidentSerializer})
    def get(self, request, pk):
        inc = SecurityIncident.objects.filter(id=pk).first()
        if not inc:
            return Response({"detail": "Security incident not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SecurityIncidentSerializer(inc)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=SecurityIncidentUpdateSerializer, responses={200: SecurityIncidentSerializer})
    def patch(self, request, pk):
        inc = SecurityIncident.objects.filter(id=pk).first()
        if not inc:
            return Response({"detail": "Security incident not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = SecurityIncidentUpdateSerializer(inc, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION,
            action="UPDATE_SECURITY_INCIDENT",
            actor=request.user,
            target_model="SecurityIncident",
            target_object_id=str(inc.id),
            description=f"Updated security incident #{inc.id}",
            request=request
        )

        res_serializer = SecurityIncidentSerializer(inc)
        return Response(res_serializer.data, status=status.HTTP_200_OK)


class SecurityIncidentAssignAPIView(APIView):
    """
    POST: Assign a security incident to an administrative investigator (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityIncidentSerializer

    @extend_schema(request=None, responses={200: SecurityIncidentSerializer})
    def post(self, request, pk):
        inc = SecurityIncident.objects.filter(id=pk).first()
        if not inc:
            return Response({"detail": "Security incident not found."}, status=status.HTTP_404_NOT_FOUND)

        assignee_id = request.data.get('assigned_to_id') or request.user.id
        assignee = User.objects.filter(id=assignee_id).first()
        if not assignee:
            return Response({"detail": "Assignee user not found."}, status=status.HTTP_400_BAD_REQUEST)

        inc.assigned_to = assignee
        inc.status = SecurityIncidentStatus.INVESTIGATING
        inc.save()

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION,
            action="ASSIGN_SECURITY_INCIDENT",
            actor=request.user,
            target_user=assignee,
            target_model="SecurityIncident",
            target_object_id=str(inc.id),
            description=f"Assigned incident #{inc.id} to {assignee.email}",
            request=request
        )

        serializer = SecurityIncidentSerializer(inc)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityIncidentResolveAPIView(APIView):
    """
    POST: Mark a security incident as resolved with resolution audit notes (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityIncidentSerializer

    @extend_schema(request=None, responses={200: SecurityIncidentSerializer})
    def post(self, request, pk):
        inc = SecurityIncident.objects.filter(id=pk).first()
        if not inc:
            return Response({"detail": "Security incident not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get('resolution_notes', 'Resolved by administrator.')
        inc.status = SecurityIncidentStatus.RESOLVED
        inc.resolved_at = timezone.now()
        inc.resolution_notes = notes
        inc.save()

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION,
            action="RESOLVE_SECURITY_INCIDENT",
            actor=request.user,
            target_model="SecurityIncident",
            target_object_id=str(inc.id),
            description=f"Resolved incident #{inc.id}",
            request=request
        )

        serializer = SecurityIncidentSerializer(inc)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityIncidentDismissAPIView(APIView):
    """
    POST: Dismiss a security incident as false positive or non-actionable (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityIncidentSerializer

    @extend_schema(request=None, responses={200: SecurityIncidentSerializer})
    def post(self, request, pk):
        inc = SecurityIncident.objects.filter(id=pk).first()
        if not inc:
            return Response({"detail": "Security incident not found."}, status=status.HTTP_404_NOT_FOUND)

        notes = request.data.get('resolution_notes', 'Dismissed as false positive.')
        inc.status = SecurityIncidentStatus.DISMISSED
        inc.resolution_notes = notes
        inc.save()

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION,
            action="DISMISS_SECURITY_INCIDENT",
            actor=request.user,
            target_model="SecurityIncident",
            target_object_id=str(inc.id),
            description=f"Dismissed incident #{inc.id}",
            request=request
        )

        serializer = SecurityIncidentSerializer(inc)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserSecurityHistoryAPIView(APIView):
    """
    GET: Retrieve comprehensive security audit events for a specific user (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = UserSecurityHistorySerializer

    @extend_schema(request=None, responses={200: UserSecurityHistorySerializer})
    def get(self, request, pk):
        target_user = User.objects.filter(id=pk).first()
        if not target_user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        qs = SecurityAuditEvent.objects.filter(Q(actor=target_user) | Q(target_user=target_user))
        tot_events = qs.count()
        recent = list(qs[:50])

        recent_serialized = SecurityAuditEventSerializer(recent, many=True).data

        data = {
            "user_id": target_user.id,
            "user_email": target_user.email,
            "role": str(getattr(target_user, 'role', '')),
            "is_active": target_user.is_active,
            "total_audit_events": tot_events,
            "recent_events": recent_serialized
        }
        return Response(data, status=status.HTTP_200_OK)


class SecurityPolicyListCreateAPIView(APIView):
    """
    GET: List configured security policies (Admin Only).
    POST: Create a new security policy rule (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityPolicySerializer

    @extend_schema(request=None, responses={200: SecurityPolicySerializer(many=True)})
    def get(self, request):
        qs = SecurityPolicy.objects.all()
        serializer = SecurityPolicySerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(request=SecurityPolicyCreateSerializer, responses={201: SecurityPolicySerializer})
    def post(self, request):
        serializer = SecurityPolicyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save(created_by=request.user)

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.SECURITY_POLICY_VIOLATION,
            action="CREATE_SECURITY_POLICY",
            actor=request.user,
            target_model="SecurityPolicy",
            target_object_id=str(policy.id),
            description=f"Created security policy '{policy.name}'",
            request=request
        )

        res_serializer = SecurityPolicySerializer(policy)
        return Response(res_serializer.data, status=status.HTTP_201_CREATED)


class SecurityPolicyDetailAPIView(APIView):
    """
    PATCH: Update an existing security policy configuration (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = SecurityPolicySerializer

    @extend_schema(request=SecurityPolicySerializer, responses={200: SecurityPolicySerializer})
    def patch(self, request, pk):
        policy = SecurityPolicy.objects.filter(id=pk).first()
        if not policy:
            return Response({"detail": "Security policy not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = SecurityPolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)

        SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.ADMIN_ACTION,
            action="UPDATE_SECURITY_POLICY",
            actor=request.user,
            target_model="SecurityPolicy",
            target_object_id=str(policy.id),
            description=f"Updated security policy '{policy.name}'",
            request=request
        )

        return Response(serializer.data, status=status.HTTP_200_OK)


class AuditIntegrityCheckAPIView(APIView):
    """
    GET: Verify cryptographic SHA-256 hash chaining and audit record integrity across historical audit events (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = AuditIntegritySerializer

    @extend_schema(request=None, responses={200: AuditIntegritySerializer})
    def get(self, request):
        integrity_res = SecurityGovernanceService.verify_audit_chain()
        serializer = AuditIntegritySerializer(integrity_res)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SecurityComplianceReportAPIView(APIView):
    """
    GET: Generate enterprise compliance audit reports in JSON or CSV export format (Admin Only).
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    serializer_class = ComplianceReportSerializer

    def perform_content_negotiation(self, request, force=False):
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)

    @extend_schema(request=None, responses={200: ComplianceReportSerializer})
    def get(self, request, report_type):
        export_format = (request.GET.get('format') or request.query_params.get('format') or 'json').lower()
        filters = request.query_params.dict()

        report_data = SecurityGovernanceService.get_compliance_report(report_type, filters)

        if export_format == 'csv':
            csv_content = SecurityGovernanceService.render_csv_compliance_report(report_data, report_type)
            response = HttpResponse(csv_content, content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="tradeflow_compliance_report_{report_type}.csv"'
            return response

        serializer = ComplianceReportSerializer(report_data)
        return Response(serializer.data, status=status.HTTP_200_OK)











