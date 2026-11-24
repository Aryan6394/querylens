"""Unit tests for the AST-based SQL safety validator."""

import pytest

from app.core.exceptions import UnsafeSQLError
from app.services.sql_validator import validate_sql

DATASET = "bigquery-public-data.thelook_ecommerce"


def test_allows_basic_select() -> None:
    sql = f"SELECT id, status FROM `{DATASET}.orders` WHERE status = 'Complete' LIMIT 10;"
    result = validate_sql(sql, allowed_dataset=DATASET)
    assert result.upper().startswith("SELECT")


def test_allows_cte_and_union() -> None:
    sql = f"""
    WITH recent_orders AS (
        SELECT order_id, user_id FROM `{DATASET}.orders` LIMIT 50
    )
    SELECT order_id FROM recent_orders
    UNION ALL
    SELECT order_id FROM recent_orders
    """
    result = validate_sql(sql, allowed_dataset=DATASET)
    assert "WITH recent_orders AS" in result


def test_strips_markdown_code_fences() -> None:
    raw = f"```sql\nSELECT COUNT(*) AS total FROM `{DATASET}.users`\n```"
    result = validate_sql(raw, allowed_dataset=DATASET)
    assert result.startswith("SELECT COUNT(*)")


@pytest.mark.parametrize(
    "unsafe_sql",
    [
        f"DROP TABLE `{DATASET}.orders`",
        f"DELETE FROM `{DATASET}.orders` WHERE order_id = 1",
        f"INSERT INTO `{DATASET}.orders` (order_id) VALUES (1)",
        f"UPDATE `{DATASET}.orders` SET status = 'Cancelled'",
        f"ALTER TABLE `{DATASET}.orders` ADD COLUMN test STRING",
        f"CREATE TABLE `{DATASET}.hacked` AS SELECT 1",
        f"TRUNCATE TABLE `{DATASET}.orders`",
        "EXPORT DATA OPTIONS(uri='gs://bucket/*.csv') AS SELECT 1",
        f"SELECT * FROM `{DATASET}.orders`; DROP TABLE `{DATASET}.orders`;",
        "",
        "   ",
        "SELECT FROM WHERE",
    ],
)
def test_blocks_unsafe_or_invalid_sql(unsafe_sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        validate_sql(unsafe_sql, allowed_dataset=DATASET)


def test_blocks_unauthorized_dataset() -> None:
    sql = "SELECT * FROM `other-project.private_data.secrets` LIMIT 5"
    with pytest.raises(UnsafeSQLError, match="blocked"):
        validate_sql(sql, allowed_dataset=DATASET)