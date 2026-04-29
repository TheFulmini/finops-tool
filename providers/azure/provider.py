# providers/azure/provider.py
# ============================================================
# Azure Provider — Concrete Implementation
# ============================================================
# This class implements the BaseProvider interface for Azure.
# It wires together auth, resource extraction, and pricing
# into a single object that the core extractor can use.
#
# The core code never imports from azure/* directly — it only
# ever calls methods defined in BaseProvider. This is the
# modularity guarantee that makes adding AWS/GCP easy later.
# ============================================================

from typing import List, Dict, Any

from providers.base import BaseProvider
from providers.azure.auth import get_credential
from providers.azure import resources as azure_resources
from providers.azure import pricing as azure_pricing


class AzureProvider(BaseProvider):
    """
    Azure implementation of the BaseProvider interface.

    Usage:
        provider = AzureProvider()
        provider.authenticate()
        subscriptions = provider.get_subscriptions()
        ...
    """

    def __init__(self):
        # Credential is set during authenticate() — not before
        self._credential = None

    # ── BaseProvider implementation ────────────────────────

    def authenticate(self) -> None:
        """
        Initialise the Azure credential using DefaultAzureCredential.
        Relies on an active `az login` session.
        """
        self._credential = get_credential()

    def get_subscriptions(self) -> List[Dict[str, str]]:
        """
        Return all enabled Azure subscriptions accessible to
        the current identity.

        Returns:
            [{"id": "...", "name": "..."}, ...]
        """
        self._require_auth()
        return azure_resources.list_subscriptions(self._credential)

    def get_resources(
        self,
        subscription_id: str,
        resource_types: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Extract all resources of the given types from one subscription.

        Args:
            subscription_id: The subscription to query.
            resource_types:  List of ARM resource type strings.

        Returns:
            List of normalised resource dicts.
        """
        self._require_auth()

        # Build a minimal subscription dict that resources.py expects
        subscription = {
            "id":   subscription_id,
            "name": self._get_subscription_name(subscription_id),
        }
        return azure_resources.get_resources(
            self._credential, subscription, resource_types
        )

    def get_price(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """
        Look up the retail price for a single resource.
        Auth is not required for pricing — the API is public.

        Args:
            resource: A resource dict from get_resources().

        Returns:
            Dict with unit, quantity, unit_price_usd, estimated_cost_usd.
        """
        return azure_pricing.get_price(resource)

    # ── Private helpers ────────────────────────────────────

    def _require_auth(self) -> None:
        """Raise a clear error if authenticate() has not been called yet."""
        if self._credential is None:
            raise RuntimeError(
                "AzureProvider: authenticate() must be called before "
                "querying resources or subscriptions."
            )

    def _get_subscription_name(self, subscription_id: str) -> str:
        """
        Look up the display name for a subscription ID.
        Used internally when get_resources() is called directly
        with an ID rather than a full subscription dict.
        """
        subs = self.get_subscriptions()
        for sub in subs:
            if sub["id"] == subscription_id:
                return sub["name"]
        return subscription_id  # Fallback to ID if name not found
