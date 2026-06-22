```markdown
# auto-cxas-scrapi Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `auto-cxas-scrapi` Python codebase. You'll learn how to structure files, write imports/exports, follow commit message standards, and understand the testing approach. This guide also provides commands and step-by-step instructions for common workflows.

## Coding Conventions

### File Naming
- Use **snake_case** for all file names.
  - Example: `data_parser.py`, `api_client.py`

### Import Style
- Use **relative imports** within the package.
  - Example:
    ```python
    from .utils import fetch_data
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - Example:
    ```python
    __all__ = ['fetch_data', 'parse_response']
    ```

### Commit Messages
- Follow **conventional commit** patterns.
- Prefixes: `feat` (feature), `fix` (bug fix)
- Messages are descriptive, averaging 110 characters.
  - Example:
    ```
    feat: add support for batch data processing in api_client
    fix: resolve timeout issue in fetch_data utility
    ```

## Workflows

### Making a Change
**Trigger:** When adding a new feature or fixing a bug  
**Command:** `/make-change`

1. Create a new branch for your change.
2. Implement the change following coding conventions.
3. Write or update tests as needed.
4. Commit using a conventional commit message.
5. Push your branch and open a pull request.

### Running Tests
**Trigger:** Before merging or after making changes  
**Command:** `/run-tests`

1. Identify test files (pattern: `*.test.*`).
2. Run tests using your preferred Python test runner (e.g., `pytest`, `unittest`).
   - Example:
     ```
     pytest
     ```
3. Ensure all tests pass before proceeding.

### Adding a Test
**Trigger:** When adding new functionality or fixing a bug  
**Command:** `/add-test`

1. Create a new test file or update an existing one.
   - File name should match `*.test.*` pattern.
   - Example: `api_client.test.py`
2. Write tests for new or updated code.
   - Example:
     ```python
     def test_fetch_data_success():
         result = fetch_data('test_url')
         assert result is not None
     ```
3. Run tests to verify correctness.

## Testing Patterns

- **Test files** follow the `*.test.*` naming convention (e.g., `module.test.py`).
- The specific testing framework is not enforced; use any Python-compatible test runner.
- Tests are typically written alongside the modules they cover.

## Commands
| Command       | Purpose                                      |
|---------------|----------------------------------------------|
| /make-change  | Start the process of adding or fixing code   |
| /run-tests    | Run all tests in the codebase                |
| /add-test     | Add or update a test for new functionality   |
```
