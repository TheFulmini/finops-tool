# core/ai_advisor.py
import anthropic
from typing import List, Dict
import os

class FinOpsAdvisor:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
    
    def analyze_costs(self, cost_data: List[Dict]) -> Dict:
        """
        Takes cost data from extractor and generates recommendations
        """
        # Prepare context for Claude
        context = self._prepare_context(cost_data)
        
        # Call Claude API
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": f"""You are a FinOps expert analyzing Azure infrastructure costs.

Given this cost data:
{context}

Provide 5-10 specific, actionable recommendations to optimize costs.

For each recommendation include:
1. Resource/service affected
2. Current monthly cost
3. Estimated savings (€ and %)
4. Implementation steps
5. Business risk (Low/Medium/High)
6. Priority (Quick Win/Strategic/Long-term)

Format as JSON array."""
            }]
        )
        
        return self._parse_recommendations(message.content)