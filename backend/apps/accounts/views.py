from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.accounts.models import User
from apps.accounts.serializers import (
    UserRegisterSerializer,
    UserSerializer,
    CustomTokenObtainPairSerializer,
)


class RegisterView(generics.CreateAPIView):
    """
    Public registration endpoint.
    Creates a new user record, validates email uniqueness and role rules,
    and initializes the corresponding profile.
    """
    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Register a new user",
        description="Registers a new Shipper, Transporter, Driver, Freight Forwarder, or Customs Staff account.",
        responses={
            201: OpenApiResponse(response=UserSerializer, description="User successfully registered."),
            400: OpenApiResponse(description="Validation error (e.g. duplicate email, invalid role, weak password).")
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        output_serializer = UserSerializer(user, context=self.get_serializer_context())
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    JWT Token Login endpoint.
    Accepts email and password, returning access and refresh JWT tokens.
    """
    serializer_class = CustomTokenObtainPairSerializer

    @extend_schema(
        summary="Obtain JWT token pair (Login)",
        description="Authenticates user credentials (email & password) and returns JWT access and refresh tokens."
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CustomTokenRefreshView(TokenRefreshView):
    """
    JWT Token Refresh endpoint.
    Accepts a valid refresh token and issues a new access token.
    """
    @extend_schema(
        summary="Refresh JWT access token",
        description="Provides a new access token when presented with a valid refresh token."
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class UserMeView(generics.RetrieveUpdateAPIView):
    """
    Protected endpoint to retrieve or update the authenticated user's profile.
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

    @extend_schema(
        summary="Get current user profile",
        description="Retrieves the details and linked domain profile of the currently authenticated user."
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Update current user profile",
        description="Updates personal profile fields (first_name, last_name, phone_number) for the current user."
    )
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)
