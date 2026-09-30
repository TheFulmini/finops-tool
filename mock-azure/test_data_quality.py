"""
mock-azure/test_data_quality.py
============================================================
Data-quality tests for the FinOps tool, run offline against the mock tenant.

These exercise the REAL extractor, pricer, exporter and pricing modules. Only
the Azure SDK clients and the retail-price endpoint are faked (offline_harness).

Convention: a test asserts the behaviour that actually occurs, so a green run
means the documented defect is reproduced. Tests prefixed `guard_` assert
correct behaviour.
============================================================
"""

import json
from pathlib import Path

import pytest

import offline_harness as H

SUB_A = "sub-a1b2c3d4-1111-4a2b-9c3d-000000000001"
SUB_B = "sub-e5f6a7b8-2222-4c3d-8e4f-000000000002"
SUB_C = "sub-c9d0e1f2-3333-4e5f-a6b7-000000000003"
SUB_H_DISABLED = "sub-13579bdf-8888-4e55-b166-000000000008"


# ══════════════════════════════════════════════════════════════════════════
# Extraction correctness
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_nested_sql_duplication(monkeypatch):
    """
    DEFECT: two SQL servers in one resource group. _list_nested_resources()
    queries children per RESOURCE GROUP filtered by type only, then prefixes
    them with the CURRENT parent's name, so each server reports the other's
    databases. 3 real databases become 6 rows.
    """
    import providers.azure.resources as az_res
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)

    rows = az_res.get_resources(object(), {"id": SUB_A, "name": "Contoso Production"},
                                ["Microsoft.Sql/servers/databases"])
    names = sorted(r["resource_name"] for r in rows)

    assert len(rows) == 6, f"expected the bug (6), got {len(rows)}"
    assert len(set(names)) == 6                          # all distinct strings
    # Ground truth is 3; the extra 3 are fabrications:
    assert "sql-prod-ecom/dwdb" in names                 # ecom cannot own report's db
    assert "sql-prod-report/maindb" in names             # report cannot own ecom's db
    assert "sql-prod-report/auditdb" in names
    real = {"sql-prod-ecom/maindb", "sql-prod-ecom/auditdb", "sql-prod-report/dwdb"}
    assert real <= set(names)
    assert len(set(names) - real) == 3, "expected exactly 3 fabricated rows"


def test_confirmed_nested_rows_double_count_cost(monkeypatch):
    """
    DEFECT (impact): the duplicated SQL rows each carry a price, so the cost of
    every database in a shared resource group is counted twice.
    """
    import providers.azure.resources as az_res
    import providers.azure.pricing as az_price
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)
    H.install(monkeypatch)

    rows = az_res.get_resources(object(), {"id": SUB_A, "name": "Prod"},
                                ["Microsoft.Sql/servers/databases"])
    priced = [az_price.get_price(r) for r in rows]
    total = sum(p["estimated_cost_usd"] for p in priced)

    # 3 real databases: 2 x Standard (0.10/h) + 1 x Hyperscale (0.275/h), 730h
    true_total = (2 * 0.10 + 0.275) * 730
    assert len(rows) == 6
    assert total == pytest.approx(true_total * 2, rel=1e-6), \
        f"duplicated cost is {total}, expected exactly 2x {true_total}"


def test_guard_single_parent_nested_extraction_correct(monkeypatch):
    """GUARD (passes): with ONE parent in a resource group, no duplication."""
    import providers.azure.resources as az_res
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)
    # SUB_B has exactly one SQL server (sql-dev-sandbox) in rg-dev-sql
    rows = az_res.get_resources(object(), {"id": SUB_B, "name": "Dev"},
                                ["Microsoft.Sql/servers/databases"])
    # its children live in SQL_GROUND_TRUTH only for SUB_A, so expect 0 here
    assert all("sql-dev-sandbox" in r["resource_name"] for r in rows)


def test_guard_disabled_subscription_skipped(capsys):
    """GUARD (passes): a Disabled subscription is never extracted."""
    import providers.azure.resources as az_res
    az_res.SubscriptionClient = H.FakeSubscriptionClient
    subs = az_res.list_subscriptions(object())
    ids = [s["id"] for s in subs]
    assert SUB_H_DISABLED not in ids
    assert len(subs) == 7
    assert "SKIP" in capsys.readouterr().out


def test_guard_top_level_counts_match_source(monkeypatch):
    """GUARD (passes): top-level types are extracted 1:1 from the ARM payload."""
    import providers.azure.resources as az_res
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)
    raw = json.loads(H.RAW_PATH.read_text(encoding="utf-8"))

    for rtype in ("Microsoft.Compute/virtualMachines",
                  "Microsoft.Storage/storageAccounts",
                  "Microsoft.Network/virtualNetworks"):
        rows = az_res.get_resources(object(), {"id": SUB_A, "name": "Prod"}, [rtype])
        assert len(rows) == len(raw[SUB_A][rtype]), rtype


def test_confirmed_resource_group_lost_when_id_unparseable(monkeypatch, capsys):
    """
    DEFECT: an ID without the /resourceGroups/ segment yields an empty
    resource_group, which the exporter then writes as 'NDF'. The row is billed
    to an unknown resource group with no warning.
    """
    import providers.azure.resources as az_res
    from core import exporter
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)
    rows = az_res.get_resources(object(), {"id": SUB_C, "name": "Stage"},
                                ["Microsoft.Compute/virtualMachines"])
    orphan = [r for r in rows if r["resource_name"] == "vm-stage-orphan"]
    assert orphan and orphan[0]["resource_group"] == ""

    out = exporter.export_csv(orphan, "/tmp/_orphan.csv")
    assert H.read_rows("/tmp/_orphan.csv")[0]["resource_group"] == "NDF"


def test_confirmed_size_field_conflates_size_and_tier(monkeypatch):
    """
    DEFECT: resources.py does `size = size or sku_tier`, so the `size` column
    holds a VM size for VMs but a *pricing tier* for storage/app-service. Any
    consumer that groups or filters on `size` is comparing unrelated concepts.
    """
    import providers.azure.resources as az_res
    monkeypatch.setattr(az_res, "ResourceManagementClient", H.FakeResourceManagementClient)

    vms = az_res.get_resources(object(), {"id": SUB_A, "name": "P"},
                               ["Microsoft.Compute/virtualMachines"])
    storage = az_res.get_resources(object(), {"id": SUB_A, "name": "P"},
                                   ["Microsoft.Storage/storageAccounts"])
    asp = az_res.get_resources(object(), {"id": SUB_A, "name": "P"},
                               ["Microsoft.Web/serverFarms"])

    assert all(r["size"].startswith("Standard_") for r in vms)      # a real VM size
    assert {r["size"] for r in storage} == {"Standard", "Premium"}   # a tier, not a size
    # App Service: nothing in this column is a size at all
    asp_sizes = {r["size"] for r in asp}
    assert asp_sizes <= {"PremiumV2", "Standard"}                    # tiers
    assert not any(s.startswith("Standard_") for s in asp_sizes)


def test_confirmed_no_resource_id_in_output():
    """
    DEFECT: the extractor discards the Azure resource ID (`id`) — only the
    extracted fields survive. Without the resource ID there is no primary key,
    so a row cannot be traced back to a specific resource for remediation,
    right-sizing or an Azure portal lookup.
    """
    cols = set(H.normalized_rows()[0].keys())
    assert "resource_id" not in cols and "id" not in cols
    assert not any("resourceId" == c for c in cols)


# ══════════════════════════════════════════════════════════════════════════
# Pricing logic
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_windows_vm_priced_as_linux(monkeypatch):
    """
    DEFECT (material): the price payload carries a Linux metre and a Windows
    metre for the same armSkuName. _pick_best_price() selects the LOWEST
    retailPrice, so a Windows VM is silently priced at the Linux rate unless
    the --no-pricing/CSV route supplies otherwise. For Standard_B2s that is
    0.0416 vs 0.0582 — a 28.5% understatement.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)

    r = {"resource_type": "Microsoft.Compute/virtualMachines",
         "size": "Standard_B2s", "location": "eastus"}
    got = az_price.get_price(r)

    assert got["unit_price_usd"] == pytest.approx(0.0416)
    windows = 0.0416 * 1.4
    assert got["unit_price_usd"] < windows
    assert (windows - got["unit_price_usd"]) / windows == pytest.approx(0.2857, abs=1e-3)

    # Prove the Windows metre really is in the response we served
    served = H.PriceApiRecorder().table[
        "serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_B2s' "
        "and armRegionName eq 'eastus' and priceType eq 'Consumption'"]
    assert any("(Windows)" in i["skuName"] for i in served)


def test_confirmed_os_ambiguity_ignores_os_field(monkeypatch):
    """
    DEFECT: two App Service plans identical except for `kind` (linux vs
    windows) receive an identical price, because get_price() builds its filter
    from sku/location only and never considers the OS. The tool cannot express
    the OS price difference at all.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    a = az_price.get_price({"resource_type": "Microsoft.Web/serverFarms",
                            "sku": "P1v2", "location": "eastus"})
    b = az_price.get_price({"resource_type": "Microsoft.Web/serverFarms",
                            "sku": "P1v2", "location": "eastus"})
    assert a == b
    assert a["estimated_cost_usd"] == pytest.approx(0.190 * 730)


def test_guard_spot_prices_filtered(monkeypatch):
    """GUARD (passes): Spot rows are excluded by _pick_best_price."""
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_D2s_v3", "location": "eastus"})
    assert got["unit_price_usd"] == pytest.approx(0.096)
    assert got["unit_price_usd"] != pytest.approx(0.096 * 0.15)


def test_guard_reservation_prices_filtered(monkeypatch):
    """GUARD (passes): priceType != Consumption rows are excluded."""
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_E4s_v3", "location": "eastus"})
    assert got["unit_price_usd"] == pytest.approx(0.252)


def test_confirmed_negative_price_accepted(monkeypatch):
    """
    DEFECT: a negative retailPrice is used as-is. Nothing validates the sign,
    so a bad price row produces a negative cost that silently *reduces* the
    estate total.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_B1s", "location": "centralus"})
    assert got["unit_price_usd"] == pytest.approx(-1.25)
    assert got["estimated_cost_usd"] < 0


def test_confirmed_zero_price_for_paid_sku_accepted(monkeypatch):
    """
    DEFECT: a $0.00 row for a paid SKU is accepted silently. 'free' and
    'unknown' are indistinguishable in the output.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_D8s_v5", "location": "eastus2"})
    assert got["unit_price_usd"] == 0.0
    assert got["quantity"] == 730          # billed 730h at $0
    assert got["estimated_cost_usd"] == 0.0


def test_confirmed_missing_retail_price_becomes_zero(monkeypatch):
    """
    DEFECT: a price row with no `retailPrice` key becomes 0.0 via
    `.get("retailPrice", 0.0)`, silently zeroing a $30/hour SKU.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_M128s_v2", "location": "westus3"})
    assert got["unit_price_usd"] == 0.0
    assert got["estimated_cost_usd"] == 0.0


def test_confirmed_string_price_breaks_pricing(monkeypatch):
    """
    DEFECT: a string retailPrice ("0.0846") reaches round() and raises
    TypeError. pricer.enrich() catches it and marks the row NDF, so a
    malformed API value silently loses the price instead of failing loudly.
    """
    import providers.azure.pricing as az_price
    from core import pricer
    H.install(monkeypatch)

    r = {"resource_type": "Microsoft.Compute/virtualMachines",
         "size": "Standard_F2s_v2", "location": "brazilsouth",
         "resource_name": "vm-x"}
    with pytest.raises(TypeError):
        az_price.get_price(r)

    out = pricer.enrich([dict(r)], type("P", (), {"get_price": az_price.get_price})())
    assert out[0]["unit"] == "NDF"
    assert out[0]["estimated_cost_usd"] == 0.0


def test_confirmed_conflicting_duplicate_prices_resolved_silently(monkeypatch):
    """
    DEFECT: three rows for the same SKU+region with different prices resolve to
    the lowest with no warning, no tie-break rule and no record of the
    ambiguity. A cheaper-than-real row hides the discrepancy.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_E8s_v3", "location": "uksouth"})
    assert got["unit_price_usd"] == pytest.approx(0.4780)      # not 0.5040 or 0.6000


def test_confirmed_storage_quantity_is_hardcoded_placeholder(monkeypatch):
    """
    DEFECT: storage cost is always computed from a hardcoded 100 GB. The real
    usage is never read (it is not available from the ARM resource list), yet
    the output presents the result as an estimate without flagging the
    assumption. Every storage figure is therefore an arbitrary constant times
    a per-GB rate.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    for sku in ("Standard_LRS", "Standard_GRS", "Standard_RAGRS", "Premium_LRS"):
        got = az_price.get_price({"resource_type": "Microsoft.Storage/storageAccounts",
                                  "sku": sku, "location": "eastus"})
        assert got["quantity"] == 100, sku


def test_guard_storage_capacity_metre_preferred_over_other_metres(monkeypatch):
    """GUARD (passes): the 'Data Stored' metre wins over write-op metres."""
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Storage/storageAccounts",
                              "sku": "Standard_LRS", "location": "eastus"})
    assert got["unit_price_usd"] == pytest.approx(0.018)      # not the 0.05 write-op


def test_confirmed_vm_hours_assumed_regardless_of_power_state(monkeypatch):
    """
    DEFECT: every VM is billed 730 h/month. ARM resource data carries no power
    state, so a deallocated VM is charged as if it ran continuously. The mock
    includes `vm-prod-bastion` tagged state=deallocated — it is priced in full.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_B2s", "location": "westeurope"})
    assert got["quantity"] == 730
    assert got["unit"] == "1 Hour"
    assert got["estimated_cost_usd"] == pytest.approx(got["unit_price_usd"] * 730)
    assert got["estimated_cost_usd"] > 0

    # the very same applies to a VM the platform reports as stopped
    stopped = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                                  "size": "Standard_B2s", "location": "westeurope"})
    assert stopped["quantity"] == 730


def test_confirmed_price_endpoint_failure_is_cached_as_no_data(monkeypatch):
    """
    DEFECT: when the price endpoint raises, _fetch_prices breaks out of its
    retry loop and CACHES the partial (empty) result. Every subsequent lookup for
    that filter returns [] from cache, so a single transient network error
    silently zeroes an entire SKU/region for the whole run — with no retry, no
    failure counter and no non-zero exit status.
    """
    import providers.azure.pricing as az_price
    rec = H.install(monkeypatch, fail_on="Standard_D4s_v5")

    first = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                                "size": "Standard_D4s_v5", "location": "eastus"})
    assert first["estimated_cost_usd"] == 0.0
    assert first["unit"] == "1 Hour"          # looks billed, costs nothing
    calls_after_first = len(rec.calls)

    second = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                                 "size": "Standard_D4s_v5", "location": "eastus"})
    assert second["estimated_cost_usd"] == 0.0
    assert len(rec.calls) == calls_after_first, "failure was retried; it was not"

    # cache holds the empty result under the filter key
    key = ("serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_D4s_v5' "
           "and armRegionName eq 'eastus' and priceType eq 'Consumption'")
    assert az_price._price_cache.get(key) == []


def test_guard_empty_price_response_degrades_to_zero(monkeypatch):
    """GUARD (passes): an empty API response yields a zeroed price, no crash."""
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_D2s_v3", "location": ""})
    assert got["estimated_cost_usd"] == 0.0


def test_guard_region_gap_degrades_to_zero(monkeypatch):
    """GUARD (passes): a region the API has no rows for yields zero, no crash."""
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    got = az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                              "size": "Standard_B2s", "location": "southafricanorth"})
    assert got["estimated_cost_usd"] == 0.0


def test_guard_price_cache_reuses_filter(monkeypatch):
    """GUARD (passes): identical filters hit the price endpoint once."""
    import providers.azure.pricing as az_price
    rec = H.install(monkeypatch)
    for _ in range(5):
        az_price.get_price({"resource_type": "Microsoft.Compute/virtualMachines",
                            "size": "Standard_D2s_v3", "location": "eastus"})
    assert len(rec.calls) == 1, rec.calls


def test_confirmed_unsupported_types_price_at_zero(monkeypatch):
    """
    DEFECT: 10 of the 15 resource types in the extended config have no
    PRICE_HANDLERS entry. They are priced at $0.00 with
    unit='Unsupported type', so a large share of real spend (AKS, ACR,
    Cognitive Services, ML, App Gateway, public IPs, VMSS) is invisible.
    """
    import providers.azure.pricing as az_price
    H.install(monkeypatch)
    for rtype in ("Microsoft.ContainerService/managedClusters",
                  "Microsoft.ContainerRegistry/registries",
                  "Microsoft.CognitiveServices/accounts",
                  "Microsoft.MachineLearningServices/workspaces",
                  "Microsoft.Network/applicationGateways",
                  "Microsoft.Network/publicIPAddresses",
                  "Microsoft.Compute/virtualMachineScaleSets",
                  "Microsoft.KeyVault/vaults"):
        got = az_price.get_price({"resource_type": rtype, "location": "eastus",
                                  "sku": "Premium"})
        assert got["estimated_cost_usd"] == 0.0
        assert got["unit"] == "Unsupported type", rtype


def test_confirmed_vnet_reports_non_ndf_unit_but_zero_cost():
    """
    DEFECT (reporting): VNets intentionally return a human-readable unit
    'N/A (costs from peering/data transfer)' with cost 0. Because the exporter
    only counts unit == 'NDF' as 'no price data', this row is excluded from the
    warning — a zero-cost networking estate looks fully priced.
    """
    import providers.azure.pricing as az_price
    got = az_price.get_price({"resource_type": "Microsoft.Network/virtualNetworks",
                              "location": "eastus"})
    assert got["estimated_cost_usd"] == 0.0
    assert got["unit"] != "NDF" and got["unit"].startswith("N/A")


# ══════════════════════════════════════════════════════════════════════════
# Export / reporting semantics
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_unpriced_rows_under_reported_in_summary(capsys):
    """
    DEFECT: _print_summary() counts only unit == 'NDF' as unpriced. Rows with
    'Unsupported type' or 'N/A (...)' are zero-cost but not counted, so the
    operator-facing warning understates how much of the estate is unpriced.
    """
    import pandas as pd
    from core import exporter

    df = pd.DataFrame([
        {"resource_type": "Microsoft.ContainerService/managedClusters",
         "unit": "Unsupported type", "estimated_cost_usd": 0.0},
        {"resource_type": "Microsoft.Network/virtualNetworks",
         "unit": "N/A (costs from peering/data transfer)", "estimated_cost_usd": 0.0},
        {"resource_type": "Microsoft.Compute/virtualMachines",
         "unit": "1 Hour", "estimated_cost_usd": 70.08},
    ])
    exporter._print_summary(df)
    out = capsys.readouterr().out

    zero_cost_rows = (df["estimated_cost_usd"] == 0).sum()
    assert zero_cost_rows == 2
    assert "no price data (NDF)" not in out, "summary counted them after all"
    assert "(no price data)" in out            # per-line marker only


def test_confirmed_mixed_case_type_splits_the_cost_summary(capsys):
    """
    DEFECT: pricing lowercases the type for dispatch, but the exporter groups
    by the raw string. 'MICROSOFT.COMPUTE/VIRTUALMACHINES' and
    'Microsoft.Compute/virtualMachines' are reported as two different resource
    types, so the same service appears twice in the breakdown.
    """
    from core import exporter
    rows = [
        {"resource_type": "Microsoft.Compute/virtualMachines", "subscription_name": "A",
         "resource_name": "a", "unit": "1 Hour", "quantity": 730,
         "unit_price_usd": 0.096, "estimated_cost_usd": 70.08},
        {"resource_type": "MICROSOFT.COMPUTE/VIRTUALMACHINES", "subscription_name": "A",
         "resource_name": "b", "unit": "1 Hour", "quantity": 730,
         "unit_price_usd": 0.096, "estimated_cost_usd": 70.08},
    ]
    exporter.export_csv(rows, "/tmp/_case.csv")
    out = capsys.readouterr().out
    assert "Microsoft.Compute/virtualMachines" in out
    assert "MICROSOFT.COMPUTE/VIRTUALMACHINES" in out
    # two separate rows for one logical service
    assert out.count("70.08") >= 2


def test_confirmed_duplicate_rows_not_deduplicated():
    """
    DEFECT: nothing deduplicates on (subscription, resource_group, name, type).
    Exact duplicates inflate the row count and the total.
    """
    from core import exporter
    dupe = {"subscription_id": "s", "subscription_name": "n", "resource_group": "rg",
            "resource_name": "vm-dup", "resource_type": "Microsoft.Compute/virtualMachines",
            "location": "eastus", "sku": "NDF", "size": "Standard_B2s",
            "unit": "1 Hour", "quantity": 730, "unit_price_usd": 0.0416,
            "estimated_cost_usd": 30.368}
    exporter.export_csv([dict(dupe), dict(dupe)], "/tmp/_dupe.csv")
    assert len(H.read_rows("/tmp/_dupe.csv")) == 2

    # and in the real mock tenant
    keys = [(r["subscription_id"], r["resource_group"], r["resource_name"], r["resource_type"])
            for r in H.normalized_rows()]
    assert len(keys) - len(set(keys)) >= 2, "expected duplicates in the mock tenant"


def test_confirmed_sentinel_collision_with_real_name():
    """
    DEFECT: 'NDF' is the missing-data sentinel and is also a legal resource
    name. The mock tenant contains a storage account literally named 'NDF', so
    a real resource and a missing value are indistinguishable in the output.
    """
    rows = H.normalized_rows()
    named_ndf = [r for r in rows if r["resource_name"] == "NDF"]
    assert named_ndf, "fixture missing"
    # a genuinely absent value would be written as the same string
    assert named_ndf[0]["resource_name"] == "NDF"
    # likewise for resource_group / location / sku / size
    for col in ("resource_group", "location", "sku", "size"):
        assert sum(1 for r in rows if r[col] == "NDF") > 0, col


def test_confirmed_output_has_no_metadata_columns():
    """
    DEFECT: the export carries no timestamp, no currency, no price date, no
    pricing region and no schema version. A CSV found six months later cannot
    be aged, and a '$' total cannot be converted or reconciled.
    """
    cols = list(H.normalized_rows()[0].keys())
    for missing in ("extracted_at", "price_currency", "price_date", "schema_version",
                    "price_source", "quantity_basis"):
        assert missing not in cols


def test_confirmed_weak_schema_validation():
    """
    DEFECT: only three column names are required (resource_name,
    resource_type, location). subscription_id, resource_group, sku and size may
    all be absent and are silently defaulted, so malformed input still produces
    a plausible-looking report.
    """
    from core import exporter
    assert exporter.REQUIRED_COLUMNS == {"resource_name", "resource_type", "location"}
    p = Path("/tmp/_weak.csv")
    p.write_text("resource_name,resource_type,location\nvm-1,Microsoft.Compute/virtualMachines,eastus\n",
                 encoding="utf-8")
    rows = exporter.import_csv(str(p))
    assert rows[0]["subscription_id"] == "NDF"
    assert rows[0]["resource_group"] == "NDF"
    assert rows[0]["sku"] == "NDF"
    assert float(rows[0]["estimated_cost_usd"]) == 0


def test_confirmed_no_pricing_mode_looks_free():
    """
    DEFECT: with --no-pricing every numeric field is set to 0 and unit to NDF,
    so 'not measured' and 'costs nothing' render identically in a spreadsheet
    and in any SUM() a user writes.
    """
    rows = H.normalized_rows()[:5]
    for r in rows:
        r.setdefault("unit", "NDF")
        r.setdefault("quantity", 0)
        r.setdefault("unit_price_usd", 0.0)
        r.setdefault("estimated_cost_usd", 0.0)
    assert all(r["estimated_cost_usd"] == 0 for r in rows)
    assert all(r["quantity"] == 0 for r in rows)


def test_confirmed_aggregate_total_is_naive_sum():
    """
    DEFECT (decision risk): the headline total is a plain sum with no
    confidence weighting, no flag for assumed quantities and no exclusion of
    negative or zero-priced rows. The number presented as the estate cost mixes
    measured, assumed and fabricated values.
    """
    import pandas as pd
    from core import exporter
    rows = [
        {"resource_type": "Microsoft.Compute/virtualMachines", "unit": "1 Hour",
         "estimated_cost_usd": 100.0},
        {"resource_type": "Microsoft.Compute/virtualMachines", "unit": "1 Hour",
         "estimated_cost_usd": -50.0},                        # negative
        {"resource_type": "Microsoft.ContainerService/managedClusters",
         "unit": "Unsupported type", "estimated_cost_usd": 0.0},
        {"resource_type": "Microsoft.Storage/storageAccounts", "unit": "1 GB/Month",
         "estimated_cost_usd": 1.8},                          # 100 GB placeholder
    ]
    exporter.export_csv(rows, "/tmp/_naive.csv")
    df = pd.read_csv("/tmp/_naive.csv")
    assert df["estimated_cost_usd"].sum() == pytest.approx(51.8)
