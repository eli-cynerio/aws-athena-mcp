# Tests for AWS Athena MCP Server

This directory contains tests for the AWS Athena MCP Server.

## Directory Structure

The test directory structure mirrors the source code structure:

```
tests/
├── conftest.py                      # Global pytest configuration
├── __init__.py                      # Makes the directory a Python package
└── mcp_server_aws_resources/        # Tests for the mcp_server_aws_resources package
    ├── __init__.py                  # Makes the directory a Python package
    └── test_server.py               # Tests for server.py
```

## Running Tests

To run the tests, use pytest from the project root directory:

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run a specific test file
pytest tests/mcp_server_aws_resources/test_server.py

# Run a specific test method
pytest tests/mcp_server_aws_resources/test_server.py::test_valid_queries
```

### Setting PYTHONPATH

To ensure the tests can import from the `src` directory, set the PYTHONPATH environment variable to include the project root:

```bash
# Linux/macOS
PYTHONPATH=. pytest

# Windows
set PYTHONPATH=.
pytest
```

This approach keeps environment configuration separate from test code and follows Python best practices.

## Test Coverage

The tests cover:

1. `validate_query` method in the `AWSResourceQuerier` class:
   - Valid queries (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN)
   - Invalid queries (containing disallowed keywords)
   - Edge cases (empty queries, whitespace-only queries, case sensitivity)

## Adding New Tests

When adding new tests:

1. Follow the existing directory structure
2. Use pytest fixtures for setup and teardown
3. Use parameterized tests for testing multiple variations
4. Mock external dependencies (like boto3) to prevent actual AWS calls
