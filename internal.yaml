"""
Shared ERCOT Public API client.

PORT FROM hen-morning-report/hen_integrations.py:
    - token acquisition / refresh logic (currently working there for the daily
      HEN pipeline — reuse it as-is rather than re-deriving auth from scratch)
    - the base request wrapper (headers, retry/backoff, subscription key handling)

This module is the market-wide equivalent: same auth, but the report IDs pulled
here are market-wide (hub prices, AS clearing prices, system load/wind/solar)
rather than HEN's 32 asset-specific nodes.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ErcotCredentials:
    username: str
    password: str
    subscription_key: str


def get_ercot_token(creds: ErcotCredentials) -> str:
    """
    Return a valid bearer token, refreshing if expired.

    TODO: port the exact token endpoint / grant flow from hen_integrations.py.
    Do not re-implement from scratch — the existing HEN pipeline has already
    solved token refresh reliably in production.
    """
    raise NotImplementedError("Port token logic from hen-morning-report/hen_integrations.py")


def ercot_get(report_endpoint: str, params: dict[str, Any], creds: ErcotCredentials) -> dict:
    """
    Base GET wrapper against api.ercot.com/api/public-reports/<report_endpoint>.

    TODO: port retry/backoff and the Ocp-Apim-Subscription-Key header handling
    from hen_integrations.py's existing request wrapper.
    """
    raise NotImplementedError("Port request wrapper from hen-morning-report/hen_integrations.py")
