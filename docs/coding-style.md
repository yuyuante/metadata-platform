# Coding Style

- Follow PEP 8 and the configured Black and Ruff rules.
- Type hints are required for public interfaces and functions.
- Prefer dataclasses for small data-carrying domain objects.
- Prefer dependency injection over hidden construction and service locators.
- Do not use global mutable state.
- Use structured logging instead of `print()` in application code.
- Use UUID values as object identifiers.
- Use the Repository Pattern for persistence boundaries.
- Use the Parser Plugin Pattern for format-specific extraction.
- Keep domain logic independent of frameworks and storage technologies.