from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.accounts.models import Role, TransporterProfile, TransporterVerificationAudit, VerificationStatus, DriverProfile
from apps.accounts.permissions import IsShipper, IsTransporter, IsDriver, IsAdmin, IsOwnerOrAdmin
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
    Rating,
)
from apps.marketplace.serializers import (
    VehicleSerializer,
    TransporterDetailSerializer,
    TransporterVerificationActionSerializer,
    TransporterVerificationAuditSerializer,
    CargoLoadSerializer,
    BidSerializer,
    BidCreateSerializer,
    ShipmentSerializer,
    LocationUpdateSerializer,
    ShipmentMilestoneSerializer,
    AssignDriverSerializer,
    ShipmentStatusUpdateSerializer,
    RatingSerializer,
)
from apps.marketplace.services import VerificationService, FleetService, LoadService, BiddingService, TrackingService
from apps.marketplace.permissions import IsVehicleOwnerOrAdmin, IsTransporterVerified, IsLoadOwnerOrAdmin, IsBidOwnerOrAdmin, IsShipmentParticipantOrAdmin


class TransporterMeProfileView(generics.RetrieveUpdateAPIView):
    """
    Endpoint for authenticated Transporters to view and update their own company profile.
    Verification status cannot be self-modified.
    """
    serializer_class = TransporterDetailSerializer
    permission_classes = [permissions.IsAuthenticated, IsTransporter]

    def get_object(self):
        if not hasattr(self.request.user, 'transporter_profile'):
            raise NotFound("Transporter profile not found for this user.")
        return self.request.user.transporter_profile

    @extend_schema(summary="Get my transporter profile details and fleet")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update my transporter profile information")
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class TransporterListView(generics.ListAPIView):
    """
    List transporters on the platform.
    Administrators can see all transporters (including PENDING/SUSPENDED);
    Shippers and drivers see only VERIFIED transporters.
    """
    serializer_class = TransporterDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN or user.is_staff:
            return TransporterProfile.objects.all().select_related('user').prefetch_related('vehicles')
        return TransporterProfile.objects.filter(
            verification_status=VerificationStatus.VERIFIED
        ).select_related('user').prefetch_related('vehicles')

    @extend_schema(summary="List marketplace transporters")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TransporterVehicleListCreateView(generics.ListCreateAPIView):
    """
    Endpoint for a Transporter to list or add vehicles to their own fleet.
    """
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated, IsTransporter]

    def get_queryset(self):
        if not hasattr(self.request.user, 'transporter_profile'):
            return Vehicle.objects.none()
        return Vehicle.objects.filter(transporter=self.request.user.transporter_profile)

    @extend_schema(summary="List fleet vehicles for authenticated transporter")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Add a new vehicle to transporter fleet")
    def create(self, request, *args, **kwargs):
        if not hasattr(request.user, 'transporter_profile'):
            raise PermissionDenied("User does not have a transporter profile.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vehicle = FleetService.add_vehicle(
            transporter=request.user.transporter_profile,
            vehicle_data=serializer.validated_data
        )
        return Response(VehicleSerializer(vehicle).data, status=status.HTTP_201_CREATED)


class TransporterVehicleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Endpoint to retrieve, update, or remove a fleet vehicle.
    Access restricted to vehicle owner or Admin.
    """
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated, IsVehicleOwnerOrAdmin]

    @extend_schema(summary="Get fleet vehicle details")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update fleet vehicle details")
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(summary="Deactivate or remove fleet vehicle")
    def delete(self, request, *args, **kwargs):
        vehicle = self.get_object()
        vehicle.is_active = False
        vehicle.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class TransporterVerificationView(generics.GenericAPIView):
    """
    ADMIN-ONLY Endpoint to approve/verify or suspend a Transporter account with audit record.
    """
    serializer_class = TransporterVerificationActionSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    @extend_schema(
        summary="Admin Transporter Verification / Suspension Action",
        description="Transitions a Transporter's verification status to VERIFIED or SUSPENDED with audit record.",
        responses={200: TransporterDetailSerializer, 400: OpenApiResponse(description="Invalid status transition")}
    )
    def post(self, request, pk=None):
        try:
            transporter = TransporterProfile.objects.get(pk=pk)
        except TransporterProfile.DoesNotExist:
            raise NotFound("Transporter profile not found.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_status = serializer.validated_data['status']
        reason = serializer.validated_data.get('reason', '')

        if target_status == VerificationStatus.VERIFIED:
            transporter, audit = VerificationService.verify_transporter(transporter, request.user, reason)
        elif target_status == VerificationStatus.SUSPENDED:
            transporter, audit = VerificationService.suspend_transporter(transporter, request.user, reason)
        else:
            raise ValidationError("Invalid verification status transition.")

        return Response(TransporterDetailSerializer(transporter).data, status=status.HTTP_200_OK)


class TransporterVerificationAuditListView(generics.ListAPIView):
    """
    ADMIN-ONLY Endpoint to retrieve verification audit history for a Transporter.
    """
    serializer_class = TransporterVerificationAuditSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get_queryset(self):
        transporter_id = self.kwargs.get('pk')
        return TransporterVerificationAudit.objects.filter(transporter_id=transporter_id)

    @extend_schema(summary="Get verification audit history for transporter")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class LoadListCreateView(generics.ListCreateAPIView):
    """
    Endpoint for listing active spot market cargo loads or posting a new load (Shippers only).
    Supports query parameters: origin, destination, required_vehicle_type, status.
    """
    serializer_class = CargoLoadSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = CargoLoad.objects.all().select_related('shipper', 'assigned_transporter', 'assigned_vehicle')
        
        origin = self.request.query_params.get('origin')
        if origin:
            qs = qs.filter(origin__icontains=origin)
            
        destination = self.request.query_params.get('destination')
        if destination:
            qs = qs.filter(destination__icontains=destination)
            
        req_type = self.request.query_params.get('required_vehicle_type')
        if req_type:
            qs = qs.filter(required_vehicle_type=req_type)
            
        load_status = self.request.query_params.get('status')
        if load_status:
            qs = qs.filter(status=load_status)
        elif not (self.request.user.is_superuser or self.request.user.role == Role.ADMIN):
            qs = qs.filter(status__in=[LoadStatus.POSTED, LoadStatus.ASSIGNED])
            
        return qs

    @extend_schema(
        summary="List active spot market cargo loads",
        parameters=[
            OpenApiParameter('origin', str, description="Filter by origin location"),
            OpenApiParameter('destination', str, description="Filter by destination location"),
            OpenApiParameter('required_vehicle_type', str, description="Filter by vehicle type"),
            OpenApiParameter('status', str, description="Filter by status (POSTED, ASSIGNED, etc.)"),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Post a new cargo load (Shippers/Admins only)")
    def create(self, request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.role == Role.ADMIN or request.user.role == Role.SHIPPER):
            raise PermissionDenied("Only Shippers or Administrators can post cargo loads.")
            
        if not hasattr(request.user, 'shipper_profile') and not (request.user.is_superuser or request.user.role == Role.ADMIN):
            raise PermissionDenied("User does not have a Shipper profile.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        shipper_profile = getattr(request.user, 'shipper_profile', None)

        load = LoadService.create_load(
            shipper_profile=shipper_profile,
            load_data=serializer.validated_data
        )
        return Response(CargoLoadSerializer(load).data, status=status.HTTP_201_CREATED)


class LoadDetailView(generics.RetrieveUpdateAPIView):
    """
    Endpoint to view or update cargo load details.
    """
    queryset = CargoLoad.objects.all().select_related('shipper', 'assigned_transporter', 'assigned_vehicle')
    serializer_class = CargoLoadSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(summary="Get cargo load details")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update cargo load parameters")
    def patch(self, request, *args, **kwargs):
        load = self.get_object()
        if not (request.user.is_superuser or request.user.role == Role.ADMIN or load.shipper.user == request.user):
            raise PermissionDenied("Only the load owner shipper or an administrator can update this load.")
        return super().patch(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class LoadCancelView(generics.GenericAPIView):
    """
    Endpoint for a Shipper or Admin to cancel a posted cargo load.
    """
    permission_classes = [permissions.IsAuthenticated, IsLoadOwnerOrAdmin]
    serializer_class = CargoLoadSerializer

    @extend_schema(summary="Cancel a posted cargo load")
    def post(self, request, pk=None):
        try:
            load = CargoLoad.objects.get(pk=pk)
        except CargoLoad.DoesNotExist:
            raise NotFound("Cargo load not found.")

        load = LoadService.cancel_load(load, request.user)
        return Response(CargoLoadSerializer(load).data, status=status.HTTP_200_OK)


class LoadBidsListCreateView(generics.ListCreateAPIView):
    """
    GET: View bids submitted on a load.
    POST: Verified Transporter ONLY submits a competitive bid on the load.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BidCreateSerializer
        return BidSerializer

    def get_queryset(self):
        load_id = self.kwargs.get('pk')
        try:
            load = CargoLoad.objects.get(pk=load_id)
        except CargoLoad.DoesNotExist:
            return Bid.objects.none()

        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN or load.shipper.user == user:
            return Bid.objects.filter(load=load).select_related('transporter', 'proposed_vehicle')
        elif hasattr(user, 'transporter_profile'):
            return Bid.objects.filter(load=load, transporter=user.transporter_profile).select_related('transporter', 'proposed_vehicle')
        return Bid.objects.none()

    @extend_schema(summary="List bids submitted on a cargo load")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Submit a competitive spot market bid (VERIFIED Transporters Only)")
    def create(self, request, pk=None):
        try:
            load = CargoLoad.objects.get(pk=pk)
        except CargoLoad.DoesNotExist:
            raise NotFound("Cargo load not found.")

        if not VerificationService.can_accept_load(request.user):
            raise PermissionDenied("Unverified or suspended transporters are not permitted to submit bids on loads.")

        serializer = BidCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        bid = BiddingService.submit_bid(
            transporter_user=request.user,
            load=load,
            bid_data=serializer.validated_data
        )
        return Response(BidSerializer(bid).data, status=status.HTTP_201_CREATED)


class BidAcceptView(generics.GenericAPIView):
    """
    Endpoint for a Shipper to accept a winning bid on their posted load.
    Triggers atomic state transition and initializes Shipment execution record.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CargoLoadSerializer

    @extend_schema(summary="Accept a winning bid (Atomic transaction)")
    def post(self, request, pk=None):
        try:
            bid = Bid.objects.get(pk=pk)
        except Bid.DoesNotExist:
            raise NotFound("Bid not found.")

        updated_load = BiddingService.accept_bid(request.user, bid)
        return Response(CargoLoadSerializer(updated_load).data, status=status.HTTP_200_OK)


class BidWithdrawView(generics.GenericAPIView):
    """
    Endpoint for a Transporter to withdraw their submitted bid.
    """
    permission_classes = [permissions.IsAuthenticated, IsBidOwnerOrAdmin]
    serializer_class = BidSerializer

    @extend_schema(summary="Withdraw a submitted bid")
    def post(self, request, pk=None):
        try:
            bid = Bid.objects.get(pk=pk)
        except Bid.DoesNotExist:
            raise NotFound("Bid not found.")

        updated_bid = BiddingService.withdraw_bid(request.user, bid)
        return Response(BidSerializer(updated_bid).data, status=status.HTTP_200_OK)


class TransporterMyBidsView(generics.ListAPIView):
    """
    Endpoint for an authenticated Transporter to list all their submitted spot market bids.
    """
    serializer_class = BidSerializer
    permission_classes = [permissions.IsAuthenticated, IsTransporter]

    def get_queryset(self):
        if not hasattr(self.request.user, 'transporter_profile'):
            return Bid.objects.none()
        return Bid.objects.filter(transporter=self.request.user.transporter_profile).select_related('load', 'proposed_vehicle')

    @extend_schema(summary="List my submitted bids")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


# ============================================================================
# PHASE 6: SHIPMENT EXECUTION & REAL-TIME TRACKING VIEWS
# ============================================================================

class ShipmentListView(generics.ListAPIView):
    """
    Endpoint for listing active corridor shipments.
    Shippers see shipments for their loads; Transporters/Drivers see assigned shipments; Admins see all.
    """
    serializer_class = ShipmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Shipment.objects.all().select_related('load', 'transporter', 'vehicle', 'driver')
        
        if user.is_superuser or user.role == Role.ADMIN:
            return qs
        elif hasattr(user, 'shipper_profile'):
            return qs.filter(load__shipper=user.shipper_profile)
        elif hasattr(user, 'transporter_profile'):
            return qs.filter(transporter=user.transporter_profile)
        elif hasattr(user, 'driver_profile'):
            return qs.filter(driver=user.driver_profile)
            
        return Shipment.objects.none()

    @extend_schema(summary="List active corridor shipments")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ShipmentDetailView(generics.RetrieveAPIView):
    """
    Endpoint to view detailed shipment information, status milestones, and latest GPS location.
    """
    queryset = Shipment.objects.all().select_related('load', 'transporter', 'vehicle', 'driver')
    serializer_class = ShipmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(summary="Get shipment execution details and tracking info")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ShipmentAssignDriverView(generics.GenericAPIView):
    """
    Endpoint for Transporter or Admin to assign a Driver to a shipment.
    """
    serializer_class = AssignDriverSerializer
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(summary="Assign a driver to a shipment")
    def post(self, request, pk=None):
        try:
            shipment = Shipment.objects.get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFound("Shipment not found.")

        self.check_object_permissions(request, shipment)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver_id = serializer.validated_data['driver_id']
        try:
            driver = DriverProfile.objects.get(pk=driver_id)
        except DriverProfile.DoesNotExist:
            raise NotFound("Driver profile not found.")

        updated_shipment = TrackingService.assign_driver(shipment, driver, request.user)
        return Response(ShipmentSerializer(updated_shipment).data, status=status.HTTP_200_OK)


class ShipmentStatusUpdateView(generics.GenericAPIView):
    """
    Endpoint for Driver, Transporter, or Admin to update shipment status (e.g. AT_PICKUP, IN_TRANSIT, DELIVERED).
    """
    serializer_class = ShipmentStatusUpdateSerializer
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(summary="Update shipment execution status with milestone log")
    def post(self, request, pk=None):
        try:
            shipment = Shipment.objects.get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFound("Shipment not found.")

        self.check_object_permissions(request, shipment)

        serializer = self.get_serializer(data=request.data)
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
        return Response(ShipmentSerializer(updated_shipment).data, status=status.HTTP_200_OK)


class ShipmentLocationView(generics.GenericAPIView):
    """
    Endpoint for Driver, Transporter, or Admin to record real-time GPS telemetry location update.
    """
    serializer_class = LocationUpdateSerializer
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(summary="Submit GPS telemetry ping for shipment in transit")
    def post(self, request, pk=None):
        try:
            shipment = Shipment.objects.get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFound("Shipment not found.")

        self.check_object_permissions(request, shipment)

        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')

        if latitude is None or longitude is None:
            raise ValidationError({"latitude": "Latitude and longitude are required."})

        speed = request.data.get('speed_kmh')
        heading = request.data.get('heading_degrees')
        location_name = request.data.get('location_name', '')

        location_update = TrackingService.record_location(
            shipment=shipment,
            latitude=float(latitude),
            longitude=float(longitude),
            speed_kmh=float(speed) if speed is not None else None,
            heading_degrees=float(heading) if heading is not None else None,
            location_name=location_name,
            user=request.user
        )
        return Response(LocationUpdateSerializer(location_update).data, status=status.HTTP_201_CREATED)


class ShipmentTrackingHistoryView(generics.GenericAPIView):
    """
    Endpoint to retrieve complete GPS location history and milestone audit trail for a shipment.
    """
    permission_classes = [permissions.IsAuthenticated, IsShipmentParticipantOrAdmin]

    @extend_schema(summary="Get full GPS location tracking history and milestone trail")
    def get(self, request, pk=None):
        try:
            shipment = Shipment.objects.get(pk=pk)
        except Shipment.DoesNotExist:
            raise NotFound("Shipment not found.")

        self.check_object_permissions(request, shipment)

        location_updates = LocationUpdate.objects.filter(shipment=shipment)
        milestones = ShipmentMilestone.objects.filter(shipment=shipment)

        return Response({
            "tracking_number": shipment.tracking_number,
            "status": shipment.status,
            "origin": shipment.origin,
            "destination": shipment.destination,
            "milestones": ShipmentMilestoneSerializer(milestones, many=True).data,
            "location_updates": LocationUpdateSerializer(location_updates, many=True).data
        }, status=status.HTTP_200_OK)


class RatingListCreateView(generics.ListCreateAPIView):
    """
    Endpoint for submitting and listing marketplace ratings.
    """
    queryset = Rating.objects.all()
    serializer_class = RatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(summary="List marketplace ratings")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Submit a post-trip rating")
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(rater=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
