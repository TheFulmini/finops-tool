# core/exporter.py
# ============================================================
# CSV Exporter / Importer
# ============================================================
# Handles all file I/O for the tool:
#
#   export_csv()  — write a list of enriched resource dicts
#                   to a CSV file with a consistent column order
#
#   import_csv()  — load a pre-existing CSV file back into the
#                   same list-of-dicts format so it can be
#                   re-priced or re-exported without hitting
#                   the cloud APIs again
#
# Missing data convention:
#   Text fields with no data use "NDF" (No Data Found).
#   Numeric fields (prices, quantities) default to 0 so that
#   sums and formulas in Excel still work correctly.
#
# We use pandas for CSV handling because it deals gracefully
# with encoding issues, mixed types, and missing columns.
# ============================================================

import pandas as pd
import os
import logging
from typing import List, Dict, Any

from core.console import header, success, warn, error, info, dim, highlight, item

logger = logging.getLogger(__name__)

# Minimum required columns for valid resource data
REQUIRED_COLUMNS = {"resource_name", "resource_type", "location"}


# ── Column schema ──────────────────────────────────────────
# Canonical column order for the output CSV.
# Extra keys in the resource dicts are appended at the end.

COLUMNS = [
    "subscription_id",
    "subscription_name",
    "resource_group",
    "resource_name",
    "resource_type",
    "location",
    "sku",
    "size",
    "unit",
    "quantity",
    "unit_price_usd",
    "estimated_cost_usd",
]

# Text columns that should show "NDF" when empty.
# Numeric columns are intentionally excluded — 0 is more useful than "NDF"
# in a cell that Excel expects to be a number.
NDF = "NDF"
TEXT_COLUMNS = {
    "subscription_id", "subscription_name", "resource_group",
    "resource_name", "resource_type", "location", "sku", "size", "unit",
}


def export_csv(
    resources: List[Dict[str, Any]],
    output_path: str,
) -> None:
    """
    Write a list of enriched resource dicts to a CSV file.

    Columns are written in the order defined in COLUMNS above.
    Additional keys are appended as extra columns at the right.
    Empty text fields are written as "NDF"; numeric fields as 0.

    Args:
        resources:   List of resource dicts (from pricer.enrich()).
        output_path: Full path to the output CSV file.

    Raises:
        SystemExit: If the file cannot be written.
    """
    if not resources:
        warn("[EXPORT] No resources to export. Output file not created.")
        return

    # Build a DataFrame from the list of dicts
    df = pd.DataFrame(resources)

    # Reorder: canonical columns first, then any extras
    extra_cols   = [c for c in df.columns if c not in COLUMNS]
    ordered_cols = [c for c in COLUMNS if c in df.columns] + extra_cols
    df = df[ordered_cols]

    # Apply NDF / 0 defaults to missing or empty cells
    _apply_ndf_defaults(df)

    # Round float columns to 4 decimal places for readability
    for col in ["unit_price_usd", "estimated_cost_usd"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(4)

    try:
        # utf-8-sig adds a BOM so Excel opens the file with correct encoding
        df.to_csv(output_path, index=False, encoding="utf-8-sig")

        success(f"\n[EXPORT] Wrote {len(df)} rows → {output_path}")
        _print_summary(df)

    except IOError as e:
        error(f"[EXPORT] Failed to write file: {e}")
        raise SystemExit(1)


def import_csv(input_path: str) -> List[Dict[str, Any]]:
    """
    Load a pre-existing CSV file into the tool's internal format.

    Minimum required columns: resource_name, resource_type, location.
    All other canonical columns are added with NDF/0 defaults if absent.

    Args:
        input_path: Path to the existing CSV file.

    Returns:
        List of resource dicts matching the extractor output format.

    Raises:
        SystemExit: If the file cannot be read, is empty, or is missing required columns.
    """
    if not os.path.exists(input_path):
        error(f"[IMPORT] File not found: {input_path}")
        raise SystemExit(1)

    try:
        # Read all values as strings initially — pandas type inference
        # can silently corrupt IDs and version strings
        df = pd.read_csv(input_path, dtype=str, encoding="utf-8-sig")

        if df.empty:
            warn(f"[IMPORT] The file {input_path} is empty.")
            raise SystemExit(1)

        # ─── Validate required columns ─────────────────────
        missing_columns = REQUIRED_COLUMNS - set(df.columns)
        if missing_columns:
            error(f"[IMPORT] CSV is missing required columns: {missing_columns}")
            error(f"[IMPORT] Found columns: {list(df.columns)}")
            raise SystemExit(1)

        header(f"[IMPORT] Loaded {len(df)} rows from: {input_path}")
        dim(f"[IMPORT] Columns found: {list(df.columns)}\n")
        logger.info(f"CSV schema validation passed: all required columns present")

        # Add any missing canonical columns
        _fill_missing_columns(df)

        # Convert back to list of plain dicts
        resources = df.to_dict(orient="records")

        # Normalise any remaining NaN values to NDF or 0
        for row in resources:
            for key, value in row.items():
                is_nan = False
                try:
                    is_nan = pd.isna(value)
                except (TypeError, ValueError):
                    pass

                if is_nan or value == "nan":
                    row[key] = NDF if key in TEXT_COLUMNS else 0

        return resources

    except pd.errors.ParserError as e:
        error(f"[IMPORT] Failed to parse CSV: {e}")
        raise SystemExit(1)


# ── Private helpers ────────────────────────────────────────

def _apply_ndf_defaults(df: pd.DataFrame) -> None:
    """
    Replace empty/NaN cells with NDF (text columns) or 0 (numeric columns).
    Modifies df in-place.
    """
    for col in df.columns:
        if col in TEXT_COLUMNS:
            # Replace NaN and empty strings with NDF
            df[col] = df[col].fillna(NDF).replace("", NDF)
        else:
            # Replace NaN with 0 for numeric columns
            df[col] = df[col].fillna(0)


def _fill_missing_columns(df: pd.DataFrame) -> None:
    """
    Add canonical columns that are absent from an imported CSV.
    Text columns default to NDF; numeric columns default to 0.
    Modifies df in-place.
    """
    # Map each canonical column to its appropriate default
    defaults = {col: (NDF if col in TEXT_COLUMNS else "0") for col in COLUMNS}

    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
            warn(f"  [IMPORT] Missing column '{col}' added with default: {default}")


def _print_summary(df: pd.DataFrame) -> None:
    """
    Print a colour-coded cost summary to the terminal after export.
    Gives an at-a-glance view without needing to open the CSV.
    """
    divider = "─" * 57

    highlight(f"\n{divider}")
    highlight(f"  COST SUMMARY — Estimated Monthly (USD)")
    highlight(divider)

    if "estimated_cost_usd" not in df.columns:
        warn("  No pricing data available.")
        highlight(divider + "\n")
        return

    # Convert to numeric — NDF rows and errors become 0
    costs = pd.to_numeric(df["estimated_cost_usd"], errors="coerce").fillna(0)
    total = costs.sum()

    highlight(f"\n  Total:  ${total:>12,.2f}\n")

    # Breakdown by resource type
    if "resource_type" in df.columns:
        info("  By resource type:")
        df_copy = df.copy()
        df_copy["_cost"] = costs

        # Exclude rows priced at 0 (NDF or free resources) from the breakdown
        # but still show them with a note
        by_type = (
            df_copy.groupby("resource_type")["_cost"]
            .sum()
            .sort_values(ascending=False)
        )
        for rtype, cost in by_type.items():
            cost_str = f"${cost:>10,.2f}"
            if cost == 0:
                # Zero-cost rows (e.g. VNets, or NDF pricing) shown dimmed
                dim(f"    {rtype:<50} {cost_str}  (no price data)")
            else:
                info(f"    {rtype:<50} {cost_str}")

    # Breakdown by subscription (only if more than one)
    if "subscription_name" in df.columns:
        valid_subs = df["subscription_name"].replace(NDF, pd.NA).dropna()
        if valid_subs.nunique() > 1:
            info("\n  By subscription:")
            df_copy = df.copy()
            df_copy["_cost"] = costs
            by_sub = (
                df_copy.groupby("subscription_name")["_cost"]
                .sum()
                .sort_values(ascending=False)
            )
            for sub, cost in by_sub.items():
                info(f"    {sub:<50} ${cost:>10,.2f}")

    # Count of NDF rows (pricing not available) as a quality indicator
    ndf_count = (df.get("unit", pd.Series(dtype=str)) == NDF).sum()
    if ndf_count > 0:
        warn(f"\n  Note: {ndf_count} resource(s) have no price data (NDF).")
        warn(f"  Check the resource type handlers in providers/azure/pricing.py")

    highlight(f"\n{divider}\n")
