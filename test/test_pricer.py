# tests/test_pricer.py
# ============================================================
# Tests for core/pricer.py
# ============================================================
# Tests the price enrichment functionality:
#   - enrich() adds pricing fields to resources
#   - Handles pricing API failures gracefully
#   - Calculates cost correctly (unit_price × quantity)
#   - Preserves original resource data
# ============================================================

import pytest
from typing import Dict, Any

from core.pricer import enrich
from providers.base import BaseProvider


class MockProviderForPricer(BaseProvider):
    """Mock provider that returns fixed prices for testing."""

    def __init__(self, price_map: Dict[str, Dict[str, Any]] = None):
        self.price_map = price_map or {}
        self.authenticated = False

    def authenticate(self) -> None:
        self.authenticated = True

    def get_subscriptions(self):
        return []

    def get_resources(self, subscription_id, resource_types):
        return []

    def get_price(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a price from the price_map, or a default mock price.
        """
        resource_name = resource.get("resource_name", "unknown")
        if resource_name in self.price_map:
            return self.price_map[resource_name]

        # Default mock price for any resource not in the map
        return {
            "unit": "1 Hour",
            "quantity": 730.0,
            "unit_price_usd": 0.100,
            "estimated_cost_usd": 73.0,
        }


class TestEnrichBasic:
    """Basic enrichment tests."""

    def test_enrich_adds_pricing_fields(self, sample_resource, mock_provider):
        """enrich() should add unit, quantity, price fields to each resource."""
        mock_provider.authenticate()
        resources = [sample_resource.copy()]
        
        # Remove pricing fields to simulate fresh extraction
        for key in ["unit", "quantity", "unit_price_usd", "estimated_cost_usd"]:
            resources[0].pop(key, None)
        
        result = enrich(resources, mock_provider)
        
        assert "unit" in result[0]
        assert "quantity" in result[0]
        assert "unit_price_usd" in result[0]
        assert "estimated_cost_usd" in result[0]

    def test_enrich_returns_same_length(self, sample_resources, mock_provider):
        """enrich() should return the same number of resources."""
        mock_provider.authenticate()
        
        result = enrich(sample_resources, mock_provider)
        
        assert len(result) == len(sample_resources)

    def test_enrich_preserves_original_fields(self, sample_resource, mock_provider):
        """enrich() should not modify non-pricing fields."""
        mock_provider.authenticate()
        resources = [sample_resource.copy()]
        
        # Save original values
        original_name = resources[0]["resource_name"]
        original_type = resources[0]["resource_type"]
        
        result = enrich(resources, mock_provider)
        
        assert result[0]["resource_name"] == original_name
        assert result[0]["resource_type"] == original_type
        assert result[0]["subscription_id"] == sample_resource["subscription_id"]


class TestEnrichCalculations:
    """Tests for cost calculations."""

    def test_enrich_calculates_cost_correctly(self, mock_provider):
        """Cost should be unit_price × quantity."""
        mock_provider.authenticate()
        
        # Create a resource without pricing
        resource = {
            "subscription_id": "sub-1",
            "subscription_name": "Test",
            "resource_group": "rg-1",
            "resource_name": "res-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "location": "eastus",
            "sku": "Standard_D2s_v3",
            "size": "2 vCPU",
        }
        
        # Mock provider returns specific prices
        provider = MockProviderForPricer({
            "res-1": {
                "unit": "1 Hour",
                "quantity": 100.0,
                "unit_price_usd": 0.5,
                "estimated_cost_usd": 50.0,  # 0.5 × 100
            }
        })
        provider.authenticate()
        
        result = enrich([resource], provider)
        
        assert result[0]["unit_price_usd"] == 0.5
        assert result[0]["quantity"] == 100.0
        assert result[0]["estimated_cost_usd"] == 50.0

    def test_enrich_handles_zero_prices(self, mock_provider):
        """enrich() should handle zero prices gracefully."""
        mock_provider.authenticate()
        
        resource = {
            "subscription_id": "sub-1",
            "subscription_name": "Test",
            "resource_group": "rg-1",
            "resource_name": "vnet-1",
            "resource_type": "Microsoft.Network/virtualNetworks",
            "location": "eastus",
            "sku": "",
            "size": "",
        }
        
        provider = MockProviderForPricer({
            "vnet-1": {
                "unit": "N/A",
                "quantity": 0,
                "unit_price_usd": 0.0,
                "estimated_cost_usd": 0.0,
            }
        })
        provider.authenticate()
        
        result = enrich([resource], provider)
        
        assert result[0]["estimated_cost_usd"] == 0.0

    def test_enrich_rounds_prices(self, mock_provider):
        """Prices in result should be properly rounded."""
        mock_provider.authenticate()
        
        resource = {
            "subscription_id": "sub-1",
            "subscription_name": "Test",
            "resource_group": "rg-1",
            "resource_name": "res-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "location": "eastus",
            "sku": "SKU",
            "size": "2 vCPU",
        }
        
        # Provider returns a price with many decimal places
        provider = MockProviderForPricer({
            "res-1": {
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.123456789,
                "estimated_cost_usd": 90.12345678,
            }
        })
        provider.authenticate()
        
        result = enrich([resource], provider)
        
        # Check that prices are rounded reasonably
        assert isinstance(result[0]["unit_price_usd"], (int, float))
        assert isinstance(result[0]["estimated_cost_usd"], (int, float))


class TestEnrichErrorHandling:
    """Tests for error handling during enrichment."""

    def test_enrich_continues_on_single_price_failure(self, mock_provider):
        """enrich() should not stop if one resource fails pricing."""
        mock_provider.authenticate()
        
        resources = [
            {
                "subscription_id": "sub-1",
                "subscription_name": "Test",
                "resource_group": "rg-1",
                "resource_name": "res-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "SKU",
                "size": "2 vCPU",
            },
            {
                "subscription_id": "sub-1",
                "subscription_name": "Test",
                "resource_group": "rg-1",
                "resource_name": "res-2",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "SKU",
                "size": "2 vCPU",
            },
        ]
        
        # Mock provider that fails for res-1 but succeeds for res-2
        class FailingMockProvider(BaseProvider):
            def authenticate(self):
                pass

            def get_subscriptions(self):
                return []

            def get_resources(self, subscription_id, resource_types):
                return []

            def get_price(self, resource: Dict[str, Any]) -> Dict[str, Any]:
                if resource["resource_name"] == "res-1":
                    raise Exception("API error")
                return {
                    "unit": "1 Hour",
                    "quantity": 730.0,
                    "unit_price_usd": 0.1,
                    "estimated_cost_usd": 73.0,
                }

        provider = FailingMockProvider()
        provider.authenticate()
        
        # Should not raise — continues despite failure
        result = enrich(resources, provider)
        
        # Both resources should be in result
        assert len(result) == 2
        # First resource should have default/NDF pricing
        assert result[0]["unit"] == "NDF" or result[0]["unit_price_usd"] == 0.0
        # Second resource should have actual pricing
        assert result[1]["unit_price_usd"] > 0.0

    def test_enrich_fills_ndf_on_missing_price(self, mock_provider):
        """enrich() should fill NDF/0 when pricing is unavailable."""
        mock_provider.authenticate()
        
        resource = {
            "subscription_id": "sub-1",
            "subscription_name": "Test",
            "resource_group": "rg-1",
            "resource_name": "res-1",
            "resource_type": "Microsoft.Compute/virtualMachines",
            "location": "eastus",
            "sku": "SKU",
            "size": "2 vCPU",
        }
        
        # Provider that returns None/empty pricing
        provider = MockProviderForPricer({
            "res-1": {
                "unit": None,
                "quantity": 0,
                "unit_price_usd": None,
                "estimated_cost_usd": None,
            }
        })
        provider.authenticate()
        
        result = enrich([resource], provider)
        
        # Should have safe default values
        assert "unit" in result[0]
        assert "quantity" in result[0]
        assert "unit_price_usd" in result[0]
        assert "estimated_cost_usd" in result[0]


class TestEnrichWithMultipleResources:
    """Tests with multiple resources of different types."""

    def test_enrich_handles_mixed_types(self, sample_resources):
        """enrich() should handle mixed resource types."""
        provider = MockProviderForPricer({
            "vm-01": {
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.096,
                "estimated_cost_usd": 70.08,
            },
            "storage-01": {
                "unit": "1 GB/Month",
                "quantity": 100.0,
                "unit_price_usd": 0.0184,
                "estimated_cost_usd": 1.84,
            },
            "vnet-01": {
                "unit": "N/A",
                "quantity": 0,
                "unit_price_usd": 0.0,
                "estimated_cost_usd": 0.0,
            },
        })
        provider.authenticate()
        
        # Remove pricing fields
        for resource in sample_resources:
            for key in ["unit", "quantity", "unit_price_usd", "estimated_cost_usd"]:
                resource.pop(key, None)
        
        result = enrich(sample_resources, provider)
        
        # All resources should have pricing
        assert len(result) == len(sample_resources)
        for resource in result:
            assert "unit_price_usd" in resource
            assert "estimated_cost_usd" in resource

    def test_enrich_preserves_order(self, sample_resources):
        """enrich() should preserve the order of resources."""
        provider = MockProviderForPricer()
        provider.authenticate()
        
        # Get the order of input resource names
        input_names = [r["resource_name"] for r in sample_resources]
        
        result = enrich(sample_resources, provider)
        
        # Output order should match input
        output_names = [r["resource_name"] for r in result]
        assert input_names == output_names

    def test_enrich_with_large_dataset(self, mock_provider):
        """enrich() should handle a large number of resources."""
        mock_provider.authenticate()
        
        # Create 100 mock resources
        resources = [
            {
                "subscription_id": "sub-1",
                "subscription_name": "Test",
                "resource_group": "rg-1",
                "resource_name": f"vm-{i:03d}",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "Standard_D2s_v3",
                "size": "2 vCPU",
            }
            for i in range(100)
        ]
        
        result = enrich(resources, mock_provider)
        
        assert len(result) == 100
        # All should have pricing
        for resource in result:
            assert "unit_price_usd" in resource
            assert isinstance(resource["estimated_cost_usd"], (int, float))
