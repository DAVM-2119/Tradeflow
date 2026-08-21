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
