# main.py
# ============================================================
# FinOps Tool — CLI Entry Point
# ============================================================
# This is the single file you run. It:
#   1. Parses CLI arguments
#   2. Selects and initialises the correct cloud provider
#   3. Either extracts live data OR loads an existing CSV
#   4. Enriches the data with retail pricing
#   5. Writes the result to a CSV file
#
# Usage examples:
#
#   # Full live extraction from Azure (all subscriptions)
#   python main.py --provider azure --output costs.csv
#
#   # Target a specific subscription
#   python main.py --provider azure --output costs.csv \
#                  --subscription <subscription-id>
#
#   # Re-price an existing CSV (no cloud API calls for resources)
#   python main.py --provider azure --input existing.csv \
#                  --output repriced.csv
#
#   # Use a custom resource type config
#   python main.py --provider azure --output costs.csv \
#                  --config path/to/my_resources.yaml
# ============================================================

import argparse
import sys
import os
from datetime import datetime

from core.console import header, success, error, info, dim, highlight
from core import extractor, pricer, exporter, dashboard


# ── Provider registry ──────────────────────────────────────
# Maps the --provider flag value to its provider class.
# To add a new provider: import its class and add an entry here.

def _get_provider_registry():
    """
    Lazily build the provider registry to avoid importing providers
    that aren't installed (e.g. boto3 for AWS won't be present yet).
    """
    registry = {}

    # Azure
    try:
        from providers.azure.provider import AzureProvider
        registry["azure"] = AzureProvider
    except ImportError as e:
        # Azure SDK not installed — listed as unavailable
        registry["azure"] = None

    # AWS (placeholder — uncomment when implemented)
    # try:
    #     from providers.aws.provider import AWSProvider
    #     registry["aws"] = AWSProvider
    # except ImportError:
    #     registry["aws"] = None

    return registry


# ── Argument parsing ───────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """
    Define and parse all command-line arguments.

    Returns:
        Parsed argparse.Namespace object.
    """
    parser = argparse.ArgumentParser(
        prog="finops-tool",
        description=(
            "Extract cloud resource usage, map to retail prices, "
            "and export to CSV."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --provider azure --output costs.csv
  python main.py --provider azure --output costs.csv --subscription <id>
  python main.py --provider azure --input existing.csv --output repriced.csv
        """,
    )

    # Required: which cloud provider to use
    parser.add_argument(
        "--provider",
        required=True,
        choices=["azure"],   # Expand as new providers are added
        help="Cloud provider to use (currently: azure).",
    )

    # Output file path — required unless you just want a dry run (future feature)
    parser.add_argument(
        "--output",
        required=True,
        metavar="FILE",
        help="Path for the output CSV file (e.g. costs.csv).",
    )

    # Optional: load usage data from an existing CSV instead of querying the cloud
    parser.add_argument(
        "--input",
        metavar="FILE",
        default=None,
        help=(
            "Path to an existing CSV file to use as the source of resource data. "
            "When provided, the tool skips the live extraction and only fetches "
            "updated prices for the resources already in the file."
        ),
    )

    # Optional: limit extraction to one or more specific subscriptions
    parser.add_argument(
        "--subscription",
        metavar="ID",
        nargs="+",   # Accept one or more subscription IDs
        default=None,
        help=(
            "One or more subscription IDs to target. "
            "If omitted, all enabled subscriptions are processed. "
            "Example: --subscription abc-123 def-456"
        ),
    )

    # Optional: override the default resources.yaml location
    parser.add_argument(
        "--config",
        metavar="FILE",
        default=None,
        help=(
            "Path to a custom resource type config YAML file. "
            "Defaults to config/resources.yaml."
        ),
    )

    # Optional: skip pricing (extract resources only, no API pricing calls)
    parser.add_argument(
        "--no-pricing",
        action="store_true",
        default=False,
        help=(
            "Extract resources but skip the pricing step. "
            "Useful for a quick inventory run. "
            "Price columns will be written as NDF."
        ),
    )

    # Optional: also generate an Excel dashboard from the output CSV
    parser.add_argument(
        "--dashboard",
        metavar="FILE",
        default=None,
        help=(
            "Path for an optional Excel dashboard file (e.g. dashboard.xlsx). "
            "Generated automatically after the CSV is written."
        ),
    )

    return parser.parse_args()


# ── Banner ─────────────────────────────────────────────────

def print_banner(provider_name: str, args: argparse.Namespace) -> None:
    """Print a startup banner summarising what the tool is about to do."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    highlight("\n╔══════════════════════════════════════════════╗")
    highlight(  "║           FinOps Tool — Cost Extractor       ║")
    highlight(  "╚══════════════════════════════════════════════╝\n")

    dim(f"  Started:   {now}")
    dim(f"  Provider:  {provider_name.upper()}")

    if args.input:
        dim(f"  Mode:      Re-price existing CSV")
        dim(f"  Input:     {args.input}")
    else:
        dim(f"  Mode:      Live extraction")
        if args.subscription:
            dim(f"  Subs:      {', '.join(args.subscription)}")
        else:
            dim(f"  Subs:      All enabled subscriptions")

    dim(f"  Output:    {args.output}")
    dim(f"  Pricing:   {'Disabled (--no-pricing)' if args.no_pricing else 'Enabled'}")
    dim(f"  Dashboard: {args.dashboard if args.dashboard else 'Disabled'}")
    print()


# ── Main flow ──────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # ── 1. Resolve provider ────────────────────────────────
    registry = _get_provider_registry()

    if args.provider not in registry or registry[args.provider] is None:
        error(f"[MAIN] Provider '{args.provider}' is not available.")
        error(f"[MAIN] Make sure the required SDK is installed.")
        error(f"[MAIN] Run: pip install -r requirements.txt")
        sys.exit(1)

    ProviderClass = registry[args.provider]
    provider      = ProviderClass()

    print_banner(args.provider, args)

    # ── 2. Authenticate ────────────────────────────────────
    # Always authenticate — even for the CSV import path, because
    # pricing may need to call the provider's pricing API.
    header("[MAIN] Authenticating...")
    provider.authenticate()
    print()

    # ── 3. Get resource data ───────────────────────────────
    if args.input:
        # --- Path A: Load from existing CSV ---
        header(f"[MAIN] Loading resources from: {args.input}")
        resources = exporter.import_csv(args.input)

    else:
        # --- Path B: Live extraction from the cloud ---
        header("[MAIN] Starting live resource extraction...")

        # Resolve config path — use provided or default
        config_path = args.config or os.path.join(
            os.path.dirname(__file__), "config", "resources.yaml"
        )

        resources = extractor.extract(
            provider         = provider,
            config_path      = config_path,
            subscription_ids = args.subscription,
        )

    if not resources:
        warn("[MAIN] No resources found. Nothing to export.")
        sys.exit(0)

    info(f"[MAIN] {len(resources)} resource(s) ready for pricing.\n")

    # ── 4. Enrich with pricing ─────────────────────────────
    if args.no_pricing:
        warn("[MAIN] Pricing skipped (--no-pricing flag set).")
        # Fill price columns with NDF so the CSV schema is consistent
        for r in resources:
            r.setdefault("unit",               "NDF")
            r.setdefault("quantity",           0)
            r.setdefault("unit_price_usd",     0.0)
            r.setdefault("estimated_cost_usd", 0.0)
    else:
        header("[MAIN] Fetching retail prices...")
        resources = pricer.enrich(resources, provider)

    # ── 5. Export to CSV ───────────────────────────────────
    header("[MAIN] Exporting to CSV...")
    exporter.export_csv(resources, args.output)

    # ── 6. Generate Excel dashboard (optional) ─────────────
    if args.dashboard:
        header("[MAIN] Generating Excel dashboard...")
        dashboard.generate(args.output, args.dashboard)

    success("[MAIN] All done.\n")


# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    main()
