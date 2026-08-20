from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.accounts.managers import UserManager


class Role(models.TextChoices):
    SHIPPER = 'SHIPPER', 'Shipper'
    TRANSPORTER = 'TRANSPORTER', 'Transporter'
    DRIVER = 'DRIVER', 'Driver'
    FREIGHT_FORWARDER = 'FREIGHT_FORWARDER', 'Freight Forwarder'
    CUSTOMS_STAFF = 'CUSTOMS_STAFF', 'Customs Staff'
    ADMIN = 'ADMIN', 'Administrator'


class VerificationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    VERIFIED = 'VERIFIED', 'Verified'
    SUSPENDED = 'SUSPENDED', 'Suspended'


class User(AbstractUser):
    """
    Custom User model for TradeFlow platform.
    Uses email as the primary authentication field.
    """
    username = None
    email = models.EmailField('email address', unique=True, db_index=True)
    phone_number = models.CharField(max_length=30, blank=True, db_index=True)
    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.SHIPPER,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'role']),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"


class ShipperProfile(models.Model):
    """
    Profile entity for Shippers/Importers/Exporters.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='shipper_profile'
    )
    company_name = models.CharField(max_length=255)
    trade_license_number = models.CharField(max_length=100, unique=True, db_index=True)
    tax_id = models.CharField(max_length=100, unique=True, db_index=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shipper Profile'
        verbose_name_plural = 'Shipper Profiles'

    def __str__(self):
        return f"Shipper: {self.company_name} ({self.user.email})"


class TransporterProfile(models.Model):
    """
    Profile entity for Transporters/Fleet Owners.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='transporter_profile'
    )
    company_name = models.CharField(max_length=255)
    trade_license_number = models.CharField(max_length=100, unique=True, db_index=True)
    tax_id = models.CharField(max_length=100, unique=True, db_index=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Transporter Profile'
        verbose_name_plural = 'Transporter Profiles'
        indexes = [
            models.Index(fields=['verification_status']),
        ]

    def __str__(self):
        return f"Transporter: {self.company_name} [{self.verification_status}]"


class TransporterVerificationAudit(models.Model):
    """
    Audit log tracking verification status transitions for Transporters.
    """
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='verification_audits'
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='performed_verification_audits'
    )
    previous_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices
    )
    new_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transporter Verification Audit'
        verbose_name_plural = 'Transporter Verification Audits'
        ordering = ['-created_at']

    def __str__(self):
        return f"Audit for {self.transporter.company_name}: {self.previous_status} -> {self.new_status}"


class DriverProfile(models.Model):
    """
    Profile entity for Drivers assigned to Transporters.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='driver_profile'
    )
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drivers'
    )
    license_number = models.CharField(max_length=100, unique=True, db_index=True)
    license_expiration = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Driver Profile'
        verbose_name_plural = 'Driver Profiles'

    def __str__(self):
        return f"Driver: {self.user.get_full_name()} ({self.license_number})"


class FreightForwarderProfile(models.Model):
    """
    Profile entity for Freight Forwarders managing cargo and documentation.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='forwarder_profile'
    )
    company_name = models.CharField(max_length=255)
    license_number = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Freight Forwarder Profile'
        verbose_name_plural = 'Freight Forwarder Profiles'

    def __str__(self):
        return f"Forwarder: {self.company_name}"


class CustomsStaffProfile(models.Model):
    """
    Profile entity for Customs Authority Staff.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='customs_profile'
    )
    badge_number = models.CharField(max_length=100, unique=True, db_index=True)
    station_location = models.CharField(max_length=255, default='Modjo Dry Port')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Customs Staff Profile'
        verbose_name_plural = 'Customs Staff Profiles'

    def __str__(self):
        return f"Customs Officer: {self.user.get_full_name()} ({self.badge_number})"
