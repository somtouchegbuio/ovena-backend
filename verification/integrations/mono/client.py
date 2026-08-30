"""
Mono Lookup API client (server-side).

Mono has no official server-side Python SDK - Mono's own SDK page
(docs.mono.co/docs/sdks) only lists official SDKs for the *frontend*
Connect widget (JS, iOS, Android, Flutter, React Native). The handful of
third-party Python wrappers on PyPI (mono-sdk, Py-Mono, monopy) are
unofficial and low-adoption, so this stays a thin `requests` wrapper -
same approach the codebase already used for Paystack.

Confirmed v3 Lookup endpoints (docs.mono.co/docs/lookup/*):

    NIN             POST /v3/lookup/nin              {nin}
    TIN / CAC       POST /v3/lookup/tin               {number, channel: "tin"|"cac"}
    CAC search      GET  /v3/lookup/cac?search=...
    Account number  POST /v3/lookup/account-number    {account_number, nip_code}

Deliberately NOT implemented here:

    BVN - Mono's BVN product ("BVN iGree") is a 3-step OTP/consent flow:
        POST /v2/lookup/bvn/initiate  -> sends OTP to the BVN owner
        POST /v2/lookup/bvn/verify    -> user submits the OTP
        POST /v2/lookup/bvn/details   -> returns the BVN data
    That requires the BVN owner to receive and relay a one-time code -
    it isn't a same-shape substitute for a single verify_bvn(bvn) call,
    so it's excluded from the Dojah-first/Mono-fallback pattern in
    verification/service.py. Wire it up as its own multi-step flow if
    you want it later.

Every function returns:
    {
        "success": bool,
        "provider_ref": str,
        "response_payload": dict,
        "error": str | None,
    }
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MONO_BASE_URL = "https://api.withmono.com/v3"


def _headers():
    return {
        "mono-sec-key": getattr(settings, "MONO_SECRET_KEY", ""),
        "Content-Type": "application/json",
    }


def _handle(resp, lookup_type):
    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code == 200 and data.get("status") == "successful":
        inner = data.get("data", data)
        ref = ""
        if isinstance(inner, dict):
            ref = inner.get("tracking_id") or inner.get("id") or ""
        return {
            "success": True,
            "provider_ref": ref,
            "response_payload": inner,
            "error": None,
        }

    error_msg = data.get("message") or data.get("error") or f"HTTP {resp.status_code}"
    logger.warning("Mono %s lookup failed: %s", lookup_type, error_msg)
    return {"success": False, "provider_ref": "", "response_payload": data, "error": error_msg}


def _post(path, payload, lookup_type):
    try:
        resp = requests.post(f"{MONO_BASE_URL}{path}", json=payload, headers=_headers(), timeout=15)
        return _handle(resp, lookup_type)
    except requests.RequestException as exc:
        logger.exception("Mono %s request error: %s", lookup_type, exc)
        return {"success": False, "provider_ref": "", "response_payload": {}, "error": str(exc)}


def _get(path, params, lookup_type):
    try:
        resp = requests.get(f"{MONO_BASE_URL}{path}", params=params, headers=_headers(), timeout=15)
        return _handle(resp, lookup_type)
    except requests.RequestException as exc:
        logger.exception("Mono %s request error: %s", lookup_type, exc)
        return {"success": False, "provider_ref": "", "response_payload": {}, "error": str(exc)}


def verify_nin(nin: str) -> dict:
    """Verify a Nigerian NIN via Mono NIN Lookup."""
    return _post("/lookup/nin", {"nin": nin}, "nin")


def verify_tin(number: str, channel: str = "tin") -> dict:
    """
    Verify a TIN or RC/CAC number via Mono TIN Lookup.
    channel="tin" for a tax ID, channel="cac" when `number` is an RC number.
    """
    return _post("/lookup/tin", {"number": number, "channel": channel}, f"tin:{channel}")


def lookup_cac(search: str) -> dict:
    """Search a business by name or RC number."""
    return _get("/lookup/cac", {"search": search}, "cac")


def verify_account_number(account_number: str, nip_code: str) -> dict:
    """
    Verify a NUBAN via Mono Account Number Lookup.
    nip_code is Mono's own bank code scheme - NOT the CBN bank_code Dojah
    uses. See https://docs.mono.co/api/miscellaneous/bank-coverage for
    the bank -> nip_code list.
    """
    return _post(
        "/lookup/account-number",
        {"account_number": account_number, "nip_code": nip_code},
        "account-number",
    )
