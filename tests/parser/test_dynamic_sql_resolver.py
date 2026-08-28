import pytest

from emip.parser.dynamic_sql_resolver import (
    DynamicSqlClassification,
    DynamicSqlResolver,
    DynamicSqlUnresolvedReason,
)


def test_folds_sql_server_constant_concatenation() -> None:
    source = """
    DECLARE @from nvarchar(max); DECLARE @where nvarchar(max);
    DECLARE @sql nvarchar(max);
    SET @from=' FROM CUSTOMER'; SET @where=' WHERE STATUS=''A''';
    SELECT @sql='SELECT * '; SET @sql=@sql+@from; SET @sql=@sql+@where;
    EXEC(@sql);
    """
    result = DynamicSqlResolver().resolve(source)
    assert result.classification is DynamicSqlClassification.DYNAMIC_EXACT
    assert result.resolved_sql == "SELECT * FROM CUSTOMER WHERE STATUS='A'"
    assert result.evidence[0].execution_construct == "EXEC"
    assert result.evidence[0].contributing_values


def test_folds_postgres_pipe_concatenation() -> None:
    source = "sql := 'SELECT * '; sql := sql || 'FROM customer'; EXECUTE sql;"
    assert DynamicSqlResolver().resolve(source).resolved_sql == "SELECT * FROM customer"


def test_does_not_fold_runtime_or_branch_values() -> None:
    source = "IF ready = 1 THEN sql := 'SELECT * FROM customer'; END IF; EXECUTE sql;"
    result = DynamicSqlResolver().resolve(source)
    assert result.classification is DynamicSqlClassification.POSSIBLE
    assert result.unresolved_reason is DynamicSqlUnresolvedReason.CONDITIONAL_AMBIGUITY


@pytest.mark.parametrize(
    ("source", "construct"),
    [
        ("EXEC 'SELECT * FROM sales.customer';", "EXEC"),
        ("EXECUTE 'SELECT * FROM sales.customer';", "EXECUTE"),
        ("EXEC sp_executesql N'SELECT * FROM sales.customer';", "SP_EXECUTESQL"),
        ("EXECUTE IMMEDIATE 'SELECT * FROM sales.customer';", "EXECUTE IMMEDIATE"),
    ],
)
def test_folds_supported_literal_execution_constructs(
    source: str, construct: str
) -> None:
    result = DynamicSqlResolver().resolve(source)

    assert result.classification is DynamicSqlClassification.DYNAMIC_EXACT
    assert result.resolved_sql == "SELECT * FROM sales.customer"
    assert result.evidence[0].execution_construct == construct


def test_static_sql_is_distinct_and_comments_or_literals_do_not_trigger() -> None:
    source = "SELECT 'EXECUTE IMMEDIATE x'; -- EXEC(@sql)\n/* EXEC @other */"
    result = DynamicSqlResolver().resolve(source)

    assert result.classification is DynamicSqlClassification.STATIC_EXACT
    assert not result.contains_dynamic_sql


@pytest.mark.parametrize(
    "source",
    [
        "EXEC dbo.RefreshInventory;",
        "EXECUTE dbo.RefreshInventory;",
        "EXEC proc_gen_F29;",
        "EXECUTE proc_gen_F29;",
    ],
)
def test_static_procedure_calls_are_not_dynamic_sql(source: str) -> None:
    result = DynamicSqlResolver().resolve(source)

    assert result.classification is DynamicSqlClassification.STATIC_EXACT
    assert not result.contains_dynamic_sql
    assert result.evidence == ()
    assert result.unresolved_reason is None


@pytest.mark.parametrize(
    "source",
    [
        "EXEC(@sql);",
        "EXEC @sql;",
        "EXEC 'SELECT * FROM dbo.T';",
        "EXECUTE 'SELECT * FROM dbo.T';",
        "EXEC sp_executesql @sql;",
        "EXECUTE sp_executesql @sql;",
        "EXECUTE IMMEDIATE v_sql;",
    ],
)
def test_dynamic_execution_constructs_remain_dynamic_sql(source: str) -> None:
    result = DynamicSqlResolver().resolve(source)

    assert result.contains_dynamic_sql
    assert result.classification is not DynamicSqlClassification.STATIC_EXACT
    assert result.evidence


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("EXEC(@runtime_sql);", DynamicSqlUnresolvedReason.RUNTIME_VARIABLE_UNKNOWN),
        (
            "EXEC build_sql(@name);",
            DynamicSqlUnresolvedReason.UNSUPPORTED_EXPRESSION_OR_FUNCTION,
        ),
        (
            "EXEC('SELECT * FROM ' + @table);",
            DynamicSqlUnresolvedReason.PARTIALLY_KNOWN_IDENTIFIER,
        ),
        ("EXEC($$RUNTIME_SQL);", DynamicSqlUnresolvedReason.EXTERNAL_INPUT),
        ("EXEC('unterminated);", DynamicSqlUnresolvedReason.MALFORMED_SQL),
    ],
)
def test_unresolved_reason_taxonomy(
    source: str, reason: DynamicSqlUnresolvedReason
) -> None:
    result = DynamicSqlResolver().resolve(source)

    assert result.classification is DynamicSqlClassification.UNRESOLVED
    assert result.unresolved_reason is reason
    assert result.resolved_sql is None


def test_loop_dependent_execution_is_possible_not_exact() -> None:
    source = (
        "WHILE ready LOOP sql := 'SELECT * FROM sales.customer'; EXECUTE sql; END LOOP;"
    )
    result = DynamicSqlResolver().resolve(source)

    assert result.classification is DynamicSqlClassification.POSSIBLE
    assert result.unresolved_reason is DynamicSqlUnresolvedReason.LOOP_DEPENDENT
    assert result.evidence[0].reconstructed_sql is None
