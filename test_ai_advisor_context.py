#!/usr/bin/env python3
"""
Test file for _prepare_context() method.

Run with:
  python test_ai_advisor_context.py
"""

from core.ai_advisor import FinOpsAdvisor

# Sample test data
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
print(f"Resource count: {len(sample_cost_data)}")
print(f"Total cost: ${sum(r.get('estimated_cost_usd', 0) for r in sample_cost_data):,.2f}")
