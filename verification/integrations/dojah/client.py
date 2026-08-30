"""
Dojah API client.

Kept as plain `requests` calls rather than switching to the official
`dojah-python-sdk` (pip install dojah-python-sdk). That SDK does exist and
is actively maintained (github.com/dojah-inc/dojah-sdks, OpenAPI-generated,
currently 4.1.0) - but its exact method surface for every endpoint used
here (photoid verify, plate number, tin, cac) wasn't something I could
fully verify without the generated client in front of me. These endpoints
are already known-good against your account, so left them as direct HTTP
calls to avoid swapping in unverified method names. Worth revisiting if
you want typed responses / async support - just confirm each method
against the SDK docs before swapping.
"""
import requests
from django.conf import settings

DOJAH_BASE_URL = "https://sandbox.dojah.io"#"https://api.dojah.io"


def _headers():
    return {
        "AppId": settings.DOJAH_APP_ID,
        "Authorization": settings.DOJAH_SECRET_KEY,
        "Content-Type": "application/json",
    }


def _get(path, params=None):
    url = f"{DOJAH_BASE_URL}{path}"
    response = requests.get(url, headers=_headers(), params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def _post(path, payload=None):
    url = f"{DOJAH_BASE_URL}{path}"
    response = requests.post(url, headers=_headers(), json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


# ──────────────────────────────────────────────
# DRIVER VERIFICATIONS
# ──────────────────────────────────────────────

def verify_nin(nin: str) -> dict:
    """Look up a National Identification Number (NIN)."""
    return _get("/api/v1/kyc/nin", params={"nin": nin})


def verify_bvn(bvn: str) -> dict:
    """Look up a Bank Verification Number (BVN)."""
    return _get("/api/v1/kyc/bvn/full", params={"bvn": bvn})


def validate_bvn(bvn: str, first_name: str = None, last_name: str = None, dob: str = None) -> dict:
    """
    Validate a BVN by matching it against supplied name/DOB.
    - dob format: YYYY-MM-DD
    """
    params = {"bvn": bvn}
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name
    if dob:
        params["dob"] = dob
    return _get("/api/v1/kyc/bvn", params=params)


def verify_account_number(account_number: str, bank_code: str) -> dict:
    """
    Look up a NUBAN account number.
    - bank_code: CBN bank code e.g. "044" for Access Bank.
    """
    return _get("/api/v1/kyc/nuban", params={
        "account_number": account_number,
        "bank_code": bank_code,
    })


def match_face_to_name(
    image: str,
    first_name: str,
    last_name: str,
    bvn: str = None,
    nin: str = None,
) -> dict:
    """
    Match a selfie/face image against government ID data (BVN or NIN).
    - image: base64-encoded JPEG/PNG string.
    - Provide at least one of bvn or nin.
    """
    payload = {
        "image": image,
        "first_name": first_name,
        "last_name": last_name,
    }
    if bvn:
        payload["bvn"] = bvn
    if nin:
        payload["nin"] = nin
    return _post("/api/v1/kyc/photoid/verify", payload=payload)


def verify_plate_number(plate_number: str) -> dict:
    """Look up a Nigerian vehicle plate number."""
    return _get("/api/v1/kyc/plate_number", params={"plate_number": plate_number})


# ──────────────────────────────────────────────
# BUSINESS VERIFICATIONS
# ──────────────────────────────────────────────

def verify_tin(tin: str) -> dict:
    """Verify a Tax Identification Number (TIN) via FIRS."""
    return _get("/api/v1/kyc/tin", params={"tin": tin})


def verify_rc_number(rc_number: str) -> dict:
    """Look up a CAC RC (Registration) Number."""
    return _get("/api/v1/kyc/cac", params={"rc_number": rc_number})


def verify_business_bvn(bvn: str) -> dict:
    """Verify the BVN of a business owner/director (same lookup as personal BVN)."""
    return _get("/api/v1/kyc/bvn/full", params={"bvn": bvn})
