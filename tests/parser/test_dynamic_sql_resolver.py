from emip.parser.dynamic_sql_resolver import DynamicSqlResolver


def test_folds_sql_server_constant_concatenation() -> None:
    source = """
    DECLARE @from nvarchar(max); DECLARE @where nvarchar(max);
    DECLARE @sql nvarchar(max);
    SET @from=' FROM CUSTOMER'; SET @where=' WHERE STATUS=''A''';
    SELECT @sql='SELECT * '; SET @sql=@sql+@from; SET @sql=@sql+@where;
    EXEC(@sql);
    """
    result = DynamicSqlResolver().resolve(source)
    assert result.resolved_sql == "SELECT * FROM CUSTOMER WHERE STATUS='A'"


def test_folds_postgres_pipe_concatenation() -> None:
    source = "sql := 'SELECT * '; sql := sql || 'FROM customer'; EXECUTE sql;"
    assert DynamicSqlResolver().resolve(source).resolved_sql == "SELECT * FROM customer"


def test_does_not_fold_runtime_or_branch_values() -> None:
    source = "IF ready = 1 THEN sql := 'SELECT * FROM customer'; END IF; EXECUTE sql;"
    assert DynamicSqlResolver().resolve(source).resolved_sql is None
