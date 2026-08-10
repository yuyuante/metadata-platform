"""Database object naming utilities."""


class DatabaseNaming:
    """Build fully qualified names for EMIP database objects."""

    def __init__(self, schema: str, table_prefix: str) -> None:
        self.schema = schema
        self.table_prefix = table_prefix

    def table(self, name: str) -> str:
        """Return the qualified name for an EMIP table."""

        table_name = f"{self.table_prefix}{name}"
        if self.schema:
            return f"{self.schema}.{table_name}"
        return table_name
