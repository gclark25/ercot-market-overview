"""
Market-wide ERCOT data pulls for Tabs 1 and 2.

Known-good report endpoints (confirmed working in hen-morning-report already —
port the pull logic, don't re-derive):
    - AS DA clearing prices : np4-188-cd/dam_clear_price_for_cap   (REGUP, REGDN, RRS, NSPIN, ECRS)
    - AS RT clearing prices : np6-795-er (or np6-796-er, 15-min settlement, average to hourly)

Still to confirm / port when this module is filled in:
    - Hub energy DA settlement point prices report ID
    - Hub energy RT settlement point prices report ID
    - Net load = gross_load - wind - solar, using the same STWPF/STPPF /
      inUseFlag filtering rules already solved in hen_integrations.py:
        * STWPFSystemWide / STPPFSystemWide are system-wide totals repeated
          across zone rows — take first-row-per-key, do not sum across rows.
        * Load forecast must filter to inUseFlag == True only.

All functions here should return hourly series keyed by ISO date + HE (hour-
ending, 1-24) so aggregations.py can roll them up into yesterday / 3-day /
MTD / YTD windows without re-deriving date logic per-caller.
"""

from ercot_client import ErcotCredentials


def get_net_load_series(creds: ErcotCredentials, days_history: int = 3, days_forecast: int = 5) -> dict:
    """
    Gross load, wind, solar, and net load (gross - wind - solar) for
    `days_history` days of actuals plus `days_forecast` days of forecast.

    TODO: port the STWPF/STPPF first-row-per-key handling and the
    inUseFlag == True load filter from hen_integrations.py.
    """
    raise NotImplementedError


def get_hub_energy_prices(creds: ErcotCredentials, hubs: list[str]) -> dict:
    """
    Hourly DA and RT settlement point prices (HE1-24) for the given hubs,
    going back far enough to cover YTD rollups.

    Returns: { hub: { "YYYY-MM-DD": { "DA": [...24 values...], "RT": [...24 values...] } } }

    TODO: confirm/port the DAM and RTM settlement point price report IDs
    already in use for the existing HEN nodal DART tables.
    """
    raise NotImplementedError


def get_as_prices(creds: ErcotCredentials, services: list[str] | None = None) -> dict:
    """
    Hourly DA and RT AS clearing prices (HE1-24) per service.

    services defaults to ["REGUP", "REGDN", "RRS", "NSPIN", "ECRS"].

    DA source : np4-188-cd/dam_clear_price_for_cap
    RT source : np6-795-er (weekly historical, hourly-averaged from 15-min settlement)

    TODO: port collect_as_prices() from hen_integrations.py — this logic
    already exists and is confirmed working.
    """
    raise NotImplementedError
