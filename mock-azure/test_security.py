"""
mock-azure/test_security.py
============================================================
Security tests for the FinOps tool, run offline against the mock tenant.

CONVENTION — read before interpreting results
------------------------------------------------------------
Tests whose name starts with `test_confirmed_` PASS when the code is behaving
INSECURELY. They are executable descriptions of a defect, so a green run means
the finding is reproduced. Tests named `test_guard_` PASS when the code is
safe, i.e. they are real regression guards.
============================================================
"""

import csv
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import offline_harness as H
from core.spreadsheet_safety import FORMULA_PREFIXES

REPO = H.REPO

# The full hostile-name set, taken from the generator so they cannot drift.
sys.path.insert(0, str(H.HERE))
from generate_mock_azure import INJ  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# CSV / spreadsheet formula injection  (the export is built for Excel)
# ══════════════════════════════════════════════════════════════════════════

def _export_one(tmp_path, name, **extra):
    from core import exporter
    row = {"subscription_id": "sub-x", "subscription_name": "Sec Test",
           "resource_group": "rg-x", "resource_name": name,
           "resource_type": "Microsoft.Compute/virtualMachines",
           "location": "eastus", "sku": "NDF", "size": "Standard_B2s",
           "unit": "1 Hour", "quantity": 730, "unit_price_usd": 0.0416,
           "estimated_cost_usd": 30.368}
    row.update(extra)
    out = tmp_path / "sec.csv"
    exporter.export_csv([row], str(out))
    return out


def test_guard_export_writes_excel_bom(tmp_path):
    """
    The export deliberately targets Excel (utf-8-sig BOM). This is the
    amplifier for every formula-injection finding below: the file is meant to
    be double-clicked into a spreadsheet that evaluates cell formulas.
    """
    out = _export_one(tmp_path, "vm-safe-01")
    assert out.read_bytes().startswith(b"\xef\xbb\xbf"), "no BOM present"


def test_guard_formula_injection_hyperlink_neutralised_on_export(tmp_path):
    """
    FIXED: a resource name beginning with '=' is no longer written verbatim.
    It is apostrophe-prefixed, so a spreadsheet that evaluates formulas sees
    literal text. Without the prefix, HYPERLINK() with a remote URL is the
    classic exfiltration shape.
    """
    payload = INJ["formula_hyperlink"]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]
    assert got == "'" + payload
    assert not got.startswith(FORMULA_PREFIXES), "live formula in the export"


def test_guard_formula_injection_dde_calc_neutralised_on_export(tmp_path):
    """FIXED: the DDE payload '=cmd|'/c calc'!A1' is neutralised too."""
    payload = INJ["formula_cmd"]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]
    assert got == "'" + payload
    assert not got.startswith("=")


@pytest.mark.parametrize("label", sorted(INJ))
def test_guard_hostile_names_never_exported_as_formulas(tmp_path, label):
    """
    FIXED: no hostile name reaches the CSV in a form a spreadsheet would
    evaluate. Formula-like values get the text marker; everything else is
    exported byte-for-byte, so the export stays lossless for ordinary data.
    """
    payload = INJ[label]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]

    assert not got.startswith(FORMULA_PREFIXES), f"live formula exported: {got!r}"
    expected = "'" + payload if payload.startswith(FORMULA_PREFIXES) else payload
    assert got == expected


@pytest.mark.parametrize("label", ["plus_prefix", "minus_prefix", "at_prefix", "dde_payload"])
def test_guard_non_equals_formula_prefixes_neutralised(tmp_path, label):
    """
    FIXED: Excel treats a leading '+', '-' or '@' as a formula introducer too,
    so neutralising only '=' would be incomplete — these are covered.
    """
    payload = INJ[label]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]
    assert payload[0] in "+-@="
    assert got == "'" + payload


@pytest.mark.parametrize("label", ["tab_prefix", "cr_prefix"])
def test_guard_control_char_prefixes_neutralised(tmp_path, label):
    """
    FIXED: newer Excel builds ignore a leading TAB/CR before evaluating a
    formula, so these bypass variants are neutralised as well.
    """
    payload = INJ[label]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]
    assert not got.startswith(FORMULA_PREFIXES)
    assert got == "'" + payload


def test_guard_ordinary_names_pass_through_unchanged(tmp_path):
    """GUARD: neutralisation must not touch normal resource names."""
    for name in ("vm-prod-web-01", "stproduction004", "sql-prod-ecom/maindb", "NDF"):
        out = _export_one(tmp_path, name)
        assert H.read_rows(out)[0]["resource_name"] == name


def test_guard_neutralisation_preserves_row_count_and_costs(tmp_path):
    """
    GUARD: the defence is applied after pricing and only rewrites string
    columns that actually start with a trigger character, so row count, every
    unchanged text column and every numeric figure survive intact.
    """
    from core import exporter

    rows = H.normalized_rows()
    src = tmp_path / "in.csv"
    exporter.export_csv(rows, str(src))
    out = H.read_rows(src)

    assert len(out) == len(rows)
    for original, written in zip(rows, out):
        for col in ("resource_name", "location", "sku", "size", "resource_type"):
            expected = ("'" + original[col]
                        if original[col].startswith(FORMULA_PREFIXES) else original[col])
            assert written[col] == expected, col

    # numeric columns are untouched by the string defence
    priced = [{**r, "estimated_cost_usd": "12.5", "unit_price_usd": "0.001"}
              for r in rows]
    exporter.export_csv(priced, str(src))
    out = H.read_rows(src)
    assert {float(r["estimated_cost_usd"]) for r in out} == {12.5}


def test_guard_embedded_newline_does_not_split_csv_rows(tmp_path):
    """
    GUARD (passes): the CSV writer quotes a field containing LF, so pandas
    reads back the same number of logical rows. No row-injection via newlines —
    the newline remains *inside* the cell, which is still a spreadsheet hazard
    but not a structural one.
    """
    payload = INJ["newline"]
    out = _export_one(tmp_path, payload)
    import pandas as pd
    df = pd.read_csv(out, dtype=str, encoding="utf-8-sig")
    assert len(df) == 1, f"row count changed: {len(df)}"
    assert payload in df.iloc[0]["resource_name"]


def test_confirmed_carriage_return_preserved_in_cell(tmp_path):
    """FINDING: CR inside a field is preserved (Excel/DDE chaining vector)."""
    payload = INJ["cr_prefix"]
    out = _export_one(tmp_path, payload)
    assert "\r" in H.read_rows(out)[0]["resource_name"]


def test_confirmed_null_byte_preserved(tmp_path):
    """
    FINDING: a NUL byte reaches the output file. Downstream consumers that
    parse this CSV (or hand it to a C-backed library) can truncate the string
    at the NUL, so the value seen by the reader differs from the value written.
    """
    payload = INJ["nullbyte"]
    out = _export_one(tmp_path, payload)
    assert "\x00" in H.read_text(out)


def test_confirmed_visual_spoofing_bidi_preserved(tmp_path):
    """
    FINDING: the Unicode RTL-override (U+202E) is preserved. In a cost report
    it reverses the rendered order of the surrounding text, so a hostile
    resource can be made to display as a different, benign-looking name —
    a spoofing vector in any human-reviewed spend report.
    """
    payload = INJ["bidi"]
    out = _export_one(tmp_path, payload)
    assert "\u202e" in H.read_rows(out)[0]["resource_name"]


def test_confirmed_homoglyph_name_not_flagged(tmp_path):
    """
    FINDING: a resource whose name uses Cyrillic characters to imitate a known
    production name is accepted and, once exported, is visually
    indistinguishable from the real resource in a report.
    """
    payload = INJ["homoglyph"]
    out = _export_one(tmp_path, payload)
    got = H.read_rows(out)[0]["resource_name"]
    assert got == payload
    assert got != "vm-prod-web-01"                # different bytes
    assert got.encode() != "vm-prod-web-01".encode()
    assert got.isascii() is False                 # but looks identical


def test_confirmed_oversize_name_not_truncated(tmp_path):
    """
    FINDING: a 10,000-character resource name is stored and exported without
    bound or truncation (no length validation anywhere in the pipeline).
    """
    payload = INJ["long10k"]
    out = _export_one(tmp_path, payload)
    assert len(H.read_rows(out)[0]["resource_name"]) == len(payload)
    assert len(payload) > 10000


# ══════════════════════════════════════════════════════════════════════════
# Terminal / log injection via the --input path
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_terminal_escape_injection_via_input_csv(tmp_path, monkeypatch, capsys):
    """
    FINDING: on the --input path the resource name comes from an untrusted file
    and is echoed to the terminal with no escaping. An ANSI sequence in the
    name therefore executes in the operator's terminal — cursor moves, cleared
    lines, or (on some terminals) clipboard and title-bar writes. Resource
    names from the live Azure API cannot contain ESC, but an imported CSV can.
    """
    from core import pricer
    monkeypatch.setattr(pricer, "provider_fake", None, raising=False)

    hostile = "\x1b[31m\x1b]0;PWNED\x07vm-evil-01"
    rows = [{"subscription_id": "s", "subscription_name": "n", "resource_group": "rg",
             "resource_name": hostile, "resource_type": "Microsoft.Compute/virtualMachines",
             "location": "eastus", "sku": "NDF", "size": "Standard_B2s"} for _ in range(3)]

    class P:
        def get_price(self, r):
            return {"unit": "1 Hour", "quantity": 730, "unit_price_usd": 0.04,
                    "estimated_cost_usd": 29.2}

    pricer.enrich(rows, P())
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "\x1b]0;PWNED\x07" in combined, "escape sequence was stripped"
    assert "\x1b[31m" in combined


def test_confirmed_escape_injection_not_sanitised_by_console(capsys):
    """FINDING: core.console passes strings through without escaping ESC."""
    from core import console
    console.info("evil\x1b[2J\x1b[Hwiped")
    out = capsys.readouterr().out
    assert "\x1b[2J" in out and "\x1b[H" in out


# ══════════════════════════════════════════════════════════════════════════
# Secrets / PII handling
# ══════════════════════════════════════════════════════════════════════════

def test_guard_connection_string_tag_not_leaked(tmp_path):
    """
    GUARD (passes): the mock storage account carries a fake
    `connectionString` tag with an account key. Tags are dropped by the
    extractor, so nothing leaks into the CSV — the safe outcome here.
    (The same mechanism is a data-quality failure: see test_data_quality.)
    """
    raw = json.loads(H.RAW_PATH.read_text(encoding="utf-8"))
    blob = json.dumps(raw)
    assert "AccountKey=FAKE" in blob, "fixture lost its secret-looking tag"

    out = tmp_path / "x.csv"
    from core import exporter
    exporter.export_csv(H.normalized_rows(), str(out))
    assert "AccountKey" not in H.read_text(out)
    assert "DefaultEndpointsProtocol" not in H.read_text(out)


def test_guard_no_hardcoded_credentials_in_source():
    """
    GUARD (passes): no hardcoded keys, tokens or passwords in the tool source.
    Auth is delegated to DefaultAzureCredential.
    """
    import re
    pattern = re.compile(
        r"(client_secret|account_key|password|api_key|apikey|bearer)\s*[=:]\s*['\"][A-Za-z0-9+/=_\-]{16,}",
        re.I)
    hits = []
    for p in REPO.rglob("*.py"):
        if any(part in (".venv-312", ".venv-test", ".venv", ".worktrees", ".git")
               for part in p.parts):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{p.relative_to(REPO)}:{i}")
    assert not hits, f"possible hardcoded credentials: {hits}"


def test_confirmed_auth_failure_echoes_raw_exception(capsys, monkeypatch):
    """
    FINDING: providers/azure/auth.py prints the raw exception text with
    `error(f"...: {e}")`. Azure authentication errors routinely embed the
    tenant ID, subscription ID, client ID and the failing endpoint, so this
    discloses environment detail into terminal logs and CI output.
    """
    import providers.azure.auth as auth

    class Boom(Exception):
        pass

    def exploding():
        raise Boom("AADSTS700016: tenant 'contoso-tenant-guid' client 'app-guid' "
                   "not found in directory")

    monkeypatch.setattr(auth, "DefaultAzureCredential", exploding)
    with pytest.raises(SystemExit):
        auth.get_credential()
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "contoso-tenant-guid" in out, "exception text was not echoed"
    assert "app-guid" in out


def test_confirmed_subscription_ids_written_to_all_console_output(capsys, monkeypatch):
    """
    FINDING: subscription IDs and names are printed to the terminal on every
    run (and written to the CSV). Nothing redacts them, so any shared log,
    screenshot or CI artifact carries tenant identifiers.
    """
    import providers.azure.resources as az_res
    monkeypatch.setattr(az_res, "SubscriptionClient", H.FakeSubscriptionClient)
    subs = az_res.list_subscriptions(object())
    out = capsys.readouterr().out
    assert subs
    assert subs[0]["id"] in out
    assert subs[0]["name"] in out
    assert "sub-a1b2c3d4-1111-4a2b-9c3d-000000000001" in out


# ══════════════════════════════════════════════════════════════════════════
# XLSX sink (the dashboard writes attacker-influenced strings into cells)
# ══════════════════════════════════════════════════════════════════════════

def test_guard_xlsx_never_stores_a_formula_from_an_input_csv(tmp_path):
    """
    FIXED (defence in depth): core/dashboard.py used to assign strings straight
    into cells, and openpyxl marks a leading-'=' string as a FORMULA — so a
    malicious resource_type or location from an imported CSV became a live
    formula inside the workbook, which a CSV-only fix would not have closed.

    The CSV is written directly here rather than through export_csv, so this
    exercises the dashboard's own defence rather than the exporter's.
    """
    import csv as _csv
    import zipfile
    from openpyxl import load_workbook
    from core import dashboard

    payload = "=cmd|'/c calc'!A1"
    rows = H.normalized_rows()[:40]
    rows.append({**rows[0], "resource_type": payload,
                 "resource_name": "vm-xlsx-sink", "estimated_cost_usd": "1.0"})

    src = tmp_path / "raw.csv"
    cols = list(rows[0].keys()) + ["unit", "quantity", "unit_price_usd",
                                   "estimated_cost_usd"]
    with open(src, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "0") for c in cols})

    xlsx = tmp_path / "dash.xlsx"
    dashboard.generate(str(src), str(xlsx))
    assert xlsx.exists(), "dashboard did not produce a file"

    # No <f> element anywhere in the workbook — nothing Excel will evaluate.
    z = zipfile.ZipFile(str(xlsx))
    for name in z.namelist():
        if name.startswith("xl/worksheets/sheet"):
            assert b"<f>" not in z.read(name), f"formula element written in {name}"

    wb = load_workbook(str(xlsx))
    seen = [(ws.title, c.coordinate, c.value, c.data_type)
            for ws in wb.worksheets
            for row in ws.iter_rows() for c in row
            if c.value == payload or (isinstance(c.value, str) and "cmd|" in c.value)]
    assert seen, "the payload never reached a cell, test proves nothing"
    assert all(dt == "s" for *_, dt in seen), f"stored as a formula: {seen}"


# ══════════════════════════════════════════════════════════════════════════
# Input handling: provenance, extra columns, path confinement, scale
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_no_provenance_validation_on_input_csv(tmp_path):
    """
    FINDING: import_csv() accepts any CSV with three column names. There is no
    check that the data came from Azure, no subscription allow-list and no
    signature. Fabricated billing data therefore flows straight into a report
    that looks authoritative — an integrity problem for a FinOps artefact
    used to make spending decisions.
    """
    from core import exporter
    fake = tmp_path / "invented.csv"
    fake.write_text(
        "resource_name,resource_type,location\n"
        "vm-invented,Microsoft.Compute/virtualMachines,eastus\n",
        encoding="utf-8")
    rows = exporter.import_csv(str(fake))
    assert len(rows) == 1
    assert rows[0]["resource_name"] == "vm-invented"
    assert rows[0]["subscription_id"] == "NDF"      # silently defaulted


def test_confirmed_unknown_columns_pass_through_to_output(tmp_path):
    """
    FINDING: extra columns in an imported CSV are preserved and appended to the
    export (`extra_cols` in export_csv). Unexpected columns reach a
    spreadsheet that macro-driven consumers may trust, and nothing warns.
    """
    from core import exporter
    hostile = tmp_path / "extra.csv"
    hostile.write_text(
        "resource_name,resource_type,location,injected,=cmd|'/c calc'!A1\n"
        "vm-extra,Microsoft.Compute/virtualMachines,eastus,hello,pwned\n",
        encoding="utf-8")
    rows = exporter.import_csv(str(hostile))
    out = tmp_path / "out.csv"
    exporter.export_csv(rows, str(out))
    text = H.read_text(out)
    assert "injected" in text
    # the header itself carries the formula payload as a column NAME
    assert "=cmd|'/c calc'!A1" in H.raw_lines(out)[0]


def test_confirmed_output_path_not_confined(tmp_path):
    """
    FINDING (context-dependent): export_csv writes wherever --output points,
    with no confinement to the working tree. Safe for an interactive CLI;
    becomes traversal-driven file write if the path is ever supplied by a
    config file, CI variable or another agent. The tool itself never
    validates the destination.
    """
    from core import exporter
    target = tmp_path / "deep" / "outside.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    exporter.export_csv(H.normalized_rows()[:3], str(target))
    assert target.exists()


def test_confirmed_symlink_output_followed(tmp_path):
    """
    FINDING: the output path follows a symlink. Combined with an
    attacker-writable destination directory, --output can be pointed at a
    symlink to overwrite an arbitrary file the process can write.
    """
    from core import exporter
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL", encoding="utf-8")
    link = tmp_path / "looks-like-csv.csv"
    link.symlink_to(victim)

    exporter.export_csv(H.normalized_rows()[:2], str(link))
    assert victim.read_text(encoding="utf-8-sig") != "ORIGINAL", "write did not follow symlink"
    assert "resource_name" in victim.read_text(encoding="utf-8-sig")


def test_guard_large_input_linear_and_bounded(tmp_path):
    """
    GUARD (passes): 200k rows import and re-export in reasonable time/memory.
    No quadratic blow-up, so the tool is not trivially DoS-able by file size.
    (No cap on row count either — see the report.)
    """
    import time
    from core import exporter
    big = tmp_path / "big.csv"
    with open(big, "w", newline="", encoding="utf-8") as f:
        f.write("resource_name,resource_type,location\n")
        for i in range(200_000):
            f.write(f"vm-{i},Microsoft.Compute/virtualMachines,eastus\n")
    t0 = time.time()
    rows = exporter.import_csv(str(big))
    dt = time.time() - t0
    assert len(rows) == 200_000
    assert dt < 120, f"import took {dt:.1f}s for 200k rows"


# ══════════════════════════════════════════════════════════════════════════
# Repository / supply-chain posture
# ══════════════════════════════════════════════════════════════════════════

def test_confirmed_no_license_file():
    """
    FINDING: no LICENSE at the repository root. Without one the code is
    'all rights reserved' by default — nobody may legally reuse, fork or
    contribute, which blocks adoption more than any code defect.
    """
    candidates = ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]
    assert not any((REPO / c).exists() for c in candidates)


def test_confirmed_pytest_shipped_as_runtime_dependency():
    """
    FINDING: requirements.txt lists pytest under a comment heading of
    "# testing libraries" with no dev/optional separation, so `pip install -r
    requirements.txt` — the documented install path — puts a test framework into
    every end-user environment. There is no [dev] extra to put it in.
    """
    text = (REPO / "requirements.txt").read_text(encoding="utf-8")
    assert "pytest" in text, "pytest is no longer a dependency at all"
    # it sits in the same flat list as the runtime deps, after a comment only
    assert "# testing libraries" in text
    assert "[dev]" not in text and "extras" not in text
    # and there is no pyproject to express the split properly
    assert not (REPO / "pyproject.toml").exists()
