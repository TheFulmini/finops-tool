# Missing Elements — finops-tool

Last updated: 2026-04-30

| # | Item | Location | Priority |
|---|------|----------|----------|
| 1 | AI Advisor not wired into the main pipeline — `--advisor` CLI flag and `main.py` hooks are commented out | `main.py` lines 276–294, `core/ai_advisor.py` | High |
| 2 | `pytest` and `unittest.mock` missing from `requirements.txt` | `requirements.txt` | High |
| 3 | Root-level AI advisor test files not discovered by `pytest test/` — no `pytest.ini` or `pyproject.toml` to unify test paths | `test_ai_advisor_complete.py`, `test_ai_advisor_context.py`, `test_analyze_costs_integration.py` | High |
| 4 | No CI/CD pipeline | Repository root | Medium |
| 5 | `providers/aws/` is an empty placeholder — no implementation | `providers/aws/` | Medium |
| 6 | `_price_storage_account()` uses hardcoded 100 GB quantity; actual usage data cannot be passed | `providers/azure/pricing.py` | Medium |
| 7 | `_price_virtual_network()` silently returns zero with no user-facing warning about excluded peering/gateway costs | `providers/azure/pricing.py` | Medium |
| 8 | No `--version` flag or version metadata | `main.py`, `requirements.txt` | Low |
