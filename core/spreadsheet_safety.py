# ============================================================
# Spreadsheet formula-injection defences
# ============================================================
# Excel, LibreOffice and Google Sheets treat a cell whose text begins with one
# of these characters as a formula rather than as text:
#
#       =   +   -   @          (and a leading TAB or CR)
#
# Azure resource names, SKUs, locations and anything read back from an
# --input CSV are attacker-influenced data: a resource can legally be named
#
#       =cmd|'/c calc'!A1
#
# Written to a spreadsheet verbatim, that string is executed when the file is
# opened — the legacy Excel DDE form needs no macro prompt. This module holds
# the single definition of "formula-like" used by both output sinks.
#
# The two sinks need two different fixes, because only one of them has types:
#
#   * CSV has no type system, so the value is prefixed with an apostrophe —
#     the spreadsheet convention for "this is literal text".
#   * .xlsx is typed, so the cell is forced to a string type instead. That
#     preserves the value exactly while forbidding a formula element.
# ============================================================

from typing import Any

#: Characters that make a spreadsheet evaluate a cell as a formula.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

#: Prepended to neutralise a formula-like value written to a CSV cell.
TEXT_MARKER = "'"


def is_formula_like(value: Any) -> bool:
    """True when `value` is a string a spreadsheet would run as a formula."""
    return isinstance(value, str) and value.startswith(FORMULA_PREFIXES)


def neutralise(value: Any) -> Any:
    """Return `value` made safe for a CSV cell. Non-strings pass through.

    Only strings that would actually be evaluated are rewritten, so ordinary
    resource names are exported unchanged.
    """
    return TEXT_MARKER + value if is_formula_like(value) else value
