# tests/test_exporter.py
# ============================================================
# Tests for core/exporter.py
# ============================================================
# Tests CSV import/export functionality:
#   - export_csv() writes files with correct schema
#   - import_csv() reads files and validates data types
#   - NDF/0 defaults are applied correctly
#   - Round-tripping (export → import) preserves data
# ============================================================

import pytest
import pandas as pd
import os
from pathlib import Path

from core.exporter import (
    export_csv,
    import_csv,
    COLUMNS,
    TEXT_COLUMNS,
)


class TestExportCsv:
    """Tests for the export_csv() function."""

    def test_export_creates_file(self, sample_resources, tmp_output_dir):
        """export_csv should create an output file."""
        output_path = tmp_output_dir / "output.csv"
        
        export_csv(sample_resources, str(output_path))
        
        assert output_path.exists(), "Output file was not created"
        assert output_path.stat().st_size > 0, "Output file is empty"

    def test_export_preserves_all_canonical_columns(self, sample_resources, tmp_output_dir):
        """Exported CSV should contain all canonical columns."""
        output_path = tmp_output_dir / "output.csv"
        
        export_csv(sample_resources, str(output_path))
        
        df = pd.read_csv(output_path)
        for col in COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_export_correct_row_count(self, sample_resources, tmp_output_dir):
        """Exported CSV should have the same number of rows as input."""
        output_path = tmp_output_dir / "output.csv"
        
        export_csv(sample_resources, str(output_path))
        
        df = pd.read_csv(output_path)
        assert len(df) == len(sample_resources)

    def test_export_rounds_prices_to_4_decimals(self, tmp_output_dir):
        """Prices should be rounded to 4 decimal places."""
        resources = [
            {
                "subscription_id": "sub-1",
                "subscription_name": "Test",
                "resource_group": "rg-1",
                "resource_name": "res-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "Standard_D2s_v3",
                "size": "2 vCPU",
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.123456789,  # Will be rounded
                "estimated_cost_usd": 90.123456789,  # Will be rounded
            }
        ]
        
        output_path = tmp_output_dir / "output.csv"
        export_csv(resources, str(output_path))
        
        df = pd.read_csv(output_path)
        price = df["unit_price_usd"].iloc[0]
        cost = df["estimated_cost_usd"].iloc[0]
        
        assert price == 0.1235, f"Price not rounded correctly: {price}"
        # Cost should be rounded to 4 decimals
        assert len(str(cost).split(".")[-1]) <= 4, f"Cost not rounded correctly: {cost}"

    def test_export_applies_ndf_defaults(self, tmp_output_dir):
        """Missing text fields should be filled with NDF."""
        resources = [
            {
                "subscription_id": "",  # Empty text field
                "subscription_name": "Test",
                "resource_group": None,  # None
                "resource_name": "res-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "",
                "size": "2 vCPU",
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.0,  # Numeric 0 is OK
                "estimated_cost_usd": 0.0,
            }
        ]
        
        output_path = tmp_output_dir / "output.csv"
        export_csv(resources, str(output_path))
        
        df = pd.read_csv(output_path)
        # Empty/None text fields should be NDF
        assert df["subscription_id"].iloc[0] == "NDF"
        assert df["resource_group"].iloc[0] == "NDF"
        assert df["sku"].iloc[0] == "NDF"
        # Numeric fields can be 0
        assert df["unit_price_usd"].iloc[0] == 0.0

    def test_export_empty_list_does_not_create_file(self, tmp_output_dir):
        """export_csv with empty list should not create a file."""
        output_path = tmp_output_dir / "empty.csv"
        
        export_csv([], str(output_path))
        
        assert not output_path.exists(), "File should not be created for empty list"

    def test_export_handles_extra_columns(self, tmp_output_dir):
        """export_csv should preserve extra (non-canonical) columns."""
        resources = [
            {
                **{
                    "subscription_id": "sub-1",
                    "subscription_name": "Test",
                    "resource_group": "rg-1",
                    "resource_name": "res-1",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "location": "eastus",
                    "sku": "SKU",
                    "size": "2 vCPU",
                    "unit": "1 Hour",
                    "quantity": 730.0,
                    "unit_price_usd": 0.1,
                    "estimated_cost_usd": 73.0,
                },
                "custom_field": "custom_value",  # Extra column
                "another_field": 12345,  # Extra numeric column
            }
        ]
        
        output_path = tmp_output_dir / "output.csv"
        export_csv(resources, str(output_path))
        
        df = pd.read_csv(output_path)
        assert "custom_field" in df.columns
        assert "another_field" in df.columns
        assert df["custom_field"].iloc[0] == "custom_value"


class TestImportCsv:
    """Tests for the import_csv() function."""

    def test_import_reads_csv(self, tmp_csv):
        """import_csv should load data from a file."""
        resources = import_csv(str(tmp_csv))
        
        assert len(resources) > 0, "No resources loaded"
        assert isinstance(resources, list), "Should return a list"
        assert isinstance(resources[0], dict), "Each item should be a dict"

    def test_import_preserves_row_count(self, tmp_csv, sample_resources):
        """Imported CSV should have the same number of rows as exported."""
        resources = import_csv(str(tmp_csv))
        
        assert len(resources) == len(sample_resources)

    def test_import_fills_missing_columns_with_defaults(self, tmp_path):
        """import_csv should auto-fill missing canonical columns."""
        # Create a minimal CSV with only a few columns
        minimal_df = pd.DataFrame({
            "resource_name": ["vm-1"],
            "resource_type": ["Microsoft.Compute/virtualMachines"],
            "location": ["eastus"],
        })
        csv_path = tmp_path / "minimal.csv"
        minimal_df.to_csv(csv_path, index=False)
        
        resources = import_csv(str(csv_path))
        
        # Check that all canonical columns are present
        for col in COLUMNS:
            assert col in resources[0], f"Missing column: {col}"

    def test_import_converts_missing_text_to_ndf(self, tmp_path):
        """Missing text fields should be filled with NDF, not NaN."""
        minimal_df = pd.DataFrame({
            "resource_name": ["vm-1"],
            "resource_type": ["Microsoft.Compute/virtualMachines"],
            "location": ["eastus"],
        })
        csv_path = tmp_path / "minimal.csv"
        minimal_df.to_csv(csv_path, index=False)
        
        resources = import_csv(str(csv_path))
        
        # Missing text columns should be NDF
        assert resources[0]["subscription_id"] == "NDF"
        assert resources[0]["sku"] == "NDF"
        # Numeric columns should be 0
        assert resources[0]["quantity"] == 0 or resources[0]["quantity"] == "0"

    def test_import_raises_on_missing_file(self, tmp_path):
        """import_csv should raise SystemExit if file doesn't exist."""
        nonexistent = tmp_path / "does_not_exist.csv"
        
        with pytest.raises(SystemExit):
            import_csv(str(nonexistent))

    def test_import_raises_on_empty_file(self, tmp_path):
        """import_csv should raise SystemExit if file is empty."""
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("")
        
        with pytest.raises(SystemExit):
            import_csv(str(empty_csv))

    def test_import_round_trip_preserves_data(self, sample_resources, tmp_output_dir):
        """Export → import round-trip should preserve data."""
        # Export
        export_path = tmp_output_dir / "export.csv"
        export_csv(sample_resources, str(export_path))
        
        # Import
        imported = import_csv(str(export_path))
        
        # Check that key fields are preserved
        assert len(imported) == len(sample_resources)
        for i, resource in enumerate(sample_resources):
            assert imported[i]["resource_name"] == resource["resource_name"]
            assert imported[i]["resource_type"] == resource["resource_type"]
            # Price fields should be rounded but match to 4 decimals
            assert abs(float(imported[i]["estimated_cost_usd"]) - 
                      float(resource["estimated_cost_usd"])) < 0.0001

    def test_import_handles_mixed_types(self, sample_resources, tmp_output_dir):
        """import_csv should handle resources of different types."""
        export_path = tmp_output_dir / "mixed.csv"
        export_csv(sample_resources, str(export_path))
        
        imported = import_csv(str(export_path))
        
        # Check we have different resource types
        types = {r["resource_type"] for r in imported}
        assert len(types) > 1, "Should have multiple resource types"

    def test_import_with_utf8_encoding(self, sample_resources, tmp_output_dir):
        """import_csv should handle UTF-8 encoding including BOM."""
        export_path = tmp_output_dir / "utf8.csv"
        export_csv(sample_resources, str(export_path))
        
        # Verify file has BOM signature (UTF-8-sig)
        with open(export_path, "rb") as f:
            first_bytes = f.read(3)
            # UTF-8 BOM is EF BB BF
            assert first_bytes == b'\xef\xbb\xbf', "File should have UTF-8 BOM"
        
        # Import should handle it correctly
        resources = import_csv(str(export_path))
        assert len(resources) == len(sample_resources)


class TestExportImportIntegration:
    """Integration tests for export and import together."""

    def test_full_pipeline_export_import_export(self, sample_resources, tmp_output_dir):
        """Test the full cycle: data → export → import → export."""
        # First export
        path1 = tmp_output_dir / "first.csv"
        export_csv(sample_resources, str(path1))
        
        # Import
        imported = import_csv(str(path1))
        
        # Second export
        path2 = tmp_output_dir / "second.csv"
        export_csv(imported, str(path2))
        
        # Both exports should have same row count
        df1 = pd.read_csv(path1)
        df2 = pd.read_csv(path2)
        assert len(df1) == len(df2)

    def test_handles_special_characters_in_names(self, tmp_output_dir):
        """export_csv should handle special characters and quotes in resource names."""
        resources = [
            {
                "subscription_id": "sub-1",
                "subscription_name": "Test",
                "resource_group": "rg-1",
                "resource_name": 'vm-"special"-chars',  # Quotes in name
                "resource_type": "Microsoft.Compute/virtualMachines",
                "location": "eastus",
                "sku": "SKU",
                "size": "2 vCPU",
                "unit": "1 Hour",
                "quantity": 730.0,
                "unit_price_usd": 0.1,
                "estimated_cost_usd": 73.0,
            }
        ]
        
        export_path = tmp_output_dir / "special.csv"
        export_csv(resources, str(export_path))
        
        imported = import_csv(str(export_path))
        assert imported[0]["resource_name"] == 'vm-"special"-chars'
