# providers/azure/pricing.py
# ============================================================
# Azure Retail Pricing
# ============================================================
# Calls the Azure Retail Prices REST API to look up the
# current list price for each resource.
#
# API documentation:
#   https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
#
# Key facts about this API:
#   - Free to call, no authentication required
#   - Returns retail (list) prices — not your negotiated/EA price
#   - Prices are in USD
#   - Supports OData $filter for server-side filtering
#   - Paginated: each response has a nextPageLink if there are more results
#
# Strategy per resource type:
#   We build a specific OData filter for each resource type so
#   we fetch only the relevant price rows. Pricing data is
#   cached per session to avoid redundant API calls.
# ============================================================

import requests
from typing import Dict, Any, Optional

# Base URL for the Azure Retail Prices API (v3 supports richer filtering)
PRICING_API_URL = "https://prices.azure.com/api/retail/prices"
API_VERSION     = "2023-01-01-preview"

# ── In-memory cache ────────────────────────────────────────
# Key:   a string representing the filter query used
# Value: list of price rows returned by the API
# This avoids calling the API multiple times for the same resource config
_price_cache: Dict[str, list] = {}


# ── API helper ─────────────────────────────────────────────

def _fetch_prices(odata_filter: str) -> list:
    """
    Call the Azure Retail Prices API with a given OData filter.
    Handles pagination automatically and caches results.

    Args:
        odata_filter: An OData $filter expression, e.g.:
            "serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_D2s_v3'
             and armRegionName eq 'eastus' and priceType eq 'Consumption'"

    Returns:
        List of price item dicts from the API.
        Returns an empty list if the API call fails.
    """
    # Return cached result if we've seen this filter before
    if odata_filter in _price_cache:
        return _price_cache[odata_filter]

    all_items = []
    url = PRICING_API_URL
    params = {
        "api-version": API_VERSION,
        "$filter":     odata_filter,
    }

    # The API paginates at 100 items per page — follow nextPageLink until done
    while url:
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            all_items.extend(data.get("Items", []))

            # nextPageLink is a fully-formed URL — pass it directly on next loop
            url    = data.get("NextPageLink")
            params = {}  # Params are already baked into the nextPageLink URL

        except requests.RequestException as e:
            print(f"  [PRICE API] Request failed: {e}")
            break

    # Cache the result for this filter so we don't call the API again
    _price_cache[odata_filter] = all_items
    return all_items


def _pick_best_price(items: list) -> Optional[Dict]:
    """
    From a list of price items returned by the API, pick the most
    relevant one for cost estimation.

    Azure often returns multiple rows for the same SKU (e.g. Spot,
    Low Priority, Reserved, Consumption). We prefer:
        1. priceType == 'Consumption'  (pay-as-you-go)
        2. Not a Spot or Low Priority price
        3. Lowest unit price (in case of duplicates)

    Returns the selected item dict, or None if the list is empty.
    """
    if not items:
        return None

    # Filter to Consumption (PAYG) prices only
    consumption = [
        i for i in items
        if i.get("priceType", "").lower() == "consumption"
        and "spot" not in i.get("skuName", "").lower()
        and "low priority" not in i.get("skuName", "").lower()
    ]

    candidates = consumption if consumption else items

    # Among candidates, return the one with the lowest retail price
    return min(candidates, key=lambda i: i.get("retailPrice", float("inf")))


# ── Per resource-type price lookups ────────────────────────
# Each function below knows how to build the right OData filter
# for its resource type and how to interpret the unit returned.

def _price_virtual_machine(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Look up the hourly price for an Azure Virtual Machine.

    The VM size (e.g. Standard_D2s_v3) is the key identifier.
    We combine it with the region to get the right price.
    """
    vm_size  = resource.get("size", "")
    location = resource.get("location", "")

    if not vm_size or not location:
        return _empty_price("1 Hour")

    # Azure pricing uses region names in a specific format (e.g. 'eastus')
    # which matches the location field from the resource manager API
    odata = (
        f"serviceName eq 'Virtual Machines' "
        f"and armSkuName eq '{vm_size}' "
        f"and armRegionName eq '{location}' "
        f"and priceType eq 'Consumption'"
    )

    items = _fetch_prices(odata)
    best  = _pick_best_price(items)

    if not best:
        return _empty_price("1 Hour")

    unit_price = best.get("retailPrice", 0.0)

    # Estimate: assume 730 hours/month (average month)
    hours_per_month = 730
    return {
        "unit":               best.get("unitOfMeasure", "1 Hour"),
        "quantity":           hours_per_month,
        "unit_price_usd":     round(unit_price, 6),
        "estimated_cost_usd": round(unit_price * hours_per_month, 4),
    }


def _price_storage_account(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Look up the price for an Azure Storage Account.

    Storage accounts don't have a single fixed price — cost depends
    on the amount of data stored (GB/month). We return the per-GB
    price for LRS (Locally Redundant Storage) as a baseline.

    SKU examples: Standard_LRS, Standard_GRS, Premium_LRS
    """
    sku      = resource.get("sku", "Standard_LRS")
    location = resource.get("location", "")

    if not location:
        return _empty_price("1 GB/Month")

    # Map SKU to a friendly redundancy string the pricing API recognises
    # Standard_LRS → "LRS", Standard_GRS → "GRS", etc.
    redundancy = sku.split("_")[-1] if "_" in sku else "LRS"
    tier       = sku.split("_")[0] if "_" in sku else "Standard"

    odata = (
        f"serviceName eq 'Storage' "
        f"and skuName eq '{tier} {redundancy}' "
        f"and armRegionName eq '{location}' "
        f"and priceType eq 'Consumption'"
    )

    items = _fetch_prices(odata)
    # Look specifically for the data stored (capacity) metre
    capacity_items = [
        i for i in items
        if "data stored" in i.get("meterName", "").lower()
        or "capacity" in i.get("meterName", "").lower()
    ]
    best = _pick_best_price(capacity_items) or _pick_best_price(items)

    if not best:
        return _empty_price("1 GB/Month")

    unit_price = best.get("retailPrice", 0.0)

    # We don't know actual GB stored — use 100 GB as a placeholder quantity
    # The user can update this in the CSV once they know actual usage
    placeholder_gb = 100
    return {
        "unit":               best.get("unitOfMeasure", "1 GB/Month"),
        "quantity":           placeholder_gb,
        "unit_price_usd":     round(unit_price, 6),
        "estimated_cost_usd": round(unit_price * placeholder_gb, 4),
        # Note: flag that this is an estimate based on placeholder quantity
    }


def _price_sql_database(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Look up the price for an Azure SQL Database.

    SQL Database pricing varies greatly by service tier:
        - DTU model: Basic, Standard (S0-S12), Premium (P1-P15)
        - vCore model: General Purpose, Business Critical, Hyperscale

    We use the SKU tier from the resource to build the filter.
    """
    sku      = resource.get("sku", "")
    location = resource.get("location", "")

    if not location:
        return _empty_price("1 Hour")

    odata = (
        f"serviceName eq 'SQL Database' "
        f"and armRegionName eq '{location}' "
        f"and priceType eq 'Consumption'"
    )

    # Narrow by SKU if we have one (e.g. "Standard", "GeneralPurpose")
    if sku:
        odata += f" and skuName eq '{sku}'"

    items = _fetch_prices(odata)
    best  = _pick_best_price(items)

    if not best:
        return _empty_price("1 Hour")

    unit_price = best.get("retailPrice", 0.0)
    hours_per_month = 730
    return {
        "unit":               best.get("unitOfMeasure", "1 Hour"),
        "quantity":           hours_per_month,
        "unit_price_usd":     round(unit_price, 6),
        "estimated_cost_usd": round(unit_price * hours_per_month, 4),
    }


def _price_app_service_plan(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Look up the price for an Azure App Service Plan.

    App Service Plans are billed by tier and instance size,
    e.g. B1, S1, P1v2, P2v3.
    The SKU field from the resource contains this size string.
    """
    sku      = resource.get("sku", "")
    location = resource.get("location", "")

    if not location:
        return _empty_price("1 Hour")

    odata = (
        f"serviceName eq 'Azure App Service' "
        f"and armRegionName eq '{location}' "
        f"and priceType eq 'Consumption'"
    )

    if sku:
        odata += f" and armSkuName eq '{sku}'"

    items = _fetch_prices(odata)
    best  = _pick_best_price(items)

    if not best:
        return _empty_price("1 Hour")

    unit_price = best.get("retailPrice", 0.0)
    hours_per_month = 730
    return {
        "unit":               best.get("unitOfMeasure", "1 Hour"),
        "quantity":           hours_per_month,
        "unit_price_usd":     round(unit_price, 6),
        "estimated_cost_usd": round(unit_price * hours_per_month, 4),
    }


def _price_virtual_network(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Virtual Networks themselves have no direct hourly cost.
    Costs arise from peering, gateways, and data transfer —
    which require separate resource entries.

    We return zero price with a descriptive unit so the CSV
    is explicit about why the cost shows as zero.
    """
    return {
        "unit":               "N/A (costs from peering/data transfer)",
        "quantity":           0,
        "unit_price_usd":     0.0,
        "estimated_cost_usd": 0.0,
    }


def _empty_price(unit: str = "") -> Dict[str, Any]:
    """
    Return a zeroed-out price dict when pricing data is unavailable.
    Used as a safe fallback — ensures the CSV always has all columns.
    """
    return {
        "unit":               unit,
        "quantity":           0,
        "unit_price_usd":     0.0,
        "estimated_cost_usd": 0.0,
    }


# ── Dispatch table ─────────────────────────────────────────
# Maps each resource type string to its pricing function.
# To add pricing support for a new resource type, add an entry
# here and write a corresponding _price_<type> function above.

PRICE_HANDLERS: Dict[str, callable] = {
    "microsoft.compute/virtualmachines":  _price_virtual_machine,
    "microsoft.storage/storageaccounts": _price_storage_account,
    "microsoft.sql/servers/databases":   _price_sql_database,
    "microsoft.web/serverfarms":         _price_app_service_plan,
    "microsoft.network/virtualnetworks": _price_virtual_network,
}


# ── Public interface ───────────────────────────────────────

def get_price(resource: Dict[str, Any]) -> Dict[str, Any]:
    """
    Look up the retail price for a single resource.
    This is the main entry point called by the pricer.

    Dispatches to the appropriate handler based on resource_type.
    Falls back to _empty_price() for unknown/unsupported types.

    Args:
        resource: A resource dict as returned by resources.get_resources().

    Returns:
        Dict with keys: unit, quantity, unit_price_usd, estimated_cost_usd
    """
    # Normalise to lowercase for reliable key matching
    rtype = resource.get("resource_type", "").lower()

    handler = PRICE_HANDLERS.get(rtype)

    if handler:
        return handler(resource)
    else:
        # Unknown type — return zeros and note it in the unit field
        print(f"  [PRICE] No handler for resource type: {rtype}")
        return _empty_price("Unsupported type")
