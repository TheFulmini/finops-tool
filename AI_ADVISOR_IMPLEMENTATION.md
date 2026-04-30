# AI Advisor Implementation Guide

## Overview
Complete the `FinOpsAdvisor` class by implementing two missing helper methods:
1. `_prepare_context()` — Transforms raw cost data into a readable prompt context
2. `_parse_recommendations()` — Extracts JSON recommendations from Claude's response

**Estimated time**: 1-2 hours  
**Difficulty**: Medium (JSON parsing + data transformation)

---

## Current State

✅ **Exists**:
- `__init__()` — Initializes Anthropic client
- `analyze_costs()` — Main orchestrator (complete logic, missing helpers)

❌ **Missing**:
- `_prepare_context(cost_data: List[Dict]) -> str`
- `_parse_recommendations(message_content) -> Dict`

---

## STEP 1: Understand Data Flow

### Input (cost_data):
```python
[
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
  # ... more resources
]
```

### What Claude Expects:
A human-readable summary like:
```
COST ANALYSIS SUMMARY
====================

Total Monthly Cost: $5,234.50
Resources Analyzed: 42

Top Spending Categories:
- Compute (VMs): $2,100 (40%)
- Storage: $1,200 (23%)
- Databases: $1,100 (21%)
- Networking: $400 (8%)
- Other: $434 (8%)

Subscription Breakdown:
- Production: $3,500 (67%)
- Development: $1,200 (23%)
- Testing: $534 (10%)

Resource Utilization Overview:
[List top 10 expensive resources]
```

### What Claude Returns:
```python
TextBlock(text='[{"resource": "vm-app-01", "current_cost": 154.03, ...}, ...]')
```

---

## STEP 2: Implement `_prepare_context()`

**Purpose**: Transform raw list of dicts into readable summary for Claude.

### Code Implementation:

```python
def _prepare_context(self, cost_data: List[Dict]) -> str:
    """
    Transforms raw cost data into a readable summary for Claude.
    
    Calculates aggregates by:
    - Total cost
    - Cost by resource type
    - Cost by subscription
    - Top 15 most expensive resources
    
    Args:
        cost_data: List of resource dicts from extractor
    
    Returns:
        Formatted string suitable for Claude's context window
    """
    if not cost_data:
        return "No cost data available for analysis."
    
    # ─── PHASE 1: Calculate aggregates ───────────────────────
    
    # Total cost
    total_cost = sum(r.get("estimated_cost_usd", 0) for r in cost_data)
    
    # Cost by resource type
    cost_by_type = {}
    for resource in cost_data:
        rtype = resource.get("resource_type", "Unknown")
        cost = resource.get("estimated_cost_usd", 0)
        cost_by_type[rtype] = cost_by_type.get(rtype, 0) + cost
    
    # Cost by subscription
    cost_by_sub = {}
    for resource in cost_data:
        sub = resource.get("subscription_name", "Unknown")
        cost = resource.get("estimated_cost_usd", 0)
        cost_by_sub[sub] = cost_by_sub.get(sub, 0) + cost
    
    # Top 15 expensive resources
    top_resources = sorted(
        cost_data,
        key=lambda r: r.get("estimated_cost_usd", 0),
        reverse=True
    )[:15]
    
    # ─── PHASE 2: Build readable summary ────────────────────
    
    summary = f"""COST ANALYSIS SUMMARY
{'='*50}

Metadata:
  Total Resources: {len(cost_data)}
  Total Monthly Cost: ${total_cost:,.2f}
  Analysis Date: {self._get_analysis_date()}

Cost by Resource Type (Top 5):
"""
    
    # Add top 5 resource types
    for idx, (rtype, cost) in enumerate(
        sorted(cost_by_type.items(), key=lambda x: x[1], reverse=True)[:5],
        1
    ):
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        summary += f"  {idx}. {rtype}: ${cost:,.2f} ({pct:.1f}%)\n"
    
    summary += f"\nCost by Subscription:\n"
    
    # Add all subscriptions
    for idx, (sub, cost) in enumerate(
        sorted(cost_by_sub.items(), key=lambda x: x[1], reverse=True),
        1
    ):
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        summary += f"  {idx}. {sub}: ${cost:,.2f} ({pct:.1f}%)\n"
    
    summary += f"\nTop 15 Most Expensive Resources:\n"
    
    # Add top resources
    for idx, resource in enumerate(top_resources, 1):
        name = resource.get("resource_name", "Unknown")
        rtype = resource.get("resource_type", "Unknown").split("/")[-1]
        cost = resource.get("estimated_cost_usd", 0)
        size = resource.get("size", "N/A")
        location = resource.get("location", "N/A")
        
        summary += (
            f"  {idx:2d}. {name:<40} | Type: {rtype:<15} | "
            f"Size: {size:<20} | Location: {location:<12} | "
            f"Cost: ${cost:>10,.2f}\n"
        )
    
    return summary

def _get_analysis_date(self) -> str:
    """Helper to get current date for context."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
```

### Testing `_prepare_context()`:

Create `test_ai_advisor_context.py`:

```python
# Test file: test_ai_advisor_context.py
from core.ai_advisor import FinOpsAdvisor

# Sample data
sample_cost_data = [
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

# Test
advisor = FinOpsAdvisor()
context = advisor._prepare_context(sample_cost_data)

print("=" * 80)
print("TEST: _prepare_context() output")
print("=" * 80)
print(context)
print("=" * 80)
print("\n✅ Context generated successfully!")
print(f"Total length: {len(context)} characters")
```

---

## STEP 3: Implement `_parse_recommendations()`

**Purpose**: Extract JSON recommendations from Claude's response.

### Code Implementation:

```python
import json
from typing import Optional

def _parse_recommendations(self, message_content) -> Dict:
    """
    Extracts JSON recommendations from Claude's message response.
    
    Claude returns a TextBlock containing a JSON array of recommendations.
    This method:
    1. Extracts text from message content
    2. Finds JSON array in response
    3. Validates structure
    4. Returns structured dict with recommendations + metadata
    
    Args:
        message_content: List of content blocks from Claude API response
    
    Returns:
        Dict with structure:
        {
            "success": bool,
            "recommendations": [
                {
                    "resource": str,
                    "current_cost": float,
                    "estimated_savings": float,
                    "savings_percentage": float,
                    "implementation_steps": [str],
                    "business_risk": str,
                    "priority": str,
                    "action_items": [str]
                }
            ],
            "summary": str,
            "total_potential_savings": float,
            "error": Optional[str]
        }
    """
    try:
        # ─── PHASE 1: Extract text from message ──────────────
        
        # message_content is a list of content blocks
        raw_text = ""
        if isinstance(message_content, list):
            for block in message_content:
                if hasattr(block, "text"):
                    raw_text += block.text
        else:
            raw_text = str(message_content)
        
        if not raw_text:
            return {
                "success": False,
                "recommendations": [],
                "error": "No text content in Claude response"
            }
        
        # ─── PHASE 2: Extract JSON from text ────────────────
        
        # Find JSON array in response
        json_str = self._extract_json(raw_text)
        
        if not json_str:
            return {
                "success": False,
                "recommendations": [],
                "error": "No JSON found in Claude response"
            }
        
        # ─── PHASE 3: Parse and validate JSON ───────────────
        
        recommendations = json.loads(json_str)
        
        if not isinstance(recommendations, list):
            return {
                "success": False,
                "recommendations": [],
                "error": "JSON response is not an array"
            }
        
        # ─── PHASE 4: Validate each recommendation ──────────
        
        validated_recommendations = []
        total_savings = 0
        
        for rec in recommendations:
            # Ensure required fields exist
            validated_rec = {
                "resource": rec.get("resource", "Unknown"),
                "current_cost": float(rec.get("current_monthly_cost", 0)),
                "estimated_savings": float(rec.get("estimated_savings", 0)),
                "savings_percentage": float(rec.get("savings_percentage", 0)),
                "implementation_steps": rec.get("implementation_steps", []),
                "business_risk": rec.get("business_risk", "Medium"),
                "priority": rec.get("priority", "Medium"),
                "action_items": rec.get("action_items", []),
                "description": rec.get("description", "")
            }
            
            validated_recommendations.append(validated_rec)
            total_savings += validated_rec["estimated_savings"]
        
        # ─── PHASE 5: Build response ────────────────────────
        
        return {
            "success": True,
            "recommendations": validated_recommendations,
            "summary": self._generate_summary(
                validated_recommendations,
                total_savings
            ),
            "total_potential_savings": total_savings,
            "recommendation_count": len(validated_recommendations),
            "error": None
        }
    
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "recommendations": [],
            "error": f"JSON parsing failed: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "recommendations": [],
            "error": f"Unexpected error: {str(e)}"
        }

def _extract_json(self, text: str) -> Optional[str]:
    """
    Extracts JSON array from text response.
    
    Looks for JSON array markers [ ... ] and returns the content.
    Handles nested objects and arrays.
    """
    start = text.find("[")
    if start == -1:
        return None
    
    # Find matching closing bracket
    bracket_count = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            bracket_count += 1
        elif text[i] == "]":
            bracket_count -= 1
            if bracket_count == 0:
                return text[start:i+1]
    
    return None

def _generate_summary(self, recommendations: List[Dict], total_savings: float) -> str:
    """
    Generates a human-readable summary of recommendations.
    """
    if not recommendations:
        return "No recommendations available."
    
    summary = f"Found {len(recommendations)} optimization opportunities.\n"
    summary += f"Total potential monthly savings: ${total_savings:,.2f}\n\n"
    
    # Group by priority
    by_priority = {}
    for rec in recommendations:
        priority = rec.get("priority", "Medium")
        if priority not in by_priority:
            by_priority[priority] = []
        by_priority[priority].append(rec)
    
    for priority in ["Quick Win", "Strategic", "Long-term"]:
        if priority in by_priority:
            count = len(by_priority[priority])
            savings = sum(r.get("estimated_savings", 0) for r in by_priority[priority])
            summary += f"{priority}: {count} actions (${savings:,.2f} savings)\n"
    
    return summary
```

---

## STEP 4: Create a Comprehensive Test File

Create `test_ai_advisor_complete.py`:

```python
#!/usr/bin/env python3
"""
Complete test suite for FinOpsAdvisor module.

Run with:
  python test_ai_advisor_complete.py
"""

import json
import os
from unittest.mock import Mock, patch
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
    
    # Check for aggregated values
    assert "$354.40" in context or "354.40" in context, "Should include total cost"
    assert "Compute" in context, "Should include resource type breakdown"
    
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
```

---

## STEP 5: Integration & Full Flow Test

Create `test_analyze_costs_integration.py`:

```python
#!/usr/bin/env python3
"""
Integration test for full analyze_costs() flow with mocked Claude API.
"""

import json
import os
from unittest.mock import Mock, patch
from core.ai_advisor import FinOpsAdvisor

SAMPLE_COST_DATA = [
    {
        "subscription_id": "sub-prod-001",
        "subscription_name": "Production",
        "resource_name": "vm-app-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "estimated_cost_usd": 154.03
    },
    {
        "subscription_id": "sub-prod-001",
        "subscription_name": "Production",
        "resource_name": "stproddata",
        "resource_type": "Microsoft.Storage/storageAccounts",
        "estimated_cost_usd": 170.00
    }
]

class MockTextBlock:
    def __init__(self, text):
        self.text = text

def test_analyze_costs_with_mocked_api():
    """Test full analyze_costs() flow with mocked Claude API."""
    
    # Create advisor
    advisor = FinOpsAdvisor()
    
    # Mock Claude's response
    recommendations_json = json.dumps([
        {
            "resource": "vm-app-01",
            "current_monthly_cost": 154.03,
            "estimated_savings": 50.00,
            "savings_percentage": 32.4,
            "business_risk": "Low",
            "priority": "Quick Win",
            "implementation_steps": ["Resize to smaller SKU"],
            "action_items": []
        }
    ])
    
    # Mock the Anthropic client
    with patch.object(advisor.client, 'messages') as mock_messages:
        # Configure the mock
        mock_response = Mock()
        mock_response.content = [MockTextBlock(recommendations_json)]
        mock_messages.create.return_value = mock_response
        
        # Call analyze_costs()
        result = advisor.analyze_costs(SAMPLE_COST_DATA)
        
        # Verify
        assert result["success"] == True, "Should succeed"
        assert len(result["recommendations"]) == 1, "Should have 1 recommendation"
        assert result["total_potential_savings"] == 50.00, "Should calculate savings"
        
        # Verify API was called
        mock_messages.create.assert_called_once()
        call_args = mock_messages.create.call_args
        assert "messages" in call_args.kwargs, "Should pass messages to API"
        
        print("✅ TEST PASSED: Full analyze_costs() integration works\n")
        print(f"   API called with model: {call_args.kwargs.get('model')}")
        print(f"   Max tokens: {call_args.kwargs.get('max_tokens')}")
        print(f"   Recommendations found: {len(result['recommendations'])}")
        print(f"   Total savings: ${result['total_potential_savings']:,.2f}\n")

if __name__ == "__main__":
    print("\n" + "="*80)
    print("Integration Test: analyze_costs() with Mocked Claude API")
    print("="*80 + "\n")
    
    test_analyze_costs_with_mocked_api()
    
    print("="*80)
    print("✅ Integration test completed successfully!")
    print("="*80 + "\n")
```

---

## STEP 6: Running the Tests

### 6.1 Test Individual Functions

```bash
# Terminal 1: Test _prepare_context()
python test_ai_advisor_context.py

# Output:
# ════════════════════════════════════════════════════════
# TEST: _prepare_context() output
# ════════════════════════════════════════════════════════
# COST ANALYSIS SUMMARY
# ==================================================
# ...
```

### 6.2 Run Complete Test Suite

```bash
python test_ai_advisor_complete.py

# Output:
# ════════════════════════════════════════════════════════
# FinOpsAdvisor Test Suite
# ════════════════════════════════════════════════════════
# Testing _prepare_context()...
# ────────────────────────────────────────────────────────
# ✅ TEST 1 PASSED: _prepare_context() generates proper summary
# ✅ TEST 2 PASSED: _prepare_context() handles empty data
# ...
# ════════════════════════════════════════════════════════
# 🎉 ALL TESTS PASSED!
# ════════════════════════════════════════════════════════
```

### 6.3 Run Integration Test

```bash
python test_analyze_costs_integration.py

# Output:
# ════════════════════════════════════════════════════════
# Integration Test: analyze_costs() with Mocked Claude API
# ════════════════════════════════════════════════════════
# ✅ TEST PASSED: Full analyze_costs() integration works
#    API called with model: claude-sonnet-4-20250514
#    Max tokens: 4096
#    Recommendations found: 1
#    Total savings: $50.00
# ════════════════════════════════════════════════════════
```

---

## STEP 7: Integration with main.py

Once tests pass, integrate into the main pipeline:

```python
# In main.py, around line 270

if args.advisor:
    header("[MAIN] Running AI Cost Advisor...")
    
    # Initialize advisor
    advisor = ai_advisor.FinOpsAdvisor()
    
    # Get recommendations
    analysis = advisor.analyze_costs(resources)
    
    if analysis["success"]:
        success(f"[MAIN] Generated {analysis['recommendation_count']} recommendations")
        success(f"[MAIN] Total potential savings: ${analysis['total_potential_savings']:,.2f}")
        
        # Export to JSON for reference
        advisor_output = "advisor_recommendations.json"
        with open(advisor_output, "w") as f:
            json.dump(analysis, f, indent=2)
        
        info(f"[MAIN] Recommendations saved to {advisor_output}")
    else:
        warn(f"[MAIN] Advisor failed: {analysis['error']}")
```

---

## Checklist

- [ ] Implement `_prepare_context()` method
- [ ] Implement `_parse_recommendations()` method  
- [ ] Implement helper methods (`_extract_json()`, `_generate_summary()`)
- [ ] Run `test_ai_advisor_complete.py` — all tests pass
- [ ] Run `test_analyze_costs_integration.py` — integration works
- [ ] Update main.py to call advisor after pricing
- [ ] Set `ANTHROPIC_API_KEY` environment variable
- [ ] Test end-to-end with real sample data
- [ ] Review recommendations output

---

**Next**: Once all tests pass, test with real Azure cost data!
