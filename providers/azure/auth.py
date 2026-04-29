# providers/azure/auth.py
# ============================================================
# Azure Authentication
# ============================================================
# Uses DefaultAzureCredential from the azure-identity library.
#
# DefaultAzureCredential tries the following authentication
# methods IN ORDER, and uses the first one that succeeds:
#
#   1. Environment variables (AZURE_CLIENT_ID, etc.)
#   2. Workload Identity (for pods running in AKS)
#   3. Managed Identity (for resources running in Azure)
#   4. Azure CLI  <-- this is what we rely on for local use
#   5. Azure PowerShell
#   6. Azure Developer CLI
#
# This means: as long as you have run `az login` in your
# terminal, this will work without any extra configuration.
# ============================================================

from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ClientAuthenticationError

from core.console import success, warn, error


def get_credential() -> DefaultAzureCredential:
    """
    Create and return an Azure credential object.

    This credential is passed to all Azure SDK clients (resource,
    subscription, etc.) and handles token refresh automatically.

    Returns:
        DefaultAzureCredential: A credential object ready to use.

    Raises:
        SystemExit: If authentication cannot be established, prints
                    a helpful message and exits cleanly.
    """
    try:
        # Instantiate the credential — no token is fetched yet,
        # it's fetched lazily when the first SDK call is made.
        credential = DefaultAzureCredential()

        success("[AUTH] Azure credential initialised (using DefaultAzureCredential).")
        warn("[AUTH] If this fails later, run: az login")

        return credential

    except Exception as e:
        # Catch any unexpected error during credential setup.
        error(f"[AUTH] Failed to initialise Azure credential: {e}")
        raise SystemExit(1)
