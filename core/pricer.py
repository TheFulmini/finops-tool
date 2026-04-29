# core/pricer.py
# ============================================================
# Pricer — Enrich Resources with Pricing Data
# ============================================================
# Takes a list of resource dicts (from extractor.py or loaded
# from an existing CSV) and adds pricing columns to each row.
#
# For each resource it calls provider.get_price() and merges
# the returned pricing fields into the resource dict.
#
# This module is also provider-agnostic — pricing logic lives
# entirely inside the provider's pricing module.
# ============================================================

from typing import List, Dict, Any

from providers.base import BaseProvider
from core.console import header, success, warn, error, info, dim


def enrich(
    resources: List[Dict[str, Any]],
    provider: BaseProvider,
) -> List[Dict[str, Any]]:
    """
    Add pricing columns to each resource dict.

    For each resource, calls provider.get_price() and merges
    the result into the resource dict in-place. Missing or
    failed pricing lookups are filled with safe zero values.

    Args:
        resources: List of resource dicts from extractor or CSV import.
        provider:  An authenticated (or at least initialised) BaseProvider.
                   Note: Azure pricing does not require auth, but the
                   provider instance is still needed for dispatch.

    Returns:
        The same list of dicts, each now containing these additional keys:
            unit               — e.g. "1 Hour", "1 GB/Month"
            quantity           — estimated units consumed per month
            unit_price_usd     — retail price per unit in USD
            estimated_cost_usd — unit_price * quantity
    """
    total   = len(resources)
    priced  = 0
    skipped = 0

    header(f"[PRICER] Enriching {total} resource(s) with pricing data...")

    for i, resource in enumerate(resources, start=1):
        rtype = resource.get("resource_type", "unknown")
        rname = resource.get("resource_name", "unknown")

        # Show progress every 10 items or on the last item
        if i % 10 == 0 or i == total:
            dim(f"  [{i}/{total}] {rname} ({rtype})")

        try:
            price_data = provider.get_price(resource)

            # Merge pricing fields into the resource dict.
            # Use "NDF" for the unit string if the API returned nothing.
            resource["unit"]               = price_data.get("unit", "NDF") or "NDF"
            resource["quantity"]           = price_data.get("quantity", 0)
            resource["unit_price_usd"]     = price_data.get("unit_price_usd", 0.0)
            resource["estimated_cost_usd"] = price_data.get("estimated_cost_usd", 0.0)

            priced += 1

        except Exception as e:
            # Never let a single pricing failure stop the whole run.
            # Log the error and mark pricing fields as NDF.
            warn(f"  [WARN] Pricing failed for {rname}: {e}")
            resource["unit"]               = "NDF"
            resource["quantity"]           = 0
            resource["unit_price_usd"]     = 0.0
            resource["estimated_cost_usd"] = 0.0
            skipped += 1

    success_msg = f"\n[PRICER] Done. Priced: {priced}  |  Errors: {skipped}\n"
    success(success_msg) if skipped == 0 else warn(success_msg)
    return resources
