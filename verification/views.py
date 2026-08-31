"""
Note: `PlateNumberVerificationView` is left as a pass-through (calls the
service layer, returns the result) but does NOT persist to a
DriverVerification row, because "plate number" wasn't in the driver
checklist (bvn / nin / face match / bank account) and DriverVerification
doesn't have a plate type yet. Add TYPE_PLATE to the model if you want it
tracked the same way as the others.
"""
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status

from .serializers import (
    NINVerificationSerializer,
    BVNVerificationSerializer,
    BVNValidationSerializer,
    AccountNumberSerializer,
    FaceMatchSerializer,
    PlateNumberSerializer,
    TINVerificationSerializer,
    RCNumberSerializer,
    BusinessBVNSerializer,
)
from . import service

from accounts.models import (
    DriverVerification,
    BusinessVerification,
    BusinessOnboardStatus,
    # BusinessAdmin
)
from driver_api.views import BaseDriverAPIView
from business_api.views import BaseBuisAdminAPIView

# ──────────────────────────────────────────────
# PERSISTENCE HELPERS
# ──────────────────────────────────────────────

def _record_driver_verification(driver, verification_type, result, request_payload=None):
    DriverVerification.objects.update_or_create(
        driver=driver,
        verification_type=verification_type,
        defaults={
            "status": DriverVerification.STATUS_SUCCESS if result["success"] else DriverVerification.STATUS_FAILED,
            "provider_name": result.get("provider") or "",
            "provider_ref": _extract_ref(result.get("data")),
            "request_payload": request_payload or {},
            "response_payload": result.get("data") or {"attempts": result.get("attempts", [])},
            "completed_at": timezone.now(),
        },
    )


def _record_business_verification(business, verification_type, result, request_payload=None):
    BusinessVerification.objects.update_or_create(
        business=business,
        verification_type=verification_type,
        defaults={
            "status": BusinessVerification.STATUS_SUCCESS if result["success"] else BusinessVerification.STATUS_FAILED,
            "provider_name": result.get("provider") or "",
            "provider_ref": _extract_ref(result.get("data")),
            "request_payload": request_payload or {},
            "response_payload": result.get("data") or {"attempts": result.get("attempts", [])},
            "completed_at": timezone.now(),
        },
    )


def _extract_ref(data):
    if not isinstance(data, dict):
        return ""
    for key in ("reference", "tracking_id", "entity_id", "id"):
        if data.get(key):
            return str(data[key])
    return ""


def _verification_response(result):
    """
    Always 200 - a failed provider check is an expected outcome that
    routes to manual review, not a server error. The frontend/next-phase
    logic decides whether to let onboarding proceed with needs_manual_review=True.
    """
    return Response(
        {
            "success": result["success"],
            "provider": result["provider"],
            "needs_manual_review": not result["success"],
            "data": result["data"],
            "attempts": result["attempts"] if not result["success"] else None,
        },
        status=status.HTTP_200_OK,
    )


# ──────────────────────────────────────────────
# DRIVER VIEWS
# ──────────────────────────────────────────────

class NINVerificationView(BaseDriverAPIView):
    """POST /api/verify/driver/nin/"""
    serializer_class = NINVerificationSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver = self.get_driver(request)

        nin = serializer.validated_data["nin"]
        result = service.verify_nin(nin)
        _record_driver_verification(driver, DriverVerification.TYPE_NIN, result, request_payload={"nin": nin})
        return _verification_response(result)


class BVNVerificationView(BaseDriverAPIView):
    """POST /api/verify/driver/bvn/"""
    serializer_class = BVNVerificationSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver = self.get_driver(request)

        bvn = serializer.validated_data["bvn"]
        result = service.verify_bvn(bvn)
        _record_driver_verification(driver, DriverVerification.TYPE_BVN, result, request_payload={"bvn": bvn})
        return _verification_response(result)


class BVNValidationView(BaseDriverAPIView):
    """POST /api/verify/driver/bvn/validate/"""

    serializer_class = BVNValidationSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver = self.get_driver(request)

        data = serializer.validated_data
        result = service.validate_bvn(
            bvn=data["bvn"],
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            dob=str(data["dob"]) if data.get("dob") else None,
        )
        # Uses the same DriverVerification.TYPE_BVN row as the plain BVN
        # lookup above - it's still "the BVN check", just with matching.
        _record_driver_verification(driver, DriverVerification.TYPE_BVN, result, request_payload=data)
        return _verification_response(result)


class AccountNumberVerificationView(BaseDriverAPIView):
    """POST /api/verify/driver/account/"""

    serializer_class = AccountNumberSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver = self.get_driver(request)

        data = serializer.validated_data
        result = service.verify_account_number(
            account_number=data["account_number"],
            bank_code=data["bank_code"],
            nip_code=data.get("nip_code"),  # optional - add this field to the serializer if you want the Mono fallback active
        )
        _record_driver_verification(
            driver, DriverVerification.TYPE_BANK_ACCOUNT, result,
            request_payload={"account_number": data["account_number"], "bank_code": data["bank_code"]},
        )

        if result["success"]:
            bank_account = getattr(driver, "bank_account", None)
            if bank_account is not None:
                bank_account.is_verified = True
                bank_account.verified_at = timezone.now()
                bank_account.save(update_fields=["is_verified", "verified_at"])

        return _verification_response(result)


class FaceMatchView(BaseDriverAPIView):
    """
    POST /api/verify/driver/face-match/
    Body: { image (base64), first_name, last_name, bvn? | nin? }
    """

    serializer_class = FaceMatchSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        driver = self.get_driver(request)

        data = serializer.validated_data
        result = service.match_face_to_name(
            image=data["image"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            bvn=data.get("bvn"),
            nin=data.get("nin"),
        )
        _record_driver_verification(
            driver, DriverVerification.TYPE_FACE_MATCH, result,
            request_payload={"first_name": data["first_name"], "last_name": data["last_name"]},  # image intentionally excluded
        )
        return _verification_response(result)


class PlateNumberVerificationView(BaseDriverAPIView):
    """
    POST /api/verify/driver/plate/
    Not persisted to DriverVerification - see module docstring.
    """

    serializer_class = PlateNumberSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = service.verify_plate_number(serializer.validated_data["plate_number"])
        return _verification_response(result)


# ──────────────────────────────────────────────
# BUSINESS VIEWS
# ──────────────────────────────────────────────

class TINVerificationView(BaseBuisAdminAPIView):
    """POST /api/verify/business/tin/"""

    serializer_class = TINVerificationSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        business_admin = self.get_buisnessadmn(request)
        business = business_admin.business
        if business is None:
            return Response({"success": False, "error": "No business on this account."}, status=status.HTTP_400_BAD_REQUEST)

        tin = serializer.validated_data["tin"]
        result = service.verify_tin(tin)
        _record_business_verification(business, BusinessVerification.TYPE_TIN, result, request_payload={"tin": tin})
        return _verification_response(result)


class RCNumberVerificationView(BaseBuisAdminAPIView):
    """POST /api/verify/business/rc/"""

    serializer_class = RCNumberSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        business_admin = self.get_buisnessadmn(request)
        business = business_admin.business
        if business is None:
            return Response({"success": False, "error": "No business on this account."}, status=status.HTTP_400_BAD_REQUEST)

        rc_number = serializer.validated_data["rc_number"]
        result = service.verify_rc_number(rc_number)
        _record_business_verification(business, BusinessVerification.TYPE_RC, result, request_payload={"rc_number": rc_number})
        return _verification_response(result)


class BusinessBVNVerificationView(BaseBuisAdminAPIView):
    """POST /api/verify/business/bvn/"""

    serializer_class = BusinessBVNSerializer
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        business_admin = self.get_buisnessadmn(request)
        business = business_admin.business
        if business is None:
            return Response({"success": False, "error": "No business on this account."}, status=status.HTTP_400_BAD_REQUEST)

        bvn = serializer.validated_data["bvn"]
        result = service.verify_business_bvn(bvn)
        _record_business_verification(business, BusinessVerification.TYPE_BVN, result, request_payload={"bvn": bvn})

        if result["success"]:
            payout = getattr(business, "payout", None)
            if payout is not None:
                payout.bvn = bvn[-4:]
                payout.bvn_verification_ref = _extract_ref(result.get("data"))
                payout.save(update_fields=["bvn", "bvn_verification_ref"])

        return _verification_response(result)


# BusinessOnboardStatus
# check onboarding to check if it was approved, add the conterpart to the admin section
class BusinessManualReviewStatusView(BaseBuisAdminAPIView):
    """
    GET /api/verify/business/manual-review/status/
    """

    REVIEW_DAYS = 4

    def get(self, request):
        business_admin = self.get_buisnessadmn(request)
        business = business_admin.business

        if business is None:
            return Response(
                {
                    "success": False,
                    "error": "No business on this account."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        onboard_status, _ = BusinessOnboardStatus.objects.get_or_create(
            admin=business_admin
        )

        verified_items = {
            verification.verification_type: verification.status
            for verification in business.verifications.all()
        }

        return Response({
            "success": True,
            "data": {
                "is_onboarding_complete": onboard_status.is_onboarding_complete,
                "needs_manual_review": onboard_status.needs_manual_review,
                "checked": onboard_status.checked,
                "review_days": self.REVIEW_DAYS
                    if onboard_status.needs_manual_review
                    else None,
                "verifications": verified_items,
                "can_retry": (
                    onboard_status.checked
                    and not onboard_status.needs_manual_review
                    and not onboard_status.is_onboarding_complete
                ),

                "approved": business.onboarding_complete
            }
        })


# class AdminBusinessReviewDetailsView(BaseBuisAdminAPIView):
#     """
#     GET /api/verify/business/manual-review/status/
#     """

#     def get(self, request, businessadmin_id):
#         business_admin = business.businessadmin
#         BusinessAdmin
    
#         onboard_status, _ = BusinessOnboardStatus.objects.get_or_create(
#             admin=business_admin
#         )
    
#         verifications = {
#             verification.verification_type: verification.status
#             for verification in business.verifications.all()
#         }
    
#         required_types = [
#             BusinessVerification.TYPE_BVN,
#             BusinessVerification.TYPE_TIN,
#             BusinessVerification.TYPE_RC,
#         ]
    
#         has_all_verifications = all(
#             verification_type in verifications
#             for verification_type in required_types
#         )
    
#         has_failure = any(
#             verifications.get(verification_type)
#             == BusinessVerification.STATUS_FAILED
#             for verification_type in required_types
#         )
    
#         if has_all_verifications and has_failure:
#             onboard_status.needs_manual_review = True
#             onboard_status.checked = False
    
#             onboard_status.save(
#                 update_fields=[
#                     "needs_manual_review",
#                     "checked",
#                 ]
#             )
    
#         return onboard_status

# class AdminBusinessReviewListView(BaseBuisAdminAPIView):
#     """
#     GET /api/verify/business/manual-review/status/
#     """

#     def get(self, request):
#         business_admin = business.businessadmin
#         # BusinessAdmin.objects.filter(business__).all()
#         onboard_status, _ = BusinessOnboardStatus.objects.get_or_create(
#             admin=business_admin
#         )
    
#         verifications = {
#             verification.verification_type: verification.status
#             for verification in business.verifications.all()
#         }
    
#         required_types = [
#             BusinessVerification.TYPE_BVN,
#             BusinessVerification.TYPE_TIN,
#             BusinessVerification.TYPE_RC,
#         ]
    
#         has_all_verifications = all(
#             verification_type in verifications
#             for verification_type in required_types
#         )
    
#         has_failure = any(
#             verifications.get(verification_type)
#             == BusinessVerification.STATUS_FAILED
#             for verification_type in required_types
#         )
    
#         if has_all_verifications and has_failure:
#             onboard_status.needs_manual_review = True
#             onboard_status.checked = False
    
#             onboard_status.save(
#                 update_fields=[
#                     "needs_manual_review",
#                     "checked",
#                 ]
#             )
    
#         return onboard_status
        