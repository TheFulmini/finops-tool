# FinOps Tool

A portable, modular tool to extract cloud resource usage, map it to retail
prices, and export the results as CSV. Currently supports Azure, with
placeholders ready for AWS and GCP.

---

## Requirements

- Python 3.9 or higher
- Azure CLI installed and logged in (`az login`)

---

## First-Time Setup — Python Virtual Environment

A virtual environment keeps this project's dependencies isolated from your
system Python. Do this once, the first time you clone or download the project.

```bash
# 1. Navigate to the project folder
cd finops-tool

# 2. Create the virtual environment (creates a folder called .venv)
python3 -m venv .venv

# 3. Activate it
#    On macOS / Linux:
source .venv/bin/activate
#    On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

You will see `(.venv)` in your terminal prompt when the environment is active.

---

## Every Time You Return to the Project

You only need to re-activate the virtual environment — no need to reinstall.

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\Activate.ps1
```

---

## Azure Authentication

This tool uses your existing Azure CLI session. Before running, make sure
you are logged in:

```bash
az login
```

If you manage multiple tenants, specify the one you want:

```bash
az login --tenant <tenant-id>
```

---

## Running the Tool

```bash
# Extract live data from Azure and write to CSV
python main.py --provider azure --output costs.csv

# Extract and also generate an Excel dashboard
python main.py --provider azure --output costs.csv --dashboard dashboard.xlsx

# Target specific subscriptions only
python main.py --provider azure --output costs.csv --subscription <id1> <id2>

# Use a pre-existing CSV file instead of querying Azure
python main.py --provider azure --input existing_usage.csv --output costs_with_prices.csv

# Inventory only — skip pricing API calls
python main.py --provider azure --output inventory.csv --no-pricing

# Test with sample data (no Azure login required)
python main.py --provider azure --input data/sample_data.csv --output costs.csv --dashboard dashboard.xlsx
```

## Sample Data

A realistic sample dataset is included at `data/sample_data.csv`.
It contains 25 resources across two subscriptions (Development and Production)
covering all five supported resource types. Use it to test and explore the
tool without needing an active Azure account:

```bash
python main.py --provider azure \
               --input data/sample_data.csv \
               --output data/sample_costs.csv \
               --dashboard data/sample_dashboard.xlsx
```

---

## Configuring Resource Types

Edit `config/resources.yaml` to add or remove the Azure resource types
you want to extract. Each type must match the official Azure Resource
Manager (ARM) namespace exactly, for example:

    Microsoft.Compute/virtualMachines
    Microsoft.Storage/storageAccounts

A full list of ARM resource types can be found at:
https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-providers-and-types

---

## Project Structure

```
finops-tool/
├── providers/
│   ├── base.py              # Abstract interface all providers must implement
│   ├── azure/
│   │   ├── auth.py          # Azure CLI authentication
│   │   ├── resources.py     # Extract resources from Azure subscriptions
│   │   └── pricing.py       # Fetch Azure retail prices
│   └── aws/                 # Placeholder for future AWS support
├── core/
│   ├── extractor.py         # Orchestrates extraction across subscriptions
│   ├── pricer.py            # Maps usage data to prices
│   └── exporter.py          # CSV import / export
├── config/
│   └── resources.yaml       # Editable list of resource types to extract
├── main.py                  # CLI entry point
└── requirements.txt         # Python dependencies
```

---

## Deactivating the Virtual Environment

When you are done working on the project:

```bash
deactivate
```
