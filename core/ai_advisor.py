# core/ai_advisor.py
import anthropic
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime
import os

logger = logging.getLogger(__name__)

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

        # Call Claude API with timeout and retry safety
        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                timeout=60,
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
        except anthropic.APIError as e:
            logger.error(f"Claude API call failed: {str(e)}")
            return {
                "success": False,
                "recommendations": [],
                "error": f"Claude API error: {str(e)}",
                "recommendation_count": 0,
                "total_potential_savings": 0
            }

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

        # ─── Validate and warn on missing fields ───────────

        missing_cost_count = sum(1 for r in cost_data if "estimated_cost_usd" not in r)
        missing_type_count = sum(1 for r in cost_data if "resource_type" not in r)

        if missing_cost_count > 0:
            logger.warning(f"Found {missing_cost_count} resources missing 'estimated_cost_usd' field")
        if missing_type_count > 0:
            logger.warning(f"Found {missing_type_count} resources missing 'resource_type' field")

        # ─── Calculate aggregates ───────────────────────────

        total_cost = sum(r.get("estimated_cost_usd", 0) for r in cost_data if isinstance(r.get("estimated_cost_usd"), (int, float)))

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
            required_fields = {"resource", "current_monthly_cost", "estimated_savings", "business_risk", "priority"}

            for idx, rec in enumerate(recommendations):
                # Check for required fields
                missing_fields = required_fields - set(rec.keys())
                if missing_fields:
                    logger.warning(
                        f"Recommendation {idx} missing required fields: {missing_fields}. Skipping: {rec}"
                    )
                    continue

                # Validate and coerce numeric fields
                try:
                    current_cost = float(rec.get("current_monthly_cost", 0))
                except (ValueError, TypeError):
                    logger.error(
                        f"Recommendation {idx} has non-numeric 'current_monthly_cost': "
                        f"{rec.get('current_monthly_cost')}. Skipping."
                    )
                    continue

                try:
                    estimated_savings = float(rec.get("estimated_savings", 0))
                except (ValueError, TypeError):
                    logger.error(
                        f"Recommendation {idx} has non-numeric 'estimated_savings': "
                        f"{rec.get('estimated_savings')}. Skipping."
                    )
                    continue

                try:
                    savings_percentage = float(rec.get("savings_percentage", 0))
                except (ValueError, TypeError):
                    logger.warning(
                        f"Recommendation {idx} has non-numeric 'savings_percentage': "
                        f"{rec.get('savings_percentage')}. Using 0."
                    )
                    savings_percentage = 0

                # Validate implementation_steps is a list
                impl_steps = rec.get("implementation_steps", [])
                if not isinstance(impl_steps, list):
                    logger.warning(
                        f"Recommendation {idx} has non-list 'implementation_steps'. Converting to list."
                    )
                    impl_steps = [str(impl_steps)] if impl_steps else []

                validated_rec = {
                    "resource": rec.get("resource", "Unknown"),
                    "current_cost": current_cost,
                    "estimated_savings": estimated_savings,
                    "savings_percentage": savings_percentage,
                    "implementation_steps": impl_steps,
                    "business_risk": rec.get("business_risk", "Medium"),
                    "priority": rec.get("priority", "Medium"),
                    "action_items": rec.get("action_items", []),
                    "description": rec.get("description", "")
                }

                validated_recommendations.append(validated_rec)
                total_savings += estimated_savings

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
        Extracts JSON array from text response using proper JSON parsing.

        Attempts to find and validate JSON arrays by iterating from the first '['
        and trying to parse progressively longer substrings. This correctly handles
        escaped characters and brackets within string values.

        Args:
            text: Raw response text from Claude

        Returns:
            Valid JSON array string or None if not found or invalid
        """
        start = text.find("[")
        if start == -1:
            logger.debug("No '[' found in Claude response")
            return None

        for end in range(start + 1, len(text)):
            candidate = text[start:end + 1]
            try:
                parsed = json.loads(candidate)
                # Verify it's actually an array
                if isinstance(parsed, list):
                    return candidate
            except json.JSONDecodeError:
                continue

        logger.debug("Could not find valid JSON array in Claude response")
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