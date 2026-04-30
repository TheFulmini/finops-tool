#!/usr/bin/env python3
"""
Complete test suite for FinOpsAdvisor module.

Run with:
  python test_ai_advisor_complete.py
"""

import json
from core.ai_advisor import FinOpsAdvisor

# Sample test data
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
        "estimated_cost_usd": 154.03
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
        "estimated_cost_usd": 170.00
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
        "estimated_cost_usd": 30.37
    }
]

class MockMessageContent:
    """Mock Claude's message response."""
    def __init__(self, json_text):
        self.text = json_text

# ─────────────────────────────────────────────────────────────
# TEST 1: _prepare_context()
# ─────────────────────────────────────────────────────────────

def test_prepare_context_basic():
    """Test that _prepare_context generates readable summary."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context(SAMPLE_COST_DATA)

    # Assertions
    assert "COST ANALYSIS SUMMARY" in context, "Missing header"
    assert "Production" in context, "Missing subscription name"
    assert "Total Monthly Cost:" in context, "Missing total cost"
    assert "Total Resources: 3" in context, "Wrong resource count"

    print("✅ TEST 1 PASSED: _prepare_context() generates proper summary")
    print(f"   Generated {len(context)} character summary\n")

def test_prepare_context_empty():
    """Test _prepare_context with empty data."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context([])

    assert "No cost data available" in context, "Should handle empty data"

    print("✅ TEST 2 PASSED: _prepare_context() handles empty data\n")

def test_prepare_context_includes_aggregates():
    """Test that context includes cost aggregations."""
    advisor = FinOpsAdvisor()
    context = advisor._prepare_context(SAMPLE_COST_DATA)

    # Check for aggregated values - check for total cost
    total = sum(r["estimated_cost_usd"] for r in SAMPLE_COST_DATA)
    assert f"${total:,.2f}" in context, f"Should include total cost ${total:,.2f}"
    assert "virtualMachines" in context or "Compute" in context, "Should include resource type breakdown"

    print("✅ TEST 3 PASSED: _prepare_context() includes aggregates\n")

# ─────────────────────────────────────────────────────────────
# TEST 2: _parse_recommendations()
# ─────────────────────────────────────────────────────────────

def test_parse_recommendations_valid_json():
    """Test parsing valid JSON recommendations."""
    advisor = FinOpsAdvisor()

    # Valid response
    json_response = json.dumps([
        {
            "resource": "vm-app-01",
            "current_monthly_cost": 154.03,
            "estimated_savings": 50.00,
            "savings_percentage": 32.4,
            "business_risk": "Low",
            "priority": "Quick Win",
            "implementation_steps": ["Resize to Standard_D2s_v3", "Test in staging"],
            "action_items": ["Update VM size", "Monitor performance"]
        }
    ])

    mock_content = [MockMessageContent(json_response)]
    result = advisor._parse_recommendations(mock_content)

    assert result["success"] == True, "Should succeed with valid JSON"
    assert len(result["recommendations"]) == 1, "Should parse single recommendation"
    assert result["total_potential_savings"] == 50.00, "Should calculate total savings"

    print("✅ TEST 4 PASSED: _parse_recommendations() parses valid JSON\n")

def test_parse_recommendations_multiple():
    """Test parsing multiple recommendations."""
    advisor = FinOpsAdvisor()

    json_response = json.dumps([
        {
            "resource": "vm-app-01",
            "current_monthly_cost": 154.03,
            "estimated_savings": 50.00,
            "savings_percentage": 32.4,
            "business_risk": "Low",
            "priority": "Quick Win",
            "implementation_steps": ["Resize VM"],
            "action_items": []
        },
        {
            "resource": "stproddata",
            "current_monthly_cost": 170.00,
            "estimated_savings": 75.00,
            "savings_percentage": 44.1,
            "business_risk": "Medium",
            "priority": "Strategic",
            "implementation_steps": ["Move to Standard tier", "Monitor costs"],
            "action_items": []
        }
    ])

    mock_content = [MockMessageContent(json_response)]
    result = advisor._parse_recommendations(mock_content)

    assert len(result["recommendations"]) == 2, "Should parse 2 recommendations"
    assert result["total_potential_savings"] == 125.00, "Should sum savings"

    print("✅ TEST 5 PASSED: _parse_recommendations() handles multiple recommendations\n")

def test_parse_recommendations_invalid_json():
    """Test handling of invalid JSON."""
    advisor = FinOpsAdvisor()

    mock_content = [MockMessageContent("This is not JSON")]
    result = advisor._parse_recommendations(mock_content)

    assert result["success"] == False, "Should fail on invalid JSON"
    assert len(result["recommendations"]) == 0, "Should have no recommendations"
    assert result["error"] is not None, "Should include error message"

    print("✅ TEST 6 PASSED: _parse_recommendations() handles invalid JSON\n")

def test_parse_recommendations_empty_response():
    """Test handling of empty response."""
    advisor = FinOpsAdvisor()

    mock_content = [MockMessageContent("")]
    result = advisor._parse_recommendations(mock_content)

    assert result["success"] == False, "Should fail on empty response"
    assert result["error"] is not None, "Should include error message"

    print("✅ TEST 7 PASSED: _parse_recommendations() handles empty response\n")

# ─────────────────────────────────────────────────────────────
# TEST 3: Helper Methods
# ─────────────────────────────────────────────────────────────

def test_extract_json():
    """Test JSON extraction from text."""
    advisor = FinOpsAdvisor()

    text = 'Some text before [{"key": "value"}] and text after'
    result = advisor._extract_json(text)

    assert result == '[{"key": "value"}]', "Should extract JSON array"

    print("✅ TEST 8 PASSED: _extract_json() correctly extracts JSON\n")

def test_extract_json_nested():
    """Test JSON extraction with nested objects."""
    advisor = FinOpsAdvisor()

    text = 'Before [{"nested": {"deep": "value"}}] After'
    result = advisor._extract_json(text)

    assert '"nested"' in result, "Should handle nested structures"

    print("✅ TEST 9 PASSED: _extract_json() handles nested JSON\n")

def test_generate_summary():
    """Test summary generation."""
    advisor = FinOpsAdvisor()

    recommendations = [
        {"priority": "Quick Win", "estimated_savings": 50.00},
        {"priority": "Quick Win", "estimated_savings": 30.00},
        {"priority": "Strategic", "estimated_savings": 100.00}
    ]

    summary = advisor._generate_summary(recommendations, 180.00)

    assert "Found 3 optimization opportunities" in summary, "Should mention count"
    assert "$180.00" in summary, "Should show total savings"
    assert "Quick Win" in summary, "Should mention priority"

    print("✅ TEST 10 PASSED: _generate_summary() creates readable summary\n")

# ─────────────────────────────────────────────────────────────
# RUN ALL TESTS
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("FinOpsAdvisor Test Suite")
    print("="*80 + "\n")

    # _prepare_context() tests
    print("Testing _prepare_context()...")
    print("-" * 80)
    test_prepare_context_basic()
    test_prepare_context_empty()
    test_prepare_context_includes_aggregates()

    # _parse_recommendations() tests
    print("Testing _parse_recommendations()...")
    print("-" * 80)
    test_parse_recommendations_valid_json()
    test_parse_recommendations_multiple()
    test_parse_recommendations_invalid_json()
    test_parse_recommendations_empty_response()

    # Helper method tests
    print("Testing Helper Methods...")
    print("-" * 80)
    test_extract_json()
    test_extract_json_nested()
    test_generate_summary()

    # Summary
    print("="*80)
    print("🎉 ALL TESTS PASSED!")
    print("="*80 + "\n")
