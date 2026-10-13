# Mock Azure dataset — FinOps tool QA (v2, complex)

Synthetic Azure tenant for exercising the tool **without credentials, network or a
real subscription**. Deterministic: seed `20260930`, so two runs are byte-identical
(verified). Not real tenant data; no secrets.

```bash
.venv-312/bin/python mock-azure/generate_mock_azure.py
```

## Scale

| | |
|---|---|
| Subscriptions | **8** (7 Enabled, 1 Disabled) across 2 management groups |
| Normalised rows | **394** |
| Resource types | **15** |
| Mock price filters | **607** |
| Adversarial payloads | **21** |
| Regions | 16 |

| Subscription | Env | Rows |
|---|---|---|
| Contoso Production | prod | 93 |
| Contoso Staging | stage | 62 |
| Contoso Data Platform | shared | 59 |
| Contoso Development | dev | 54 |
| Contoso Shared Services | shared | 52 |
| Contoso Sandbox | sandbox | 39 |
| Contoso Identity | identity | 36 |
| **Contoso Legacy (Cancelled)** | **Disabled** | **0 — must be skipped** |

Rows by type: VMs 131 · Storage 60 · publicIPs 54 · App Service plans 34 ·
VNets 28 · AKS 20 · SQL servers 17 · NICs 16 · VMSS 8 · **SQL databases 6** ·
KeyVault 4 · ACR 4 · Cognitive Services 4 · ML workspaces 4 · App Gateways 4.

## Artifacts

| File | Mirrors |
|---|---|
| `azure_subscriptions.json` | `SubscriptionClient.subscriptions.list()` |
| `azure_resources_raw.json` | `ResourceManagementClient.resources.list()` — raw ARM shape incl. `tags`, `zones`, `identity`, `kind`, nested Sql parents+children |
| `azure_prices.json` | retail-price `Items`, keyed by the **exact** OData filter `pricing.py` builds |
| `azure_resources_normalized.csv` | extractor output → valid `--input` CSV |
| `resources_extended.yaml` | 14-type config (shipped config has 5) |

## Confirmed-broken: nested SQL duplication (2 rows may 1)

`_list_nested_resources()` queries children **per resource group**, filtered by
**type only**, then prefixes results with the **current parent's** name. Two SQL
servers in one resource group therefore each see the other's databases.

Ground truth = 3 databases. Emitted = **6 rows**:

```
sql-prod-ecom/auditdb      sql-prod-report/auditdb     <- wrong parent
sql-prod-ecom/dwdb         sql-prod-report/dwdb        <- wrong parent
sql-prod-ecom/maindb       sql-prod-report/maindb      <- duplicate
```

`sql-prod-report/maindb` and `sql-prod-ecom/dwdb` **do not exist**. Costs are
double-counted and attributed to the wrong server.

## Adversarial payloads (21) — all land in the exported CSV

Formula/DDE: `=HYPERLINK("…"&A1,"click")` · `=cmd|'/c calc'!A1` · `=1+1+cmd|' /C calc'!A0` ·
`+HYPERLINK(…)` · `-2+3+cmd|…` · `@SUM(1+1)*cmd|…` · leading TAB · leading CR
Structural: embedded newline · comma+quote · null byte · 10 000-char name
Markup: `"><img src=x onerror=alert(1)>` · `<script>alert(1)</script>`
Deception: RTL-override `vm-‮…` (visual spoof) · Cyrillic homoglyph `vм-prod-web-01`
Injection probes: `../../../../etc/passwd` · `..\..\windows\system32\config` ·
`vm'; DROP TABLE resources;--` · `vm' UNION SELECT * FROM prices--` · `🚀`

## Data-quality traps in the price payload

| Trap | Served row | Why it matters |
|---|---|---|
| Negative price | `-1.25` for `Standard_B1s`/centralus | nothing validates sign; cost goes negative |
| Zero price | `0.0` for `Standard_D8s_v5`/eastus2 | a paid SKU silently bills $0 |
| Missing `retailPrice` | `Standard_M128s_v2`/westus3 | `.get(...,0.0)` → $0, no warning |
| String price | `"0.0846"` for `Standard_F2s_v2`/brazilsouth | `min()` over `str` vs `float` → TypeError |
| Windows vs Linux | same SKU, two metres | `_pick_best_price` takes the **lowest** → Linux price for Windows fleets (~29% under) |
| Spot + Reservation | present alongside PAYG | must be filtered; Reservation has `priceType != Consumption` |
| Conflicting duplicates | 3 rows for `Standard_E8s_v3`/uksouth | lowest wins silently; no tie-break or warning |

## Missing attributes exercised

No `hardwareProfile` (size empty) · no `sku` block · no `tags` (untagged = invisible
to showback) · missing `location` · unparseable resource ID → empty resource group ·
unknown VM SKU → NDF · region with no price rows → NDF · mixed-case `resource_type` ·
duplicate rows · resource literally named `NDF` (collides with the sentinel) ·
unpriced types (VMSS/AKS/ACR/Cognitive/ML/KeyVault/pip/NIC/AppGateway) → "Unsupported type", $0.

**Tags are collected in the raw payload but dropped entirely by the extractor** —
384 raw resources carry `costCenter`/`owner`/`environment`, and the CSV schema has
nowhere to put them. No tag means no showback or chargeback.

## Known modelling limitations (deliberate)

- Storage quantity is a hardcoded **100 GB** placeholder; VM/AppService/SQL assume
  **730 h/month**. These are assumptions displayed as estimates.
- Retail list prices only — no EA/MCA discount, reservations or Spot.
- No power state, so a deallocated VM (`vm-prod-bastion`) is billed as if running.

## Usage

```bash
python main.py --provider azure --input mock-azure/azure_resources_normalized.csv \
               --output out/mock_priced.csv
python main.py --provider azure --input mock-azure/azure_resources_normalized.csv \
               --output out/mock_noprice.csv --no-pricing
```
