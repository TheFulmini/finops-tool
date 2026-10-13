"""
mock-azure/offline_harness.py
============================================================
Test harness that fakes ONLY the Azure boundary.

Nothing in core/ or providers/ is reimplemented: the SDK clients and the
retail-price REST endpoint are replaced, and every other line of the tool
under test is the real thing.

Two fixtures matter:

* FakeResourceManagementClient — behaves like Azure:
    - resources.list(filter="resourceType eq 'T'")
        -> every resource of type T in the subscription
    - resources.list_by_resource_group(rg, filter="resourceType eq 'T'")
        -> every resource of type T **in that resource group**, regardless of
           which parent it hangs off. This is what makes the nested-SQL
           duplication reproducible against the real _list_nested_resources().

* Fake retail price endpoint — answers using the exact OData filter string
  the real pricing.py builds, so _pick_best_price()/get_price() run unmodified.
============================================================
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

SUBS_PATH = HERE / "azure_subscriptions.json"
RAW_PATH = HERE / "azure_resources_raw.json"
PRICES_PATH = HERE / "azure_prices.json"
NORMALIZED_CSV = HERE / "azure_resources_normalized.csv"

_TYPE_RE = re.compile(r"resourceType\s+eq\s+'([^']+)'")


# ── attribute bag (stands in for the msrest/azure-core model objects) ──────
class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def to_sdk(raw: dict) -> Obj:
    """Convert one raw-ARM JSON blob into the attribute object the SDK yields."""
    props = raw.get("properties") or {}
    hooks = {}
    if "hardwareProfile" in props:
        hooks["hardware_profile"] = Obj(vm_size=props["hardwareProfile"].get("vmSize", "") or "")
    if "addressSpace" in props:
        hooks["address_space"] = props["addressSpace"]

    sku = raw.get("sku")
    return Obj(
        id=raw["id"],
        name=raw["name"],
        type=raw["type"],
        location=raw.get("location"),          # may be "" on purpose
        sku=(Obj(name=sku.get("name") or "", tier=sku.get("tier") or "") if sku else None),
        properties=Obj(**hooks),               # no hardware_profile unless a VM
        tags=raw.get("tags") or {},
        kind=raw.get("kind"),
        zones=raw.get("zones"),
    )


# ── fake SDK clients ──────────────────────────────────────────────────────
class _ResourcesApi:
    def __init__(self, raw: dict):
        self.raw = raw

    def list(self, filter: str | None = None, expand: str | None = None):
        m = _TYPE_RE.search(filter or "")
        if not m:
            return []
        return [to_sdk(r) for r in self.raw.get(m.group(1), [])]

    def list_by_resource_group(self, resource_group_name: str,
                               filter: str | None = None, expand: str | None = None):
        m = _TYPE_RE.search(filter or "")
        if not m:
            return []
        t = m.group(1)
        # Deliberately NOT scoped to a parent: this mirrors Azure's behaviour
        # for an RG-scoped type filter, and is the root of the duplication bug.
        return [to_sdk(r) for r in self.raw.get(t, [])
                if r.get("resourceGroup") == resource_group_name]


class FakeResourceManagementClient:
    def __init__(self, credential=None, subscription_id=None):
        self.subscription_id = subscription_id
        self._raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        self.resources = _ResourcesApi(self._raw.get(subscription_id, {}))


class _SubscriptionsApi:
    def __init__(self, subs):
        self._subs = subs

    def list(self):
        return [Obj(subscription_id=s["subscription_id"],
                    display_name=s["display_name"],
                    state=Obj(value=s["state"])) for s in self._subs]


class FakeSubscriptionClient:
    def __init__(self, credential=None):
        subs = json.loads(SUBS_PATH.read_text(encoding="utf-8"))["value"]
        self.subscriptions = _SubscriptionsApi(subs)


# ── fake retail price endpoint ────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeRequests:
    """Stands in for the `requests` module *inside* providers.azure.pricing.

    Patching at this level (rather than replacing _fetch_prices) means the real
    cache, pagination and error handling all still run.
    """

    def __init__(self, table: dict, calls: list, fail_on: str | None = None):
        import requests as _requests
        self.RequestException = _requests.RequestException
        self.exceptions = _requests.exceptions
        self._table = table
        self.calls = calls
        self.fail_on = fail_on

    def get(self, url, params=None, timeout=None, headers=None):
        f = (params or {}).get("$filter", "")
        self.calls.append(f)
        if self.fail_on and self.fail_on in f:
            raise self.RequestException("simulated network failure")
        return _FakeResponse({"Items": self._table.get(f, []), "NextPageLink": None})


class PriceApiRecorder:
    """Records every filter string the real pricing code puts on the wire."""

    def __init__(self, fail_on: str | None = None):
        self.table = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
        self.calls: list[str] = []
        self.shim = _FakeRequests(self.table, self.calls, fail_on=fail_on)

    def __call__(self, odata_filter: str) -> list:
        self.calls.append(odata_filter)
        return self.table.get(odata_filter, [])


# ── patches ───────────────────────────────────────────────────────────────
def install(monkeypatch, fail_on: str | None = None):
    """Patch the Azure boundary. Returns the recording price endpoint.

    `fail_on` makes the price endpoint raise for any filter containing that
    substring, so network-failure handling can be exercised.
    """
    import providers.azure.resources as az_res
    import providers.azure.pricing as az_price

    monkeypatch.setattr(az_res, "ResourceManagementClient", FakeResourceManagementClient)
    monkeypatch.setattr(az_res, "SubscriptionClient", FakeSubscriptionClient)

    recorder = PriceApiRecorder(fail_on=fail_on)
    az_price._price_cache.clear()                 # module-level cache
    monkeypatch.setattr(az_price, "requests", recorder.shim)
    return recorder


# ── provider used for end-to-end runs ─────────────────────────────────────
def make_offline_provider():
    from providers.base import BaseProvider
    import providers.azure.resources as az_res
    import providers.azure.pricing as az_price

    class OfflineAzureProvider(BaseProvider):
        def __init__(self):
            self._credential = None
            self.subscription_calls = []
            self.resource_calls = []

        def authenticate(self):
            self._credential = object()          # stand-in, no real credential

        def get_subscriptions(self):
            subs = az_res.list_subscriptions(self._credential)
            return subs

        def get_resources(self, subscription_id, resource_types):
            self.resource_calls.append((subscription_id, tuple(resource_types)))
            name = subscription_id
            for s in json.loads(SUBS_PATH.read_text(encoding="utf-8"))["value"]:
                if s["subscription_id"] == subscription_id:
                    name = s["display_name"]
            return az_res.get_resources(self._credential,
                                        {"id": subscription_id, "name": name},
                                        resource_types)

        def get_price(self, resource):
            return az_price.get_price(resource)

    return OfflineAzureProvider()


# ── file helpers ──────────────────────────────────────────────────────────
def read_text(path) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def read_rows(path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def raw_lines(path) -> list[str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return f.read().splitlines()


def normalized_rows() -> list[dict]:
    return read_rows(NORMALIZED_CSV)


def write_probe_csv(path, rows, columns=None):
    """Write a hostile CSV for the --input path."""
    columns = columns or ["subscription_id", "subscription_name", "resource_group",
                          "resource_name", "resource_type", "location", "sku", "size"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "NDF") for c in columns})
    return str(path)
