"""
mock-azure/test_end_to_end.py
============================================================
Runs the real CLI entry point (main.main) offline, end to end, and computes
estate-level quality metrics for the report.

Only the provider registry is swapped for the offline provider; argument
parsing, extraction, pricing, export, the Excel dashboard and the console
summary are the tool's own code.
============================================================
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

import offline_harness as H

REPO = H.REPO


@pytest.fixture
def run_cli(monkeypatch):
    """Invoke main.main() with a given argv, offline."""
    def _run(argv):
        import main as cli
        import offline_harness as H2
        provider = H2.make_offline_provider()
        monkeypatch.setattr(cli, "_get_provider_registry", lambda: {"azure": lambda: provider})
        monkeypatch.setattr("sys.argv", ["main.py"] + argv)
        cli.main()
        return provider
    return _run


def test_guard_end_to_end_repricing_run(run_cli, tmp_path, monkeypatch):
    """GUARD (passes): the full pipeline completes offline and writes a CSV."""
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    assert out.exists()
    rows = H.read_rows(out)
    assert len(rows) == len(H.normalized_rows())
    assert all("estimated_cost_usd" in r for r in rows)
    priced = [r for r in rows if float(r["estimated_cost_usd"]) > 0]
    assert priced, "nothing was priced at all"


def test_confirmed_end_to_end_loses_rows_to_pricing_errors(run_cli, tmp_path, monkeypatch):
    """
    DEFECT: the single malformed (string) price row raises TypeError inside
    get_price; pricer.enrich swallows it and writes NDF/0. The run reports
    success. A pricing outage or API change would therefore degrade quietly
    into '$0.00' rather than failing the run.
    """
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    rows = H.read_rows(out)
    ndf = [r for r in rows if r["unit"] == "NDF"]
    assert ndf, "expected the malformed price row to fall back to NDF"
    assert all(float(r["estimated_cost_usd"]) == 0 for r in ndf)


def test_confirmed_end_to_end_unpriced_estate_share(run_cli, tmp_path, monkeypatch):
    """
    DEFECT (scale): measure how much of the estate reports $0.00. This is the
    headline data-quality number for the report.
    """
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    rows = H.read_rows(out)

    zero = [r for r in rows if float(r["estimated_cost_usd"]) == 0]
    unsupported = [r for r in rows if r["unit"] == "Unsupported type"]
    na_unit = [r for r in rows if r["unit"].startswith("N/A")]
    ndf = [r for r in rows if r["unit"] == "NDF"]

    assert len(rows) == len(H.normalized_rows())
    print(f"\n  rows                : {len(rows)}")
    print(f"  $0.00 rows          : {len(zero)} ({len(zero)/len(rows):.1%})")
    print(f"    of which unsupported type: {len(unsupported)}")
    print(f"    of which N/A unit        : {len(na_unit)}")
    print(f"    of which NDF             : {len(ndf)}")

    assert len(zero) / len(rows) > 0.25, "expected >25% of the estate to report $0"
    assert len(unsupported) >= 100, "expected the unpriced types to dominate"


def test_guard_end_to_end_sql_rows_are_not_fabricated(run_cli, tmp_path, monkeypatch):
    """
    FIXED (impact quantified): the duplicated SQL rows used to carry cost, so the
    report overstated SQL spend by exactly 100 %. Each database now appears once,
    under the server that owns it.
    """
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    rows = H.read_rows(out)
    sql = [r for r in rows if r["resource_type"] == "Microsoft.Sql/servers/databases"]

    names = sorted(r["resource_name"] for r in sql)
    assert names == ["sql-prod-ecom/auditdb", "sql-prod-ecom/maindb",
                     "sql-prod-report/dwdb"], names

    # and the reported SQL total is the real one
    total = sum(float(r["estimated_cost_usd"]) for r in sql)
    assert total == pytest.approx((2 * 0.10 + 0.275) * 730, rel=1e-6), total


def test_guard_end_to_end_no_pricing_mode(run_cli, tmp_path):
    """GUARD (passes): --no-pricing runs without touching the price endpoint."""
    out = tmp_path / "noprice.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV),
             "--output", str(out), "--no-pricing"])
    rows = H.read_rows(out)
    assert len(rows) == len(H.normalized_rows())
    assert all(float(r["estimated_cost_usd"]) == 0 for r in rows)
    assert all(r["unit"] == "NDF" for r in rows)


def test_guard_end_to_end_deterministic(run_cli, tmp_path, monkeypatch):
    """GUARD (passes): two identical runs produce identical output."""
    H.install(monkeypatch)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    for out in (a, b):
        monkeypatch.undo() if False else None
        H.install(monkeypatch)
        run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    assert a.read_bytes() == b.read_bytes()


def test_confirmed_estate_metrics_for_report(run_cli, tmp_path, monkeypatch):
    """
    Produce the aggregate figures used in the report (informational: asserts
    only that the numbers are self-consistent).
    """
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    rows = H.read_rows(out)

    total = sum(float(r["estimated_cost_usd"]) for r in rows)
    by_type = defaultdict(float)
    for r in rows:
        by_type[r["resource_type"]] += float(r["estimated_cost_usd"])

    print("\n  ── ESTATE METRICS ──────────────────────────────")
    print(f"  rows                     : {len(rows)}")
    print(f"  total estimated (USD/mo) : {total:,.2f}")
    print(f"  distinct resource types  : {len(by_type)}")
    print("  top cost drivers:")
    for t, c in sorted(by_type.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {c:>12,.2f}  {t}")
    print(f"  rows with a non-zero cost: {sum(1 for r in rows if float(r['estimated_cost_usd']) > 0)}")
    print(f"  rows with quantity == 730: {sum(1 for r in rows if r['quantity'] == '730')}")
    print(f"  rows with quantity == 100: {sum(1 for r in rows if r['quantity'] == '100')}")

    assert total > 0
    assert abs(sum(by_type.values()) - total) < 0.01


def test_confirmed_assumption_vs_measured_ratio(run_cli, tmp_path, monkeypatch):
    """
    DEFECT (trust): every non-zero cost in the report rests on either a fixed
    quantity assumption (730 h, 100 GB) or a real measuring of nothing. No row
    carries a measured usage figure, so 100% of the estate total is modelled
    rather than observed. This test asserts that no usage data is present.
    """
    H.install(monkeypatch)
    out = tmp_path / "priced.csv"
    run_cli(["--provider", "azure", "--input", str(H.NORMALIZED_CSV), "--output", str(out)])
    rows = H.read_rows(out)

    known_quantities = {"730", "100"}
    vm_qty = {r["quantity"] for r in rows if r["resource_type"] ==
              "Microsoft.Compute/virtualMachines"}
    assert "730" in vm_qty
    assert vm_qty <= {"730", "0"}, vm_qty     # 0 only where pricing failed
    assert {r["quantity"] for r in rows if r["resource_type"] ==
            "Microsoft.Storage/storageAccounts"} <= {"100", "730", "0"}
    measured_cols = [c for c in rows[0] if "usage" in c or "actual" in c or "measured" in c]
    assert not measured_cols


def test_confirmed_tags_collected_but_never_exported(run_cli, tmp_path, monkeypatch):
    """
    DEFECT (allocation): the ARM payload carries costCenter/owner/environment
    on 384 resources. The normalized row dict has 8 keys and the CSV schema has
    12 columns; none is a tag. Showback and chargeback are impossible from this
    output, and the data is discarded before it can be used.
    """
    raw = json.loads(H.RAW_PATH.read_text(encoding="utf-8"))
    tagged = 0
    cost_centers = Counter()
    for sub, block in raw.items():
        for rtype, items in block.items():
            if not isinstance(items, list):
                continue
            for r in items:
                if r.get("tags"):
                    tagged += 1
                    if r["tags"].get("costCenter"):
                        cost_centers[r["tags"]["costCenter"]] += 1

    assert tagged >= 380
    assert len(cost_centers) >= 6

    cols = list(H.normalized_rows()[0].keys())
    assert "tags" not in cols and "cost_center" not in cols and "owner" not in cols
    assert len(cols) == 8


def test_confirmed_dashboard_crashes_on_the_extractors_own_output(tmp_path):
    """
    DEFECT (usability, reproducible in one command): dashboard.py requires the
    price columns, but the extractor's normalized CSV is written before pricing
    and has only 8 columns. Pointed at that file — i.e. the output of a
    --no-pricing run, or of extraction alone — the dashboard dies with a bare
    KeyError and a full Python traceback instead of a clear message.
    """
    from core import dashboard

    with pytest.raises(KeyError) as exc:
        dashboard.generate(str(H.NORMALIZED_CSV), str(tmp_path / "d.xlsx"))
    assert "estimated_cost_usd" in str(exc.value)

    # the schema mismatch that causes it
    norm_cols = set(H.normalized_rows()[0].keys())
    assert not {"estimated_cost_usd", "unit", "quantity"} & norm_cols
