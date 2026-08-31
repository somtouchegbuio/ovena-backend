from django.db import models
from .profile import BusinessAdmin
from .main import Business
from authflow.storage_backends import PrivateStorage
from payments.models.accounts import AbstractPayoutAccount

class BusinessOnboardStatus(models.Model):
    PHASE = [(i, day) for i, day in enumerate(
        ["notStarted","phase1", "phase2", "phase3"]
    )]
    admin = models.OneToOneField(BusinessAdmin, on_delete=models.CASCADE, related_name="cerd")
    onboarding_step = models.IntegerField(choices=PHASE, default=0)
    is_onboarding_complete = models.BooleanField(default=False)
    needs_manual_review = models.BooleanField(default=False)  # new
    checked = models.BooleanField(default=False) # for admins, make sure we remove this on new chnage;
    # STATUS_DRAFT = "draft"
    # STATUS_SUBMITTED = "submitted"
    # STATUS_APPROVED = "approved"
    # STATUS_REJECTED = "rejected"

    # STATUS_CHOICES = [
    #     (STATUS_DRAFT, "Draft"),
    #     (STATUS_SUBMITTED, "Submitted"),
    #     (STATUS_APPROVED, "Approved"),
    #     (STATUS_REJECTED, "Rejected"),
    # ]

    # status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)


class BusinessCerd(models.Model):
    BUSINESS_TYPE_CHOICES = [
        ("LLC", "Limited Liability Company"),
        ("C", "Corporations"),
        ("P", "Partnerships "),
        ("SP", "Sole Proprietorships"),
    ]

    class DocType(models.TextChoices):
        CAC = "cac", "CAC Document"
        TAX = "tax", "Tax Document"
        ID = "id", "ID Document"
        OTHER = "other", "Other"
    
    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="cerd")
    business_type = models.CharField(max_length=120, choices=BUSINESS_TYPE_CHOICES, default="restaurant")
    doc_type = models.CharField(max_length=20, choices=DocType.choices, default=DocType.OTHER)
    business_doc = models.FileField(
        upload_to="business/docs/",
        storage=PrivateStorage(),  # private bucket
        blank=True,
        null=True
    )

    # KYC / registration (optional at initial step)
    registered_business_name = models.CharField(max_length=255, null=True, blank=True) # well also remove to another model
    tax_identification_number = models.CharField(max_length=100, null=True, blank=True) # should be the last 4 bdigits for safety
    rc_number = models.CharField(max_length=100, null=True, blank=True)
    bn_number = models.CharField(max_length=100, blank=True, default="")

    def __str__(self):
        return self.registered_business_name


class BusinessPayoutAccount(AbstractPayoutAccount):
    """
    Payout account owned by a Business entity, not an individual user.
 
    Extends AbstractPayoutAccount so the withdrawal bridge can resolve
    a recipient code through the same interface as UserAccount.
 
    Extra fields over the base:
      - bank_name       : human-readable label for the bank
      - bvn             : last-4 only, personal verification of the signatory
      - bvn_verification_ref : external ref from BVN verification call
    """
 
    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="payout",
    )
 
    bank_name = models.CharField(max_length=120)
 
    # Store only the last 4 digits of the BVN for safety.
    bvn = models.CharField(max_length=4, null=True, blank=True)
    bvn_verification_ref = models.CharField(max_length=120, null=True, blank=True)
 
    class Meta:
        db_table = "accounts_businesspayoutaccount"  # keeps the existing table name
 
    def get_recipient_code(self) -> str:
        return self.paystack_recipient_code or ""
 
    def __str__(self) -> str:
        return f"{self.bank_account_name} — {self.business}"


class BusinessSubscription(models.Model):
    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="subscription"
    )

    banner_enabled = models.BooleanField(default=False)
    carousel_enabled = models.BooleanField(default=False)

    banner_info = models.JSONField(default=dict, blank=True, null=True,)
    carousel_image = models.ImageField(upload_to="business/carousel/", null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True)


class BusinessVerification(models.Model):
    TYPE_TIN = "tin"
    TYPE_RC = "rc"
    TYPE_BVN = "bvn"
    TYPE_CHOICES = [
        (TYPE_TIN, "TIN"),
        (TYPE_RC, "RC/CAC Number"),
        (TYPE_BVN, "BVN"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_SUCCESS, "Success"), (STATUS_FAILED, "Failed")]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="verifications")
    verification_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)

    provider_name = models.CharField(max_length=60, blank=True)
    provider_ref = models.CharField(max_length=120, blank=True)

    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "verification_type"], name="uniq_business_verification_type")
        ]
