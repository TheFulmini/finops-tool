"""Path setup and fixture provisioning for the offline test suite.

Nothing here alters the tool under test.

The generated Azure fixtures (JSON + CSV) are not committed — they are
reproducible byte for byte from `generate_mock_azure.py` with a fixed seed, so
they are built on demand instead.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
for p in (str(REPO), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

FIXTURES = (
    "azure_subscriptions.json",
    "azure_resources_raw.json",
    "azure_prices.json",
    "azure_resources_normalized.csv",
)


def _ensure_fixtures() -> None:
    missing = [f for f in FIXTURES if not (HERE / f).exists()]
    if not missing:
        return
    result = subprocess.run(
        [sys.executable, str(HERE / "generate_mock_azure.py")],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "could not generate the mock Azure fixtures "
            f"({', '.join(missing)} missing):\n{result.stdout}\n{result.stderr}"
        )


_ensure_fixtures()
