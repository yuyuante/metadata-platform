"""Database connection configuration loading."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config/database.yaml")
DEFAULT_ENV_CONFIG_PATH = Path(r"C:\Users\peteryu\code\env\GP178_admin.txt")
_ENV_PATTERN = re.compile(
    r"^\s*\$env:(PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD)\s*=\s*['\"]?(.*?)['\"]?\s*$"
)


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """Configuration required to open a database connection."""

    host: str
    port: int
    database: str
    username: str
    password: str
    schema: str = ""
    table_prefix: str = "EMIP_"


def _load_flat_yaml(config_path: Path) -> dict[str, str]:
    """Read the flat key/value YAML shape used by database.yaml."""

    values: dict[str, str] = {}
    with config_path.open(encoding="utf-8") as config_file:
        for line in config_file:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            key, separator, value = line.partition(":")
            if not separator:
                raise DatabaseConfigurationError(
                    f"Invalid database configuration line: {line}"
                )
            values[key.strip()] = value.strip().strip("\"'")
    return values


def _load_environment_config(config_path: Path) -> DatabaseSettings:
    """Load PostgreSQL connection variables from a PowerShell env file."""

    values: dict[str, str] = {}
    with config_path.open(encoding="utf-8") as config_file:
        for line in config_file:
            match = _ENV_PATTERN.match(line)
            if match:
                values[match.group(1)] = match.group(2).strip()

    required_fields = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing_fields = [
        field_name for field_name in required_fields if not values.get(field_name)
    ]
    if missing_fields:
        fields = ", ".join(missing_fields)
        raise DatabaseConfigurationError(
            f"Missing database environment settings: {fields}"
        )

    try:
        port = int(values["PGPORT"])
    except ValueError as exc:
        raise DatabaseConfigurationError("PGPORT must be an integer.") from exc

    return DatabaseSettings(
        host=values["PGHOST"],
        port=port,
        database=values["PGDATABASE"],
        username=values["PGUSER"],
        password=values["PGPASSWORD"],
    )


def _load_yaml(config_path: Path) -> Any:
    """Load YAML with a fallback for the Greenplum client Python path."""

    try:
        import yaml
    except ImportError:
        return _load_flat_yaml(config_path)

    try:
        with config_path.open(encoding="utf-8") as config_file:
            return yaml.safe_load(config_file)
    except yaml.YAMLError as exc:
        raise DatabaseConfigurationError(
            f"Invalid YAML in database configuration file: {config_path}"
        ) from exc


def _load_yaml_config(config_path: Path) -> DatabaseSettings:
    """Validate and convert a YAML mapping into database settings."""

    raw_config: Any = _load_yaml(config_path)
    if not isinstance(raw_config, dict):
        raise DatabaseConfigurationError(
            "Database configuration must contain a YAML mapping."
        )

    required_fields = (
        "host",
        "port",
        "database",
        "username",
        "password",
        "schema",
        "table_prefix",
    )
    missing_fields = [
        field_name
        for field_name in required_fields
        if field_name not in raw_config or raw_config[field_name] is None
    ]
    if missing_fields:
        fields = ", ".join(missing_fields)
        raise DatabaseConfigurationError(f"Missing database configuration: {fields}")

    try:
        port = int(raw_config["port"])
    except (TypeError, ValueError) as exc:
        raise DatabaseConfigurationError("Database port must be an integer.") from exc

    string_fields = (
        "host",
        "database",
        "username",
        "password",
        "schema",
        "table_prefix",
    )
    if any(not isinstance(raw_config[field_name], str) for field_name in string_fields):
        raise DatabaseConfigurationError("Database string settings must be strings.")

    return DatabaseSettings(
        host=raw_config["host"],
        port=port,
        database=raw_config["database"],
        username=raw_config["username"],
        password=raw_config["password"],
        schema=raw_config["schema"],
        table_prefix=raw_config["table_prefix"],
    )


def load_database_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> DatabaseSettings:
    """Load database settings from YAML or the configured env file fallback."""

    config_path = Path(path)
    try:
        if config_path.suffix.lower() == ".txt":
            return _load_environment_config(config_path)
        return _load_yaml_config(config_path)
    except FileNotFoundError as exc:
        if config_path == DEFAULT_CONFIG_PATH and DEFAULT_ENV_CONFIG_PATH.exists():
            return _load_environment_config(DEFAULT_ENV_CONFIG_PATH)
        raise DatabaseConfigurationError(
            f"Database configuration file not found: {config_path}"
        ) from exc
    except OSError as exc:
        raise DatabaseConfigurationError(
            f"Unable to read database configuration file: {config_path}"
        ) from exc
