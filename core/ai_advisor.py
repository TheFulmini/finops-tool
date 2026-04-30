# core/ai_advisor.py
import anthropic
import json
from typing import List, Dict, Optional
from datetime import datetime
import os

class FinOpsAdvisor:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

    def analyze_costs(self, cost_data: List[Dict]) -> Dict:
        """
        Takes cost data from extractor and generates recommendations.

        Args:
            cost_data: List of resource dicts with cost information

        Returns:
            Dict with success flag, recommendations, and metadata
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
3. Estimated savings (USD and %)
4. Implementation steps (as list)
5. Business risk (Low/Medium/High)
6. Priority (Quick Win/Strategic/Long-term)

Format as JSON array with keys: resource, current_monthly_cost, estimated_savings, savings_percentage, implementation_steps, business_risk, priority, action_items."""
            }]
        )

        return self._parse_recommendations(message.content)

    def _prepare_context(self, cost_data: List[Dict]) -> str:
        """
        Transforms raw cost data into readable summary for Claude.

        Calculates aggregates by resource type, subscription, and identifies
        top expensive resources.

        Args:
            cost_data: List of resource dicts from extractor

        Returns:
            Formatted string for Claude's analysis
        """
        if not cost_data:
            return "No cost data available for analysis."

        # ─── Calculate aggregates ───────────────────────────

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

        # ─── Build readable summary ────────────────────────

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
            type_name = rtype.split("/")[-1] if "/" in rtype else rtype
            summary += f"  {idx}. {type_name}: ${cost:,.2f} ({pct:.1f}%)\n"

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
            size = resource.get("size", "N/A")[:20]

            summary += (
                f"  {idx:2d}. {name:<35} | {rtype:<15} | "
                f"${cost:>10,.2f}\n"
            )

        return summary

    def _parse_recommendations(self, message_content) -> Dict:
        """
        Extracts JSON recommendations from Claude's message response.

        Handles:
        - TextBlock extraction from content list
        - JSON array parsing with error recovery
        - Field validation and type coercion
        - Summary generation

        Args:
            message_content: List of content blocks from Claude API

        Returns:
            Dict with structure:
            {
                "success": bool,
                "recommendations": [List[Dict]],
                "summary": str,
                "total_potential_savings": float,
                "recommendation_count": int,
                "error": Optional[str]
            }
        """
        try:
            # ─── Extract text from message ──────────────────

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
                    "error": "No text content in Claude response",
                    "recommendation_count": 0,
                    "total_potential_savings": 0
                }

            # ─── Extract JSON from text ────────────────────

            json_str = self._extract_json(raw_text)

            if not json_str:
                return {
                    "success": False,
                    "recommendations": [],
                    "error": "No JSON found in Claude response",
                    "recommendation_count": 0,
                    "total_potential_savings": 0
                }

            # ─── Parse and validate JSON ───────────────────

            recommendations = json.loads(json_str)

            if not isinstance(recommendations, list):
                return {
                    "success": False,
                    "recommendations": [],
                    "error": "JSON response is not an array",
                    "recommendation_count": 0,
                    "total_potential_savings": 0
                }

            # ─── Validate each recommendation ──────────────

            validated_recommendations = []
            total_savings = 0

            for rec in recommendations:
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

            # ─── Build response ────────────────────────────

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
                "error": f"JSON parsing failed: {str(e)}",
                "recommendation_count": 0,
                "total_potential_savings": 0
            }
        except Exception as e:
            return {
                "success": False,
                "recommendations": [],
                "error": f"Unexpected error: {str(e)}",
                "recommendation_count": 0,
                "total_potential_savings": 0
            }

    def _extract_json(self, text: str) -> Optional[str]:
        """
        Extracts JSON array from text response.

        Finds [ and matching ] to extract JSON array.
        Handles nested objects and arrays.

        Args:
            text: Raw response text from Claude

        Returns:
            JSON array string or None if not found
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
        Generates human-readable summary of recommendations.

        Groups by priority and calculates statistics.

        Args:
            recommendations: List of recommendation dicts
            total_savings: Total monthly savings

        Returns:
            Formatted summary string
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

        # Add priority breakdown
        for priority in ["Quick Win", "Strategic", "Long-term"]:
            if priority in by_priority:
                count = len(by_priority[priority])
                savings = sum(r.get("estimated_savings", 0) for r in by_priority[priority])
                summary += f"  {priority}: {count} action(s), ${savings:,.2f} savings\n"

        return summary

    def _get_analysis_date(self) -> str:
        """Get current date for context."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")