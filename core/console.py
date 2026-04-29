# core/console.py
# ============================================================
# Console Color Utilities
# ============================================================
# Central place for all terminal output styling.
# Uses colorama for cross-platform ANSI color support
# (required on Windows — macOS/Linux support it natively).
#
# All other modules import from here instead of using
# colorama directly, so changing a color means editing
# one file only.
#
# Color conventions used across the tool:
#   CYAN    — section headers / progress steps
#   GREEN   — success, found resources, completed actions
#   YELLOW  — warnings, skipped items, placeholders
#   RED     — errors, failures
#   WHITE   — normal data values
#   MAGENTA — cost totals and financial highlights
#   DIM     — secondary/supporting information
# ============================================================

from colorama import init, Fore, Style

# init() must be called once before using colorama.
# autoreset=True means each print() call resets the color
# automatically — no need to append Style.RESET_ALL manually.
init(autoreset=True)


# ── Convenience wrappers ───────────────────────────────────

def header(msg: str) -> None:
    """Bold cyan — section headers like [EXTRACTOR], [CONFIG]."""
    print(f"{Style.BRIGHT}{Fore.CYAN}{msg}{Style.RESET_ALL}")


def success(msg: str) -> None:
    """Green — positive outcomes: found resources, file written."""
    print(f"{Fore.GREEN}{msg}{Style.RESET_ALL}")


def warn(msg: str) -> None:
    """Yellow — non-fatal issues: skipped items, missing data."""
    print(f"{Fore.YELLOW}{msg}{Style.RESET_ALL}")


def error(msg: str) -> None:
    """Red — failures that affect output quality."""
    print(f"{Fore.RED}{msg}{Style.RESET_ALL}")


def info(msg: str) -> None:
    """White (default) — neutral progress information."""
    print(msg)


def dim(msg: str) -> None:
    """Dimmed — secondary detail, less visually prominent."""
    print(f"{Style.DIM}{msg}{Style.RESET_ALL}")


def highlight(msg: str) -> None:
    """Bold magenta — financial totals and important figures."""
    print(f"{Style.BRIGHT}{Fore.MAGENTA}{msg}{Style.RESET_ALL}")


def item(label: str, value: str = "") -> None:
    """
    Dim label + white value — used for key/value pairs in summaries.
    Example:  item("  Total resources:", "42")
    """
    if value:
        print(f"{Style.DIM}{label}{Style.RESET_ALL} {value}")
    else:
        print(f"{Style.DIM}{label}{Style.RESET_ALL}")
