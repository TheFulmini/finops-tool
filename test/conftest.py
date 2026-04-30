# tests/conftest.py
# ============================================================
# Pytest Configuration & Shared Fixtures
# ============================================================
# This file is automatically loaded by pytest before running tests.
# Define common fixtures, mocks, and test utilities here so they're
# available to all test files.
#
# Fixtures are functions that set up test data and resources.
# They're injected into test functions by name — e.g.:
#   def test_something(sample_resource):  # sample_resource is auto-provided
#       assert sample_resource["name"] == "test-vm"
# ============================================================

import pytest
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import MagicMock
import tempfile
import json

from providers.base import BaseProvider


# ── Sample Data Fixtures ───────────────────────────────────

@pytest.fixture
def sample_resource() -> Dict[str, Any]:
    """
    A single sample Azure resource for testing.
    Represents a Standard_D2s_v3 VM in eastus.
    """
    return {
        "subscription_id": "12345678-1234-1234-1234-123456789012",
        "subscription_name": "Test-Prod",
        "resource_group": "rg-test",
        "resource_name": "vm-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "location": "eastus",
        "sku": "Standard_D2s_v3",
        "size": "Standard_D2s_v3",
        "unit": "1 Hour",
        "quantity": 730.0,
        "unit_price_usd": 0.096,
        "estimated_cost_usd": 70.08,
    }


@pytest.fixture
def sample_resources(sample_resource) -> List[Dict[str, Any]]:
    """Multiple sample resources with different types."""
    return [
        sample_resource,
        {
            **sample_resource,
            "resource_name": "vm-02",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "unit_price_usd": 0.048,  # Different VM type
            "estimated_cost_usd": 35.04,
        },
        {
            "subscription_id": "12345678-1234-1234-1234-123456789012",
            "subscription_name": "Test-Prod",
            "resource_group": "rg-test",
            "resource_name": "storage-01",
            "resource_type": "Microsoft.Storage/storageAccounts",
            "location": "eastus",
            "sku": "Standard_LRS",
            "size": "",
            "unit": "1 GB/Month",
            "quantity": 100.0,
            "unit_price_usd": 0.0184,
            "estimated_cost_usd": 1.84,
        },
        {
            "subscription_id": "12345678-1234-1234-1234-123456789012",
            "subscription_name": "Test-Prod",
            "resource_group": "rg-test",
            "resource_name": "vnet-01",
            "resource_type": "Microsoft.Network/virtualNetworks",
            "location": "eastus",
            "sku": "",
            "size": "",
            "unit": "N/A",
            "quantity": 0,
            "unit_price_usd": 0.0,
            "estimated_cost_usd": 0.0,
        },
    ]


@pytest.fixture
def sample_subscriptions() -> List[Dict[str, str]]:
    """Sample list of Azure subscriptions."""
    return [
        {
            "id": "12345678-1234-1234-1234-123456789012",
            "name": "Test-Prod",
        },
        {
            "id": "87654321-4321-4321-4321-210987654321",
            "name": "Test-Dev",
        },
    ]


# ── File I/O Fixtures ──────────────────────────────────────

@pytest.fixture
def tmp_csv(tmp_path, sample_resources) -> Path:
    """
    Create a temporary CSV file with sample resources.
    Returns the Path to the CSV.
    """
    df = pd.DataFrame(sample_resources)
    csv_path = tmp_path / "test_data.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


@pytest.fixture
def tmp_json(tmp_path, sample_resources) -> Path:
    """
    Create a temporary JSON file with sample data.
    Returns the Path to the JSON file.
    """
    json_path = tmp_path / "test_data.json"
    with open(json_path, "w") as f:
        json.dump(sample_resources, f)
    return json_path


@pytest.fixture
def tmp_output_dir(tmp_path) -> Path:
    """Temporary directory for test output files."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


# ── Mock Provider Fixtures ─────────────────────────────────

@pytest.fixture
def mock_azure_credential():
    """Mock Azure credential object."""
    mock = MagicMock()
    return mock


@pytest.fixture
def mock_provider(sample_subscriptions, sample_resources) -> BaseProvider:
    """
    Mock provider that doesn't require actual Azure authentication.
    Returns fixed data for testing.
    """
    class MockProvider(BaseProvider):
        def __init__(self):
            self.authenticated = False
            self._subscriptions = sample_subscriptions
            self._resources = sample_resources

        def authenticate(self) -> None:
            self.authenticated = True

        def get_subscriptions(self) -> List[Dict[str, str]]:
            if not self.authenticated:
                raise RuntimeError("Not authenticated")
            return self._subscriptions

        def get_resources(
            self, subscription_id: str, resource_types: List[str]
        ) -> List[Dict[str, Any]]:
            if not self.authenticated:
                raise RuntimeError("Not authenticated")
            # Filter to the requested subscription and types
            return [
                r for r in self._resources
                if r["subscription_id"] == subscription_id
                and r["resource_type"] in resource_types
            ]

        def get_price(self, resource: Dict[str, Any]) -> Dict[str, Any]:
            # Return the price fields if they exist, or mock zero prices
            return {
                "unit": resource.get("unit", "1 Hour"),
                "quantity": resource.get("quantity", 730.0),
                "unit_price_usd": resource.get("unit_price_usd", 0.0),
                "estimated_cost_usd": resource.get("estimated_cost_usd", 0.0),
            }

    return MockProvider()


# ── Fixtures for specific modules ──────────────────────────

@pytest.fixture
def mock_requests_get(monkeypatch):
    """
    Mock requests.get for Azure Pricing API tests.
    Use with monkeypatch.setattr to inject into tests:
        monkeypatch.setattr("requests.get", mock_requests_get)
    """
    def mock_get(url, **kwargs):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "Items": [
                {
                    "retailPrice": 0.096,
                    "unitOfMeasure": "1 Hour",
                    "priceType": "Consumption",
                    "skuName": "Virtual Machines Standard_D2s_v3",
                }
            ],
            "NextPageLink": None,
        }
        mock_response.raise_for_status.return_value = None
        return mock_response

    return mock_get


# ── Utility fixtures ───────────────────────────────────────

@pytest.fixture
def capture_output(monkeypatch):
    """
    Capture print output for testing console functions.
    Returns a list that gets populated with each print() call.
    """
    output = []

    def mock_print(*args, **kwargs):
        output.append(" ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", mock_print)
    return output
