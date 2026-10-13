# providers/azure/resources.py
# ============================================================
# Azure Resource Extractor
# ============================================================
# Connects to each accessible subscription and lists all
# resources that match the types defined in resources.yaml.
#
# For each resource we extract:
#   - Identity fields  (subscription, resource group, name, type, location)
#   - Sizing fields    (SKU name, SKU tier, VM size) where available
#
# Note on nested resource types:
#   Types like Microsoft.Sql/servers/databases have two segments
#   after the namespace (servers AND databases). The generic
#   resources list API does NOT return these — we detect them
#   and use a dedicated sub-resource query instead.
# ============================================================

from typing import List, Dict, Any

from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.subscription import SubscriptionClient
from azure.core.exceptions import HttpResponseError

from core.console import header, success, warn, info, dim


# ── Helpers ────────────────────────────────────────────────

def _is_nested_type(resource_type: str) -> bool:
    """
    Return True if the resource type string has more than one
    segment after the namespace, e.g.:
        Microsoft.Sql/servers/databases   → True  (nested)
        Microsoft.Compute/virtualMachines → False (top-level)
    """
    # Split on '/' and count segments after the namespace prefix
    parts = resource_type.split("/")
    # parts[0] = "Microsoft.Sql", parts[1] = "servers", parts[2] = "databases"
    return len(parts) > 2


def _safe_sku(resource) -> tuple:
    """
    Safely extract SKU name and tier from a resource object.
    Many resource types have no SKU block — we return empty
    strings rather than crashing.
    """
    sku_name = ""
    sku_tier = ""
    if resource.sku:
        sku_name = resource.sku.name or ""
        sku_tier = resource.sku.tier or ""
    return sku_name, sku_tier


def _safe_size(resource) -> str:
    """
    Extract VM size from the properties bag, if present.
    Only Microsoft.Compute/virtualMachines exposes this field.
    Returns empty string for all other resource types.
    """
    try:
        # properties is an AdditionalProperties dict — not all types have it
        if resource.properties and hasattr(resource.properties, "hardware_profile"):
            return resource.properties.hardware_profile.vm_size or ""
    except Exception:
        pass
    return ""


def _parse_resource_group(resource_id: str) -> str:
    """
    Extract the resource group name from a full Azure resource ID.

    Azure resource IDs follow this pattern:
    /subscriptions/<sub>/resourceGroups/<rg>/providers/<type>/<name>

    We split on '/' and grab the segment after 'resourcegroups'.
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("resourcegroups")
        # The original (non-lowercased) ID preserves correct casing
        original_parts = resource_id.split("/")
        return original_parts[idx + 1]
    except (ValueError, IndexError):
        return ""


# ── Subscription listing ───────────────────────────────────

def list_subscriptions(credential) -> List[Dict[str, str]]:
    """
    Return all subscriptions accessible to the authenticated identity.

    Uses the SubscriptionClient to enumerate subscriptions.
    Only returns subscriptions in 'Enabled' state — skips disabled ones.

    Args:
        credential: An authenticated DefaultAzureCredential object.

    Returns:
        List of dicts: [{"id": "...", "name": "..."}, ...]
    """
    client = SubscriptionClient(credential)
    subscriptions = []

    header("[SUBSCRIPTIONS] Discovering accessible subscriptions...")

    for sub in client.subscriptions.list():
        # Skip disabled/cancelled subscriptions — they won't return resources
        if sub.state.value.lower() != "enabled":
            warn(f"  [SKIP] {sub.display_name} — state: {sub.state.value}")
            continue

        subscriptions.append({
            "id":   sub.subscription_id,
            "name": sub.display_name,
        })
        success(f"  [FOUND] {sub.display_name} ({sub.subscription_id})")

    info(f"[SUBSCRIPTIONS] Total enabled: {len(subscriptions)}\n")
    return subscriptions


# ── Top-level resource listing ─────────────────────────────

def _list_top_level_resources(
    client: ResourceManagementClient,
    subscription_id: str,
    subscription_name: str,
    resource_type: str,
) -> List[Dict[str, Any]]:
    """
    List resources of a single top-level type within a subscription.

    Uses the generic resources.list() API with an OData filter.
    This works for any type where the full path has exactly one
    segment after the provider namespace:
        Microsoft.Compute/virtualMachines   ✓
        Microsoft.Storage/storageAccounts   ✓

    Args:
        client:            ResourceManagementClient for the subscription.
        subscription_id:   Current subscription ID.
        subscription_name: Human-readable subscription name.
        resource_type:     e.g. "Microsoft.Compute/virtualMachines"

    Returns:
        List of normalised resource dicts.
    """
    results = []

    # OData filter narrows results server-side — faster than filtering locally
    filter_expr = f"resourceType eq '{resource_type}'"

    try:
        for resource in client.resources.list(filter=filter_expr, expand="createdTime,changedTime,provisioningState"):
            sku_name, sku_tier = _safe_sku(resource)
            size = _safe_size(resource)
            rg   = _parse_resource_group(resource.id)

            results.append({
                "subscription_id":   subscription_id,
                "subscription_name": subscription_name,
                "resource_group":    rg,
                "resource_name":     resource.name,
                "resource_type":     resource_type,
                "location":          resource.location or "",
                "sku":               sku_name,
                "size":              size or sku_tier,  # fallback to SKU tier
            })

    except HttpResponseError as e:
        # Some subscriptions may not have the resource provider registered
        warn(f"  [WARN] Could not list {resource_type}: {e.message}")

    return results


# ── Nested resource listing ────────────────────────────────

def _owning_parent(child_id: str, parents: List[Any]):
    """
    Return the parent resource that owns `child_id`, or None if none does.

    A child's ARM id embeds its whole ancestry, so the owner is the parent
    whose id is the longest prefix of the child's:

        parent  .../providers/Microsoft.Sql/servers/sql-prod-ecom
        child   .../providers/Microsoft.Sql/servers/sql-prod-ecom/databases/maindb

    Longest prefix rather than first match, so a deeper hierarchy still resolves
    to the closest ancestor. The comparison is case-insensitive, as ARM ids are.
    """
    child = (child_id or "").rstrip("/").lower()
    if not child:
        return None

    owner = None
    owner_len = -1
    for parent in parents:
        parent_id = (parent.id or "").rstrip("/").lower()
        if not parent_id:
            continue
        # Require a full segment boundary: ".../servers/sql-prod-ecom" must not
        # match a child of ".../servers/sql-prod-ecom-archive".
        if child.startswith(parent_id + "/") and len(parent_id) > owner_len:
            owner, owner_len = parent, len(parent_id)
    return owner


def _list_nested_resources(
    client: ResourceManagementClient,
    subscription_id: str,
    subscription_name: str,
    resource_type: str,
) -> List[Dict[str, Any]]:
    """
    List nested resources such as Microsoft.Sql/servers/databases.

    For nested types we must:
      1. First list the parent resources (e.g. SQL servers)
      2. Then list the children of each parent (e.g. databases)

    Azure's generic list API does not surface nested resources directly, and it
    cannot be scoped to a single parent: a resource-group-scoped query filtered
    by type returns *every* resource of that type in the group, whichever parent
    it hangs off. So we ask once per resource group and attribute each child to
    the parent whose ARM id prefixes the child's id.

    Asking per group rather than per parent is also fewer calls: two SQL servers
    sharing a resource group cost one child query, not two.

    Args:
        client:            ResourceManagementClient for the subscription.
        subscription_id:   Current subscription ID.
        subscription_name: Human-readable subscription name.
        resource_type:     e.g. "Microsoft.Sql/servers/databases"

    Returns:
        List of normalised resource dicts.
    """
    results = []

    # Split the type into: namespace, parent type, child type
    # e.g. "Microsoft.Sql/servers/databases"
    #       → namespace    = "Microsoft.Sql"
    #       → parent_type  = "servers"
    #       → child_type   = "databases"
    parts       = resource_type.split("/")
    namespace   = parts[0]                        # e.g. Microsoft.Sql
    parent_type = f"{namespace}/{parts[1]}"       # e.g. Microsoft.Sql/servers
    child_type  = parts[2]                        # e.g. databases

    # Step 1: list all parent resources (e.g. all SQL servers)
    parent_filter = f"resourceType eq '{parent_type}'"
    try:
        parents = list(client.resources.list(filter=parent_filter))
    except HttpResponseError as e:
        warn(f"  [WARN] Could not list parent {parent_type}: {e.message}")
        return results

    if not parents:
        return results

    # Group the parents by resource group so each group is queried exactly once.
    parents_by_rg: Dict[str, List[Any]] = {}
    for parent in parents:
        parent_rg = _parse_resource_group(parent.id)
        if not parent_rg:
            warn(f"  [WARN] Skipping {parent.name}: no resource group in its id")
            continue
        parents_by_rg.setdefault(parent_rg, []).append(parent)

    # Step 2: per resource group, list the children and attribute each one
    for parent_rg, rg_parents in parents_by_rg.items():
        try:
            children = list(client.resources.list_by_resource_group(
                resource_group_name=parent_rg,
                filter=f"resourceType eq '{resource_type}'",
                expand="createdTime",
            ))
        except HttpResponseError as e:
            warn(f"  [WARN] Could not list children in {parent_rg}: {e.message}")
            continue

        for child in children:
            owner = _owning_parent(child.id, rg_parents)
            if owner is None:
                # Never invent an attribution. A child that matches no parent in
                # this group is reported and dropped, rather than being hung off
                # whichever parent happened to be iterating.
                warn(f"  [WARN] Skipping {child.name}: no parent in {parent_rg} owns it")
                continue

            sku_name, sku_tier = _safe_sku(child)

            results.append({
                "subscription_id":   subscription_id,
                "subscription_name": subscription_name,
                "resource_group":    parent_rg,
                # The owning parent's name, e.g. "myserver/mydb"
                "resource_name":     f"{owner.name}/{child.name}",
                "resource_type":     resource_type,
                "location":          child.location or owner.location or "",
                "sku":               sku_name,
                "size":              sku_tier,
            })

    return results


# ── Public interface ───────────────────────────────────────

def get_resources(
    credential,
    subscription: Dict[str, str],
    resource_types: List[str],
) -> List[Dict[str, Any]]:
    """
    Extract all resources of the configured types from one subscription.

    This is the main entry point called by the extractor.
    It dispatches each resource type to either the top-level
    or nested listing function as appropriate.

    Args:
        credential:     An authenticated DefaultAzureCredential.
        subscription:   Dict with 'id' and 'name' keys.
        resource_types: List of resource type strings from resources.yaml.

    Returns:
        Combined list of all found resources as normalised dicts.
    """
    sub_id   = subscription["id"]
    sub_name = subscription["name"]

    # Create a resource management client scoped to this subscription
    client = ResourceManagementClient(credential, sub_id)

    all_resources = []

    header(f"[RESOURCES] Scanning subscription: {sub_name}")

    for rtype in resource_types:
        info(f"  → {rtype}")

        if _is_nested_type(rtype):
            # e.g. Microsoft.Sql/servers/databases
            found = _list_nested_resources(client, sub_id, sub_name, rtype)
        else:
            # e.g. Microsoft.Compute/virtualMachines
            found = _list_top_level_resources(client, sub_id, sub_name, rtype)

        success(f"     Found: {len(found)}")
        all_resources.extend(found)

    info(f"[RESOURCES] Total resources in {sub_name}: {len(all_resources)}\n")
    return all_resources
