# providers/base.py
# ============================================================
# Abstract Base Provider
# ============================================================
# This class defines the interface that ALL cloud providers
# must implement. By enforcing this contract, we ensure that
# the core logic (extractor, pricer, exporter) never needs to
# know which provider it is talking to.
#
# To add a new provider (e.g. AWS, GCP):
#   1. Create a new folder under providers/ (e.g. providers/aws/)
#   2. Create a class that inherits from BaseProvider
#   3. Implement all abstract methods below
# ============================================================

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseProvider(ABC):
    """
    Abstract base class for all cloud providers.
    Every provider must implement authenticate(), get_subscriptions(),
    get_resources(), and get_price().
    """

    @abstractmethod
    def authenticate(self) -> None:
        """
        Authenticate with the cloud provider.
        For CLI-based auth (e.g. az login / aws configure), this method
        should set up the credential object used by subsequent calls.
        """
        pass

    @abstractmethod
    def get_subscriptions(self) -> List[Dict[str, str]]:
        """
        Return a list of all accessible subscriptions/accounts/projects.

        Expected return format (list of dicts):
        [
            {"id": "<subscription_id>", "name": "<subscription_name>"},
            ...
        ]
        """
        pass

    @abstractmethod
    def get_resources(
        self,
        subscription_id: str,
        resource_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Extract all resources of the specified types from a given subscription.

        Args:
            subscription_id: The subscription/account to query.
            resource_types:  List of resource type strings from resources.yaml.

        Expected return format (list of dicts), one entry per resource:
        [
            {
                "subscription_id":   str,
                "subscription_name": str,
                "resource_group":    str,
                "resource_name":     str,
                "resource_type":     str,
                "location":          str,
                "sku":               str,   # SKU/tier if available
                "size":              str,   # VM size, storage tier, etc.
            },
            ...
        ]
        """
        pass

    @abstractmethod
    def get_price(
        self,
        resource: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Look up the retail price for a single resource.

        Args:
            resource: A resource dict as returned by get_resources().

        Expected return format:
        {
            "unit":               str,   # e.g. "1 Hour", "1 GB/Month"
            "quantity":           float, # estimated quantity consumed
            "unit_price_usd":     float, # retail price per unit
            "estimated_cost_usd": float, # unit_price * quantity
        }
        Returns a dict with zero/None values if pricing is unavailable.
        """
        pass
