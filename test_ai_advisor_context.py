#!/usr/bin/env python3
"""Pytest tests for FinOpsAdvisor._prepare_context().

These tests exercise the internal context formatting helper without calling the
Anthropic API. They run with no network access and no ANTHROPIC_API_KEY set.
"""

import pytest
from unittest.mock import Mock

from core.ai_advisor import FinOpsAdvisor


SAMPLE_COST_DATA = [
    {
        "subscription_id": "sub-prod-001",
        "subscription_name": "Production",
        "resource_group": "rg-compute",
        "resource_name": "vm-app-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "location": "westeurope",
        "sku": "NDF",
        "size": "Standard_D4s_v3",
        "unit": "1 Hour",
        "quantity": 730,
        "unit_price_usd": 0.211,
        "estimated_cost_usd": 154.03,
    },
    {
        "subscription_id": "sub-prod-001",
        "subscription_name": "Production",
        "resource_group": "rg-storage",
        "resource_name": "stproddata",
        "resource_type": "Microsoft.Storage/storageAccounts",
        "location": "westeurope",
        "sku": "Premium_LRS",
        "size": "NDF",
        "unit": "1 GB/Month",
        "quantity": 1000,
        "unit_price_usd": 0.17,
        "estimated_cost_usd": 170.00,
    },
    {
        "subscription_id": "sub-dev-002",
        "subscription_name": "Development",
        "resource_group": "rg-compute",
        "resource_name": "vm-dev-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "location": "eastus",
        "sku": "NDF",
        "size": "Standard_B2s",
        "unit": "1 Hour",
        "quantity": 730,
        "unit_price_usd": 0.0416,
        "estimated_cost_usd": 30.37,
    },
]


@pytest.fixture(autouse=True)
def _mock_anthropic_client(monkeypatch):
    """Prevent FinOpsAdvisor from instantiating a real Anthropic client."""
    monkeypatch.setattr("core.ai_advisor.anthropic.Anthropic", Mock)


def test_prepare_context_includes_resource_names():
    """All resource names from the input data appear in the generated context."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context(SAMPLE_COST_DATA)

    for name in ("vm-app-01", "stproddata", "vm-dev-01"):
        assert name in context, f"Expected resource name '{name}' in context"


def test_prepare_context_includes_subscription_names():
    """Both subscription names appear in the generated context."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context(SAMPLE_COST_DATA)

    assert "Production" in context
    assert "Development" in context


def test_prepare_context_includes_resource_count_and_total_cost():
    """The context reports the correct resource count and total monthly cost."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context(SAMPLE_COST_DATA)

    assert "Total Resources: 3" in context
    assert "$354.40" in context


def test_prepare_context_handles_empty_data():
    """_prepare_context returns a clear message when no cost data is supplied."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context([])

    assert "No cost data available" in context
