#!/usr/bin/env python3
"""
Integration test for full analyze_costs() flow with mocked Claude API.

Run with:
  python test_analyze_costs_integration.py
"""

import json
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
    },
    {
        "subscription_id": "sub-dev-002",
        "subscription_name": "Development",
        "resource_name": "vm-dev-01",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "estimated_cost_usd": 30.37
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
        },
        {
            "resource": "stproddata",
            "current_monthly_cost": 170.00,
            "estimated_savings": 75.00,
            "savings_percentage": 44.1,
            "business_risk": "Medium",
            "priority": "Strategic",
            "implementation_steps": ["Change storage tier"],
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
        assert len(result["recommendations"]) == 2, "Should have 2 recommendations"
        assert result["total_potential_savings"] == 125.00, "Should calculate savings"
        assert result["recommendation_count"] == 2, "Should count recommendations"

        # Verify API was called
        mock_messages.create.assert_called_once()
        call_args = mock_messages.create.call_args
        assert "messages" in call_args.kwargs, "Should pass messages to API"

        print("✅ TEST PASSED: Full analyze_costs() integration works\n")
        print(f"   API called with model: {call_args.kwargs.get('model')}")
        print(f"   Max tokens: {call_args.kwargs.get('max_tokens')}")
        print(f"   Recommendations found: {result['recommendation_count']}")
        print(f"   Total savings: ${result['total_potential_savings']:,.2f}")
        print(f"   Summary: {result['summary'][:100]}...\n")

        # Verify recommendation structure
        rec = result["recommendations"][0]
        print("   First recommendation structure:")
        print(f"     - Resource: {rec['resource']}")
        print(f"     - Current cost: ${rec['current_cost']:,.2f}")
        print(f"     - Estimated savings: ${rec['estimated_savings']:,.2f}")
        print(f"     - Priority: {rec['priority']}")
        print(f"     - Risk: {rec['business_risk']}\n")

if __name__ == "__main__":
    print("\n" + "="*80)
    print("Integration Test: analyze_costs() with Mocked Claude API")
    print("="*80 + "\n")

    test_analyze_costs_with_mocked_api()

    print("="*80)
    print("✅ Integration test completed successfully!")
    print("="*80 + "\n")
