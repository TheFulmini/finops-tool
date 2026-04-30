# tests/test_azure_pricing.py
# ============================================================
# Tests for providers/azure/pricing.py
# ============================================================
# Tests Azure pricing logic:
#   - _pick_best_price() selects the right price item
#   - Price handlers build correct OData filters
#   - Empty pricing is handled gracefully
#   - Cost calculations are correct
# ============================================================

import pytest
from unittest.mock import MagicMock, patch

from providers.azure import pricing


class TestPickBestPrice:
    """Tests for _pick_best_price() function."""

    def test_prefers_consumption_pricing(self):
        """Should prefer Consumption (PAYG) prices over others."""
        items = [
            {
                "priceType": "Spot",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.050,
            },
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.096,
            },
            {
                "priceType": "Reserved",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.070,
            },
        ]
        
        best = pricing._pick_best_price(items)
        
        assert best["priceType"] == "Consumption"
        assert best["retailPrice"] == 0.096

    def test_avoids_spot_pricing(self):
        """Should avoid Spot and Low Priority pricing."""
        items = [
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3 Spot",
                "retailPrice": 0.020,
            },
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.096,
            },
        ]
        
        best = pricing._pick_best_price(items)
        
        # Should pick the non-Spot version despite Spot being cheaper
        assert "Spot" not in best["skuName"]
        assert best["retailPrice"] == 0.096

    def test_avoids_low_priority_pricing(self):
        """Should avoid Low Priority pricing."""
        items = [
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3 Low Priority",
                "retailPrice": 0.030,
            },
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.096,
            },
        ]
        
        best = pricing._pick_best_price(items)
        
        assert "Low Priority" not in best["skuName"]

    def test_picks_lowest_price_among_candidates(self):
        """Among valid candidates, should pick the lowest price."""
        items = [
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.150,
            },
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.096,
            },
            {
                "priceType": "Consumption",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.120,
            },
        ]
        
        best = pricing._pick_best_price(items)
        
        assert best["retailPrice"] == 0.096

    def test_handles_empty_list(self):
        """Should return None for empty list."""
        result = pricing._pick_best_price([])
        
        assert result is None

    def test_falls_back_to_any_price_if_no_consumption(self):
        """Should return any price if no Consumption prices available."""
        items = [
            {
                "priceType": "Reserved",
                "skuName": "Standard_D2s_v3",
                "retailPrice": 0.070,
            }
        ]
        
        best = pricing._pick_best_price(items)
        
        assert best is not None
        assert best["retailPrice"] == 0.070


class TestPriceVirtualMachine:
    """Tests for _price_virtual_machine() function."""

    def test_prices_vm_with_valid_size_and_location(self):
        """Should price VM when size and location are provided."""
        resource = {
            "size": "Standard_D2s_v3",
            "location": "eastus",
        }
        
        # Mock the fetch function
        with patch("providers.azure.pricing._fetch_prices") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "retailPrice": 0.096,
                    "unitOfMeasure": "1 Hour",
                    "priceType": "Consumption",
                }
            ]
            
            result = pricing._price_virtual_machine(resource)
        
        assert result["unit_price_usd"] == 0.096
        assert result["quantity"] == 730.0
        assert result["estimated_cost_usd"] == 70.08  # 0.096 × 730

    def test_returns_empty_price_no_size(self):
        """Should return empty price if size is missing."""
        resource = {
            "size": "",
            "location": "eastus",
        }
        
        result = pricing._price_virtual_machine(resource)
        
        assert result["unit_price_usd"] == 0.0
        assert result["estimated_cost_usd"] == 0.0

    def test_returns_empty_price_no_location(self):
        """Should return empty price if location is missing."""
        resource = {
            "size": "Standard_D2s_v3",
            "location": "",
        }
        
        result = pricing._price_virtual_machine(resource)
        
        assert result["unit_price_usd"] == 0.0
        assert result["estimated_cost_usd"] == 0.0

    def test_estimates_730_hours_per_month(self):
        """Should use 730 hours as monthly estimate."""
        resource = {
            "size": "Standard_B1s",
            "location": "eastus",
        }
        
        with patch("providers.azure.pricing._fetch_prices") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "retailPrice": 0.010,
                    "unitOfMeasure": "1 Hour",
                    "priceType": "Consumption",
                }
            ]
            
            result = pricing._price_virtual_machine(resource)
        
        assert result["quantity"] == 730.0
        assert result["estimated_cost_usd"] == 7.30  # 0.010 × 730


class TestPriceStorageAccount:
    """Tests for _price_storage_account() function."""

    def test_prices_storage_with_sku_and_location(self):
        """Should price storage account with SKU and location."""
        resource = {
            "sku": "Standard_LRS",
            "location": "eastus",
        }
        
        with patch("providers.azure.pricing._fetch_prices") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "retailPrice": 0.0184,
                    "unitOfMeasure": "1 GB/Month",
                    "meterName": "Data Stored",
                    "priceType": "Consumption",
                }
            ]
            
            result = pricing._price_storage_account(resource)
        
        assert result["unit"] == "1 GB/Month"
        assert result["unit_price_usd"] == 0.0184
        # Default placeholder is 100 GB
        assert result["quantity"] == 100.0
        assert result["estimated_cost_usd"] == 1.84  # 0.0184 × 100

    def test_uses_100gb_placeholder(self):
        """Should use 100 GB as placeholder quantity since actual usage unknown."""
        resource = {
            "sku": "Standard_LRS",
            "location": "eastus",
        }
        
        with patch("providers.azure.pricing._fetch_prices") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "retailPrice": 0.01,
                    "unitOfMeasure": "1 GB/Month",
                    "meterName": "Data Stored",
                    "priceType": "Consumption",
                }
            ]
            
            result = pricing._price_storage_account(resource)
        
        # User is expected to update this in CSV once they know actual usage
        assert result["quantity"] == 100.0

    def test_returns_empty_price_no_location(self):
        """Should return empty price if location is missing."""
        resource = {
            "sku": "Standard_LRS",
            "location": "",
        }
        
        result = pricing._price_storage_account(resource)
        
        assert result["unit_price_usd"] == 0.0


class TestPriceVirtualNetwork:
    """Tests for _price_virtual_network() function."""

    def test_vnet_always_zero_cost(self):
        """Virtual Networks should always return zero cost."""
        resource = {
            "location": "eastus",
        }
        
        result = pricing._price_virtual_network(resource)
        
        assert result["estimated_cost_usd"] == 0.0
        assert result["quantity"] == 0
        assert "peering" in result["unit"].lower() or "N/A" in result["unit"]


class TestEmptyPrice:
    """Tests for _empty_price() function."""

    def test_returns_zero_price(self):
        """_empty_price should return all zeros."""
        result = pricing._empty_price("1 Hour")
        
        assert result["unit"] == "1 Hour"
        assert result["quantity"] == 0
        assert result["unit_price_usd"] == 0.0
        assert result["estimated_cost_usd"] == 0.0

    def test_handles_custom_unit(self):
        """Should accept and return custom unit string."""
        result = pricing._empty_price("Custom Unit")
        
        assert result["unit"] == "Custom Unit"


class TestGetPrice:
    """Tests for the main get_price() function (dispatch)."""

    def test_dispatches_to_vm_handler(self):
        """Should dispatch to VM handler for VM resources."""
        resource = {
            "resource_type": "Microsoft.Compute/virtualMachines",
            "size": "Standard_D2s_v3",
            "location": "eastus",
        }
        
        with patch("providers.azure.pricing._price_virtual_machine") as mock_handler:
            mock_handler.return_value = {
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.096,
                "estimated_cost_usd": 70.08,
            }
            
            result = pricing.get_price(resource)
        
        mock_handler.assert_called_once()
        assert result["unit_price_usd"] == 0.096

    def test_handles_unknown_resource_type(self):
        """Should return empty price for unknown resource types."""
        resource = {
            "resource_type": "Microsoft.Unknown/unknownType",
        }
        
        result = pricing.get_price(resource)
        
        assert result["unit_price_usd"] == 0.0
        assert result["estimated_cost_usd"] == 0.0

    def test_normalizes_resource_type_case(self):
        """Should normalize resource type to lowercase for matching."""
        resource = {
            "resource_type": "MICROSOFT.COMPUTE/VIRTUALMACHINES",  # Uppercase
            "size": "Standard_D2s_v3",
            "location": "eastus",
        }
        
        with patch("providers.azure.pricing._price_virtual_machine") as mock_handler:
            mock_handler.return_value = {"unit_price_usd": 0.1, "estimated_cost_usd": 73.0}
            
            result = pricing.get_price(resource)
        
        # Should still find and call the VM handler
        mock_handler.assert_called_once()


class TestPriceCaching:
    """Tests for price caching behavior."""

    def test_cache_prevents_duplicate_api_calls(self):
        """_fetch_prices should cache results to avoid duplicate API calls."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "Items": [{"retailPrice": 0.1}],
                "NextPageLink": None,
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            # Clear the cache
            pricing._price_cache.clear()
            
            # Make the same call twice
            filter_expr = "serviceName eq 'Virtual Machines'"
            pricing._fetch_prices(filter_expr)
            pricing._fetch_prices(filter_expr)
            
            # Should only call API once (second call uses cache)
            assert mock_get.call_count == 1
