# Testing Guide for FinOps Tool

## Quick Start

### 1. Install Testing Dependencies

```bash
pip install pytest pytest-cov pytest-mock
```

### 2. Run All Tests

```bash
# Run all tests with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=core --cov=providers --cov-report=html

# Run a specific test file
pytest tests/test_exporter.py -v

# Run a specific test class
pytest tests/test_exporter.py::TestExportCsv -v

# Run a specific test
pytest tests/test_exporter.py::TestExportCsv::test_export_creates_file -v
```

### 3. Check Coverage

```bash
# Generate coverage report
pytest tests/ --cov=core --cov=providers --cov-report=term-missing

# Generate HTML report (open htmlcov/index.html)
pytest tests/ --cov=core --cov=providers --cov-report=html
```

---

## Test Structure

### Directory Layout

```
finops-tool/
├── core/
│   ├── exporter.py
│   ├── pricer.py
│   └── ...
├── providers/
│   ├── azure/
│   │   ├── resources.py
│   │   ├── pricing.py
│   │   └── ...
│   └── ...
└── tests/              # ← Test files go here
    ├── __init__.py
    ├── conftest.py     # Shared fixtures
    ├── test_exporter.py
    ├── test_pricer.py
    ├── test_azure_resources.py
    ├── test_azure_pricing.py
    └── ...
```

### Test File Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<FunctionOrClass><Purpose>`
- Test methods: `test_<behavior_being_tested>`

Examples:
- `test_exporter.py` tests `core/exporter.py`
- `TestExportCsv` class tests the `export_csv()` function
- `test_export_creates_file()` tests that `export_csv()` creates a file

---

## Fixtures: Reusable Test Data

Fixtures are defined in `conftest.py` and automatically available to all tests. Import them by adding them as function parameters.

### Available Fixtures

#### Data Fixtures

```python
def test_something(sample_resource):
    """single Azure resource"""
    assert sample_resource["resource_type"] == "Microsoft.Compute/virtualMachines"

def test_something(sample_resources):
    """list of diverse Azure resources (VMs, storage, VNets)"""
    assert len(sample_resources) == 4

def test_something(sample_subscriptions):
    """list of mock Azure subscriptions"""
    assert len(sample_subscriptions) == 2
```

#### File Fixtures

```python
def test_csv_import(tmp_csv):
    """Path to temporary CSV file with sample data"""
    resources = import_csv(str(tmp_csv))
    assert len(resources) > 0

def test_output_location(tmp_output_dir):
    """Temporary directory for test output files"""
    output_path = tmp_output_dir / "test.csv"
    export_csv(resources, str(output_path))
    assert output_path.exists()
```

#### Provider Fixtures

```python
def test_with_mock(mock_provider):
    """Mock provider that doesn't require Azure auth"""
    mock_provider.authenticate()
    resources = mock_provider.get_resources("sub-id", ["type"])
    assert len(resources) > 0
```

#### Utility Fixtures

```python
def test_console_output(capture_output):
    """Captures all print() calls during test"""
    header("Test message")
    assert "Test message" in capture_output
```

---

## Writing New Tests

### Test Template

```python
# tests/test_my_module.py

import pytest
from my_module import my_function


class TestMyFunction:
    """Test group for my_function()"""

    def test_basic_behavior(self):
        """One-line description of what is being tested."""
        # Arrange: Set up test data
        input_data = {"key": "value"}
        
        # Act: Call the function
        result = my_function(input_data)
        
        # Assert: Check the result
        assert result == expected_value

    def test_error_handling(self):
        """Test how function handles errors."""
        with pytest.raises(ValueError):
            my_function(None)

    def test_with_fixture(self, sample_resource):
        """Tests can accept fixtures as parameters."""
        result = my_function(sample_resource)
        assert "resource_name" in result
```

### Best Practices

#### 1. Use Descriptive Test Names

```python
# Good ✅
def test_export_csv_creates_file_with_correct_columns(self):
    pass

# Bad ❌
def test_export(self):
    pass
```

#### 2. One Behavior Per Test

```python
# Good ✅
def test_export_creates_file(self):
    assert output_path.exists()

def test_export_has_all_columns(self):
    assert all(col in df.columns for col in COLUMNS)

# Bad ❌
def test_export(self):
    assert output_path.exists()
    assert all(col in df.columns for col in COLUMNS)
    assert df.shape[0] > 0
    # ... 5 more assertions
```

#### 3. Use AAA Pattern (Arrange-Act-Assert)

```python
def test_enrich_calculates_cost(self, mock_provider):
    # ARRANGE: Set up test data
    mock_provider.authenticate()
    resource = {"price": 0.5, "quantity": 100}
    
    # ACT: Call the function
    result = enrich([resource], mock_provider)
    
    # ASSERT: Check the output
    assert result[0]["estimated_cost"] == 50.0
```

#### 4. Test Edge Cases and Errors

```python
class TestMyFunction:
    def test_normal_case(self):
        """Happy path"""
        pass
    
    def test_empty_input(self):
        """Edge case: empty data"""
        pass
    
    def test_none_input(self):
        """Edge case: None"""
        pass
    
    def test_very_large_input(self):
        """Edge case: boundary condition"""
        pass
    
    def test_api_failure(self):
        """Error case: API returns error"""
        pass
```

#### 5. Isolate Unit Tests from External Dependencies

Use mocks to avoid calling real APIs:

```python
# Good ✅ - Mocked
def test_pricing(self):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"Items": [...]}
        result = get_price(resource)
        assert result["cost"] == expected

# Bad ❌ - Calls real API
def test_pricing(self):
    result = get_price(resource)  # Might fail if Azure API is down
    assert result["cost"] == expected
```

---

## Mocking and Patching

### Mock Objects

```python
from unittest.mock import MagicMock, patch

# Create a mock with specific return value
mock_credential = MagicMock()
mock_credential.get_token.return_value = "fake-token"

# Use it in your test
result = authenticate(mock_credential)
assert result == "fake-token"
```

### Patching Functions

```python
# Replace a function for the duration of a test
with patch("providers.azure.pricing._fetch_prices") as mock_fetch:
    mock_fetch.return_value = [{"retailPrice": 0.1}]
    
    result = get_price(resource)
    assert result["unit_price_usd"] == 0.1
```

### Patching with monkeypatch (pytest style)

```python
def test_something(monkeypatch):
    """monkeypatch is a pytest fixture for patching"""
    
    # Replace a module-level variable
    monkeypatch.setattr("module.CONSTANT", "new_value")
    
    # Replace a function
    monkeypatch.setattr("module.function", lambda x: x * 2)
```

---

## Running Tests in CI/CD

### GitHub Actions Example

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11, 3.12]
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-mock
      
      - name: Run tests
        run: pytest tests/ -v --cov=core --cov=providers
```

---

## Common Test Patterns

### Testing CSV Export/Import

```python
def test_csv_round_trip(self, sample_resources, tmp_output_dir):
    """Test that export → import preserves data"""
    # Export
    export_path = tmp_output_dir / "export.csv"
    export_csv(sample_resources, str(export_path))
    
    # Import
    imported = import_csv(str(export_path))
    
    # Verify
    assert len(imported) == len(sample_resources)
    assert imported[0]["resource_name"] == sample_resources[0]["resource_name"]
```

### Testing Error Handling

```python
def test_handles_api_failure(self):
    """Test graceful failure when API returns error"""
    
    class FailingMockProvider(BaseProvider):
        def get_price(self, resource):
            raise Exception("API timeout")
    
    provider = FailingMockProvider()
    
    # Should not raise — continues despite failure
    result = enrich(resources, provider)
    assert len(result) == len(resources)  # All resources still present
```

### Testing with Fixtures

```python
def test_with_multiple_fixtures(self, sample_resources, tmp_output_dir, mock_provider):
    """Tests can use multiple fixtures"""
    mock_provider.authenticate()
    
    resources = mock_provider.get_resources("sub-id", ["type"])
    assert len(resources) > 0
    
    export_path = tmp_output_dir / "test.csv"
    export_csv(resources, str(export_path))
    assert export_path.exists()
```

---

## Debugging Failed Tests

### Run Failing Test with Pdb

```bash
# Drop into Python debugger on failure
pytest tests/test_exporter.py::TestExportCsv::test_export_creates_file -v --pdb

# Set breakpoint in test code
def test_something(self):
    result = my_function()
    import pdb; pdb.set_trace()  # Debugger stops here
    assert result == expected
```

### Verbose Output

```bash
# Show print statements during tests
pytest tests/ -v -s

# Show extra info about assertions
pytest tests/ -v --tb=long
```

### Run Only Specific Tests

```bash
# Run tests matching a pattern
pytest tests/ -k "test_export" -v

# Run tests in a specific file
pytest tests/test_exporter.py -v

# Run tests in a specific class
pytest tests/test_exporter.py::TestExportCsv -v
```

---

## Coverage Goals

### Current State
- **Target**: 80%+ coverage across core/ and providers/
- **Baseline**: 0% (no tests yet)

### Coverage Report

```bash
pytest tests/ --cov=core --cov=providers --cov-report=term-missing
```

Example output:
```
core/exporter.py        45      8    82%
core/pricer.py          32      4    88%
providers/azure/resources.py   120     15    88%
providers/azure/pricing.py     200     25    88%
────────────────────────────────────────
TOTAL               397     52    87%
```

### Focus Areas
1. **exporter.py** — CSV I/O (high importance)
2. **pricer.py** — Cost calculations (high importance)
3. **azure/resources.py** — Helper functions (medium importance)
4. **azure/pricing.py** — Price dispatch (medium importance)
5. **main.py** — CLI orchestration (lower priority for unit tests)

---

## Next Steps

1. **Run the test suite**:
   ```bash
   pytest tests/ -v --cov=core --cov=providers
   ```

2. **Check coverage**:
   ```bash
   pytest tests/ --cov=core --cov=providers --cov-report=html
   # Open htmlcov/index.html
   ```

3. **Add tests for missing coverage**:
   - Identify gaps in the coverage report
   - Add test cases for uncovered lines
   - Aim for 80%+ overall

4. **Write integration tests** (optional):
   - End-to-end: extract → price → export
   - Multiple subscriptions
   - Large resource sets

---

## FAQ

**Q: How do I test code that requires Azure authentication?**
A: Use `mock_provider` fixture or mock the Azure SDK calls with `patch()`.

**Q: Can I run a single test?**
A: Yes: `pytest tests/test_exporter.py::TestExportCsv::test_export_creates_file -v`

**Q: How do I see what my test is printing?**
A: Run with `-s` flag: `pytest tests/ -v -s`

**Q: Can I use my own test data instead of fixtures?**
A: Yes, just create it in your test method, but fixtures are better for reuse.

**Q: How do I mock external API calls?**
A: Use `@patch` decorator or `with patch()` context manager to replace the function.

**Q: Should I test Azure SDK calls directly?**
A: No — mock the Azure SDK. You're testing your code, not Microsoft's SDK.

---

**Ready to get started?** Run:
```bash
pytest tests/ -v --cov=core --cov=providers --cov-report=html
```
