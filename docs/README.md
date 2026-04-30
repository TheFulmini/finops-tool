# finops-tool

> A modular Azure cost extraction and pricing pipeline that queries live subscriptions or re-prices an existing CSV, enriches each resource with Azure Retail Prices API data, and exports the result as CSV with an optional Excel dashboard and AI cost recommendations.

---

## 1. Overview

- Extracts cloud resources from Azure subscriptions (or re-prices an existing CSV) and maps them to current retail prices in USD.
- Designed for FinOps practitioners and cloud engineers who need repeatable, scriptable cost visibility without portal access.
- **Stack**: Python 3.9+, Azure SDK (`azure-identity`, `azure-mgmt-resource`, `azure-mgmt-subscription`), `pandas`, `openpyxl`, `requests`, `pyyaml`, `colorama`, `anthropic`.
- **Architecture**: A linear pipeline — `main.py` drives five interchangeable stages (auth → extract → price → export → dashboard/AI) through a provider-abstracted interface. Only the Azure provider is implemented; AWS/GCP stubs are placeholders.

---

## 2. Components

### `main.py`
- **Purpose**: CLI entry point and pipeline orchestrator.
- **Location**: [`main.py`](../main.py)
- **Key exports**: `main()`, `parse_args()`, `_get_provider_registry()`
- **Dependencies**: All core modules + provider registry.
- **Notes**: `_get_provider_registry()` lazy-loads provider classes so that missing SDKs don't crash the import. AI Advisor hooks exist in the file but are commented out (pending integration).

### `core/console.py`
- **Purpose**: Centralised colorama wrappers so all modules share consistent terminal output styles.
- **Location**: [`core/console.py`](../core/console.py)
- **Key exports**: `header()`, `success()`, `warn()`, `error()`, `info()`, `dim()`, `highlight()`, `item()`
- **Dependencies**: `colorama`

### `core/extractor.py`
- **Purpose**: Reads `resources.yaml`, iterates over subscriptions and resource types, and returns a flat list of resource dicts.
- **Location**: [`core/extractor.py`](../core/extractor.py)
- **Key exports**: `extract(provider, config_path, subscription_ids)`, `load_resource_types(config_path)`
- **Dependencies**: `BaseProvider`, `pyyaml`, `core/console.py`

### `core/pricer.py`
- **Purpose**: Enriches each resource dict with pricing fields by calling `provider.get_price()`.
- **Location**: [`core/pricer.py`](../core/pricer.py)
- **Key exports**: `enrich(resources, provider)`
- **Dependencies**: `BaseProvider`, `core/console.py`
- **Notes**: Individual pricing failures are swallowed; resources default to `unit="NDF"` and zero numeric fields rather than halting the pipeline.

### `core/exporter.py`
- **Purpose**: Reads and writes CSVs with an enforced 12-column canonical schema.
- **Location**: [`core/exporter.py`](../core/exporter.py)
- **Key exports**: `export_csv(resources, output_path)`, `import_csv(input_path)`
- **Dependencies**: `pandas`, `core/console.py`
- **Notes**: Writes UTF-8-sig BOM for Excel compatibility. `NDF` fills empty text columns; `0` fills empty numeric columns. `import_csv` reads everything as strings first to prevent pandas type-inference corruption, then normalises.

### `core/dashboard.py`
- **Purpose**: Generates a 3-sheet Excel workbook (Summary, By Location, Raw Data) from a cost CSV.
- **Location**: [`core/dashboard.py`](../core/dashboard.py)
- **Key exports**: `generate(input_csv, output_xlsx)`
- **Dependencies**: `openpyxl`, `pandas`
- **Notes**: No Excel installation required. All charts (bar, pie) are built with openpyxl's charting API.

### `core/ai_advisor.py`
- **Purpose**: Sends a structured cost summary to the Claude API and parses JSON recommendations.
- **Location**: [`core/ai_advisor.py`](../core/ai_advisor.py)
- **Key exports**: `FinOpsAdvisor` class
- **Dependencies**: `anthropic`, `ANTHROPIC_API_KEY` environment variable
- **Notes**: Uses `claude-sonnet-4-20250514` with `max_tokens=4096`. Returns a dict with `recommendations`, `total_potential_savings`, and `summary`. The hook in `main.py` that calls this class is currently commented out.

### `providers/base.py`
- **Purpose**: Abstract base class (`BaseProvider`) that all cloud providers must implement.
- **Location**: [`providers/base.py`](../providers/base.py)
- **Key exports**: `BaseProvider` (ABC with `authenticate`, `get_subscriptions`, `get_resources`, `get_price`)
- **Notes**: Core modules import only `BaseProvider`; no provider-specific SDK ever leaks into core logic.

### `providers/azure/`
- **Purpose**: Concrete Azure implementation of `BaseProvider`.
- **Location**: [`providers/azure/`](../providers/azure/)
- **Key exports**: `AzureProvider`
- **Sub-modules**:
  - `auth.py` — `get_credential()`: returns `DefaultAzureCredential` (requires `az login` locally).
  - `resources.py` — `get_resources()`, `list_subscriptions()`: handles both top-level and nested resource types.
  - `pricing.py` — `get_price()`: hits the [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) with per-type OData filters; session-level in-memory cache.
- **Supported resource types**: `virtualMachines`, `storageAccounts`, `servers/databases`, `serverFarms`, `virtualNetworks`.

### `config/resources.yaml`
- **Purpose**: User-editable list of Azure resource types to extract.
- **Location**: [`config/resources.yaml`](../config/resources.yaml)
- **Notes**: Comment/uncomment lines to add or remove resource types. Future type additions also require a matching handler in `providers/azure/pricing.py`.

### `test/`
- **Purpose**: Pytest suite covering exporter round-trips, Azure resource extraction, pricing, and AI advisor logic.
- **Location**: [`test/`](../test/)
- **Key fixtures** (in `conftest.py`): `sample_resources`, `mock_provider`, `mock_requests_get`, `tmp_csv`.
- **Notes**: Root-level `test_ai_advisor_*.py` files are separate from the `test/` package and must be run directly with `python`.

---

## 3. Usage Guide

### Installation

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd finops-tool

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Live extraction only) Authenticate to Azure
az login
```

### Running

```bash
# Live extraction from Azure
python main.py --provider azure --output costs.csv

# Live extraction + Excel dashboard
python main.py --provider azure --output costs.csv --dashboard dashboard.xlsx

# Re-price an existing CSV (no Azure auth needed)
python main.py --provider azure --input data/sample_data.csv --output repriced.csv

# Inventory only — skip pricing
python main.py --provider azure --output inventory.csv --no-pricing

# Scope to specific subscriptions
python main.py --provider azure --output costs.csv --subscription sub-id-1 sub-id-2

# Custom resource type config
python main.py --provider azure --output costs.csv --config path/to/resources.yaml
```

### Examples

**Test locally with sample data (no Azure subscription required)**

```bash
python main.py \
  --provider azure \
  --input data/sample_data.csv \
  --output costs.csv \
  --dashboard dashboard.xlsx
```

**Run the test suite**

```bash
pytest test/

# AI advisor tests (run separately — they live at root level)
python test_ai_advisor_complete.py
python test_analyze_costs_integration.py
```

**Use the AI Advisor programmatically**

```python
import os
from core.ai_advisor import FinOpsAdvisor
from core.exporter import import_csv

os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."

resources = import_csv("costs.csv")
advisor = FinOpsAdvisor()
result = advisor.analyze_costs(resources)

print(result["summary"])
for rec in result["recommendations"]:
    print(rec["resource"], rec["estimated_savings"])
```

---

## 4. Configuration

| Option / Variable | Type | Default | Description |
|---|---|---|---|
| `--provider` | CLI flag | *(required)* | Cloud provider. Only `azure` is implemented. |
| `--output` | CLI flag | `output.csv` | Path for the output CSV. |
| `--input` | CLI flag | `None` | Path to an existing CSV to re-price instead of doing live extraction. |
| `--subscription` | CLI flag | `None` (all) | One or more subscription IDs to scope extraction. |
| `--config` | CLI flag | `config/resources.yaml` | Path to a custom resource-type config YAML. |
| `--no-pricing` | CLI flag | `False` | Skip pricing enrichment; export inventory only. |
| `--dashboard` | CLI flag | `None` | If set, generate an Excel dashboard at this path. |
| `ANTHROPIC_API_KEY` | Env var | *(required for AI)* | API key for the Claude AI Advisor. |
| `config/resources.yaml` | YAML file | 5 Azure types | List of resource types to extract. Comment lines to disable. |

<!-- TODO: default value for --output not confirmed in source — verify parse_args() -->

---

## 5. Missing Elements

### Gaps found

- [ ] AI Advisor not wired into the main pipeline — hooks in `main.py` are commented out; no `--advisor` CLI flag exists.
- [ ] `pytest` and `unittest.mock` are not in `requirements.txt` — developers must install them manually.
- [ ] Root-level AI advisor test files (`test_ai_advisor_*.py`) are not discovered by `pytest test/` — no `pytest.ini` or `pyproject.toml` to configure test paths.
- [ ] No CI/CD configuration (`.github/workflows/`, `Dockerfile`, etc.).
- [ ] `providers/aws/` directory exists but contains no implementation — placeholder only.
- [ ] `pricing.py` uses a hardcoded placeholder quantity (100 GB) for storage accounts; there is no way to pass actual usage data.
- [ ] `_price_virtual_network()` always returns zero — VNet peering and gateway costs are silently excluded with no warning to the user.
- [ ] No `--version` flag or version metadata anywhere in the project.
