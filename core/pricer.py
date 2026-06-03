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

    For each resource, calls provider.get_price() and creates a new enriched
    dict with pricing data. Missing or failed pricing lookups are filled with
    safe zero values. Returns a new list; does not modify input in-place.

    Args:
        resources: List of resource dicts from extractor or CSV import.
        provider:  An authenticated (or at least initialised) BaseProvider.
                   Note: Azure pricing does not require auth, but the
                   provider instance is still needed for dispatch.

    Returns:
        A new list of dicts, each containing original keys plus pricing keys:
            unit               — e.g. "1 Hour", "1 GB/Month"
            quantity           — estimated units consumed per month
            unit_price_usd     — retail price per unit in USD
            estimated_cost_usd — unit_price * quantity
    """
    total   = len(resources)
    priced  = 0
    skipped = 0
    enriched_resources = []

    header(f"[PRICER] Enriching {total} resource(s) with pricing data...")

    for i, resource in enumerate(resources, start=1):
        rtype = resource.get("resource_type", "unknown")
        rname = resource.get("resource_name", "unknown")

        # Show progress every 10 items or on the last item
        if i % 10 == 0 or i == total:
            dim(f"  [{i}/{total}] {rname} ({rtype})")

        try:
            price_data = provider.get_price(resource)

            # Create a new dict with original data + pricing fields.
            # This avoids modifying the input and prevents race conditions.
            enriched = resource.copy()
            enriched["unit"]               = price_data.get("unit", "NDF") or "NDF"
            enriched["quantity"]           = price_data.get("quantity", 0)
            enriched["unit_price_usd"]     = price_data.get("unit_price_usd", 0.0)
            enriched["estimated_cost_usd"] = price_data.get("estimated_cost_usd", 0.0)

            enriched_resources.append(enriched)
            priced += 1

        except Exception as e:
            # Never let a single pricing failure stop the whole run.
            # Log the error and mark pricing fields as NDF.
            warn(f"  [WARN] Pricing failed for {rname}: {e}")
            enriched = resource.copy()
            enriched["unit"]               = "NDF"
            enriched["quantity"]           = 0
            enriched["unit_price_usd"]     = 0.0
            enriched["estimated_cost_usd"] = 0.0
            enriched_resources.append(enriched)
            skipped += 1

    success_msg = f"\n[PRICER] Done. Priced: {priced}  |  Errors: {skipped}\n"
    success(success_msg) if skipped == 0 else warn(success_msg)
    return enriched_resources
