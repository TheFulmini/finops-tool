# core/extractor.py
# ============================================================
# Resource Extractor — Orchestration Layer
# ============================================================
# This module is the main orchestrator for the live extraction
# path (as opposed to loading from an existing CSV).
#
# It:
#   1. Reads the configured resource types from resources.yaml
#   2. Calls the provider to list all accessible subscriptions
#   3. For each subscription, extracts resources of every
#      configured type
#   4. Returns a flat list of all resource dicts ready to be
#      enriched with pricing by pricer.py
#
# This module is provider-agnostic — it only calls methods
# defined in BaseProvider and never imports Azure directly.
# ============================================================

import yaml
import os
from typing import List, Dict, Any

from providers.base import BaseProvider
from core.console import header, success, warn, error, info, dim


# Default path to the resource type config file.
# Can be overridden when calling extract().
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__),   # core/
    "..",                         # project root
    "config",
    "resources.yaml",
)


def load_resource_types(config_path: str = DEFAULT_CONFIG_PATH) -> List[str]:
    """
    Read the list of resource types to extract from resources.yaml.

    Strips whitespace and skips any empty entries so the YAML
    can be freely edited without causing downstream errors.

    Args:
        config_path: Path to the YAML config file.

    Returns:
        List of resource type strings, e.g.:
        ["Microsoft.Compute/virtualMachines", "Microsoft.Storage/storageAccounts"]

    Raises:
        SystemExit: If the file cannot be read or parsed.
    """
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Pull out the 'resources' list and clean it up
        raw = config.get("resources", [])
        types = [r.strip() for r in raw if r and r.strip()]

        if not types:
            print("[CONFIG] Warning: no resource types found in resources.yaml.")
            print("[CONFIG] Check that the file has entries under the 'resources' key.")

        header(f"[CONFIG] Loaded {len(types)} resource type(s) from {config_path}")
        for t in types:
            dim(f"  • {t}")
        print()

        return types

    except FileNotFoundError:
        error(f"[CONFIG] Config file not found: {config_path}")
        raise SystemExit(1)
    except yaml.YAMLError as e:
        error(f"[CONFIG] Failed to parse resources.yaml: {e}")
        raise SystemExit(1)


def extract(
    provider: BaseProvider,
    config_path: str = DEFAULT_CONFIG_PATH,
    subscription_ids: List[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run a full live extraction across all (or selected) subscriptions.

    Steps:
      1. Load resource types from config
      2. Discover subscriptions via the provider
      3. For each subscription, call provider.get_resources()
      4. Collect and return all results as a flat list

    Args:
        provider:         An authenticated BaseProvider instance.
        config_path:      Path to resources.yaml (optional override).
        subscription_ids: Optional list of specific subscription IDs to
                          target. If None or empty, all enabled
                          subscriptions are processed.

    Returns:
        Flat list of resource dicts. Each dict has the keys defined
        in BaseProvider.get_resources():
            subscription_id, subscription_name, resource_group,
            resource_name, resource_type, location, sku, size
    """
    # Step 1: load the configured resource types
    resource_types = load_resource_types(config_path)

    # Step 2: discover subscriptions
    all_subscriptions = provider.get_subscriptions()

    if not all_subscriptions:
        warn("[EXTRACTOR] No enabled subscriptions found. Exiting.")
        return []

    # Step 3: filter to specific subscriptions if requested
    if subscription_ids:
        # Normalise to lowercase for case-insensitive comparison
        target_ids = {sid.lower() for sid in subscription_ids}
        subscriptions = [
            s for s in all_subscriptions
            if s["id"].lower() in target_ids
        ]
        if not subscriptions:
            error(f"[EXTRACTOR] None of the requested subscription IDs were found.")
            error(f"[EXTRACTOR] Requested: {subscription_ids}")
            return []
        info(f"[EXTRACTOR] Targeting {len(subscriptions)} of "
             f"{len(all_subscriptions)} subscription(s).\n")
    else:
        # Process all subscriptions
        subscriptions = all_subscriptions
        info(f"[EXTRACTOR] Processing all {len(subscriptions)} subscription(s).\n")

    # Step 4: extract resources from each subscription
    all_resources = []

    for i, sub in enumerate(subscriptions, start=1):
        header(f"[EXTRACTOR] [{i}/{len(subscriptions)}] {sub['name']} ({sub['id']})")

        resources = provider.get_resources(sub["id"], resource_types)
        all_resources.extend(resources)

    # Summary
    success(f"\n[EXTRACTOR] Extraction complete.")
    success(f"[EXTRACTOR] Total resources found: {len(all_resources)}\n")

    return all_resources
