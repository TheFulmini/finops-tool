# tests/test_azure_resources.py
# ============================================================
# Tests for providers/azure/resources.py
# ============================================================
# Tests Azure resource extraction helpers:
#   - _is_nested_type() correctly identifies nested types
#   - _parse_resource_group() extracts RG from resource IDs
#   - _safe_sku() handles missing SKU gracefully
#   - _safe_size() extracts VM sizes correctly
# ============================================================

import pytest
from unittest.mock import MagicMock

from providers.azure import resources


class TestIsNestedType:
    """Tests for _is_nested_type() function."""

    def test_identifies_top_level_types(self):
        """Top-level resource types should return False."""
        top_level_types = [
            "Microsoft.Compute/virtualMachines",
            "Microsoft.Storage/storageAccounts",
            "Microsoft.Network/virtualNetworks",
            "Microsoft.Web/serverfarms",
        ]
        
        for rtype in top_level_types:
            assert not resources._is_nested_type(rtype), \
                f"{rtype} should be detected as top-level"

    def test_identifies_nested_types(self):
        """Nested resource types should return True."""
        nested_types = [
            "Microsoft.Sql/servers/databases",
            "Microsoft.Sql/servers/elasticPools",
            # Microsoft.Authorization/roleAssignments has only 2 path segments
            # (Provider/Type) — it is a top-level resource, not nested.
            "Microsoft.Network/virtualNetworks/subnets",
        ]
        
        for rtype in nested_types:
            assert resources._is_nested_type(rtype), \
                f"{rtype} should be detected as nested"

    def test_handles_malformed_types(self):
        """Should handle edge cases gracefully."""
        # Single segment (no /)
        assert not resources._is_nested_type("InvalidType")
        # Empty string
        assert not resources._is_nested_type("")


class TestParseResourceGroup:
    """Tests for _parse_resource_group() function."""

    def test_parses_standard_resource_id(self):
        """Should extract resource group name from standard Azure resource ID."""
        resource_id = "/subscriptions/12345/resourceGroups/my-rg/providers/Microsoft.Compute/virtualMachines/vm-1"
        
        rg = resources._parse_resource_group(resource_id)
        
        assert rg == "my-rg"

    def test_handles_case_insensitivity(self):
        """Should handle 'resourcegroups' in any case."""
        resource_id = "/subscriptions/12345/ResourceGroups/MY-RG/providers/Microsoft.Compute/virtualMachines/vm-1"
        
        rg = resources._parse_resource_group(resource_id)
        
        # Should preserve original casing from input
        assert rg == "MY-RG"

    def test_handles_rg_with_special_characters(self):
        """Should handle resource group names with special characters."""
        resource_id = "/subscriptions/12345/resourceGroups/rg-test_prod.123/providers/Microsoft.Compute/virtualMachines/vm-1"
        
        rg = resources._parse_resource_group(resource_id)
        
        assert rg == "rg-test_prod.123"

    def test_returns_empty_string_on_invalid_id(self):
        """Should return empty string if resourceGroups not found in ID."""
        invalid_id = "/subscriptions/12345/providers/Microsoft.Storage/storageAccounts/myaccount"
        
        rg = resources._parse_resource_group(invalid_id)
        
        assert rg == ""

    def test_handles_empty_string(self):
        """Should handle empty input gracefully."""
        rg = resources._parse_resource_group("")
        
        assert rg == ""


class TestSafeSku:
    """Tests for _safe_sku() function."""

    def test_extracts_sku_name_and_tier(self):
        """Should extract both name and tier from resource SKU."""
        mock_resource = MagicMock()
        mock_resource.sku.name = "Standard_LRS"
        mock_resource.sku.tier = "Standard"
        
        name, tier = resources._safe_sku(mock_resource)
        
        assert name == "Standard_LRS"
        assert tier == "Standard"

    def test_handles_missing_sku(self):
        """Should return empty strings if SKU is None."""
        mock_resource = MagicMock()
        mock_resource.sku = None
        
        name, tier = resources._safe_sku(mock_resource)
        
        assert name == ""
        assert tier == ""

    def test_handles_none_name_and_tier(self):
        """Should return empty strings if name/tier are None."""
        mock_resource = MagicMock()
        mock_resource.sku.name = None
        mock_resource.sku.tier = None
        
        name, tier = resources._safe_sku(mock_resource)
        
        assert name == ""
        assert tier == ""

    def test_handles_missing_tier(self):
        """Should handle when only tier is missing."""
        mock_resource = MagicMock()
        mock_resource.sku.name = "Standard_D2s_v3"
        mock_resource.sku.tier = None
        
        name, tier = resources._safe_sku(mock_resource)
        
        assert name == "Standard_D2s_v3"
        assert tier == ""


class TestSafeSize:
    """Tests for _safe_size() function."""

    def test_extracts_vm_size(self):
        """Should extract VM size from hardware profile."""
        mock_resource = MagicMock()
        mock_resource.properties.hardware_profile.vm_size = "Standard_D2s_v3"
        
        size = resources._safe_size(mock_resource)
        
        assert size == "Standard_D2s_v3"

    def test_returns_empty_string_no_properties(self):
        """Should return empty string if properties don't exist."""
        mock_resource = MagicMock()
        mock_resource.properties = None
        
        size = resources._safe_size(mock_resource)
        
        assert size == ""

    def test_returns_empty_string_no_hardware_profile(self):
        """Should return empty string if hardware_profile doesn't exist."""
        mock_resource = MagicMock()
        mock_resource.properties = MagicMock(spec=[])  # No hardware_profile attr
        
        size = resources._safe_size(mock_resource)
        
        assert size == ""

    def test_handles_exception_gracefully(self):
        """Should return empty string if any exception occurs."""
        mock_resource = MagicMock()
        mock_resource.properties = MagicMock()
        mock_resource.properties.hardware_profile = MagicMock()
        mock_resource.properties.hardware_profile.vm_size = None
        
        size = resources._safe_size(mock_resource)
        
        assert size == ""


class TestResourceTypeFormatting:
    """Integration tests for resource type handling."""

    def test_nested_type_parsing(self):
        """Test parsing of a realistic nested type."""
        nested_type = "Microsoft.Sql/servers/databases"
        
        parts = nested_type.split("/")
        assert parts[0] == "Microsoft.Sql"
        assert parts[1] == "servers"
        assert parts[2] == "databases"
        assert len(parts) == 3
        
        # Verify is_nested_type catches it
        assert resources._is_nested_type(nested_type)

    def test_top_level_type_parsing(self):
        """Test parsing of a realistic top-level type."""
        top_level_type = "Microsoft.Compute/virtualMachines"
        
        parts = top_level_type.split("/")
        assert parts[0] == "Microsoft.Compute"
        assert parts[1] == "virtualMachines"
        assert len(parts) == 2
        
        # Verify is_nested_type doesn't catch it
        assert not resources._is_nested_type(top_level_type)
