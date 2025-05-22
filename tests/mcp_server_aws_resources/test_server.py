import pytest
import re
import sys
from unittest.mock import patch, MagicMock
from src.mcp_server_aws_resources.server import AWSResourceQuerier


@pytest.fixture
def aws_resource_querier():
    """
    Fixture to create an AWSResourceQuerier instance with mocked AWS credentials.
    This prevents actual AWS calls during testing.
    """
    with patch('src.mcp_server_aws_resources.server.boto3.Session') as mock_session:
        # Mock the boto3 session to prevent actual AWS calls
        mock_session_instance = MagicMock()
        mock_session.return_value = mock_session_instance
        
        # Create the querier instance with default parameters
        querier = AWSResourceQuerier(
            region='us-east-1',
            athena_workgroup='primary',
            athena_output_location='s3://aws-athena-query-results-qa-ue1/query-results/'
        )
        
        # Return the querier for use in tests
        yield querier


"""Tests for the validate_query method in AWSResourceQuerier class."""

@pytest.mark.parametrize("query", [
    "SELECT * FROM my_table",
    "SELECT id, name FROM users WHERE age > 18",
    "SELECT COUNT(*) FROM events",
    "SELECT * FROM my_table LIMIT 10",
    "WITH cte AS (SELECT * FROM table1) SELECT * FROM cte",
    "SHOW TABLES",
    "SHOW DATABASES",
    "DESCRIBE my_table",
    "EXPLAIN SELECT * FROM my_table",
    # Complex but valid queries
    """
    SELECT 
        t1.id, 
        t1.name, 
        t2.value 
    FROM 
        table1 t1 
    JOIN 
        table2 t2 
    ON 
        t1.id = t2.id 
    WHERE 
        t1.created_at > '2023-01-01'
    """
])
def test_valid_queries(aws_resource_querier, query):
    """Test that valid queries pass validation."""
    result = aws_resource_querier.validate_query(query)
    assert result is None, f"Query should be valid but got error: {result}"

@pytest.mark.parametrize("query", [
    "INSERT INTO my_table VALUES (1, 'test')",
    "UPDATE my_table SET name = 'new' WHERE id = 1",
    "DELETE FROM my_table WHERE id = 1",
    "DROP TABLE my_table",
    "ALTER TABLE my_table ADD COLUMN new_col INT",
    "CREATE TABLE new_table (id INT)",
    "TRUNCATE TABLE my_table",
    "MERGE INTO target_table USING source_table ON (target.id = source.id)",
    "GRANT SELECT ON my_table TO user",
    "REVOKE SELECT ON my_table FROM user",
    "VACUUM my_table",
    # Mixed case to test case insensitivity
    "Insert INTO my_table VALUES (1, 'test')",
    # Query with multiple disallowed keywords
    "CREATE TABLE temp AS SELECT * FROM my_table; DROP TABLE temp",
    # Query with comments
    """
    -- This is a comment
    SELECT * FROM my_table -- Another comment
    WHERE id > 100 /* Block comment */
    """
])
def test_disallowed_keywords(aws_resource_querier, query):
    """Test that queries with disallowed keywords fail validation."""
    result = aws_resource_querier.validate_query(query)
    assert result is not None, "Query with disallowed keyword should fail validation"
    assert "error" in result, "Result should contain an error message"
    assert "Security restriction:" in result["error"], "Error should mention security restriction"

@pytest.mark.parametrize("query", [
    "EXECUTE my_procedure",
    "CALL my_procedure()",
    "SET variable = 'value'",
    "USE database",
    "ANALYZE TABLE my_table",
    "LOAD DATA INPATH 's3://bucket/file' INTO TABLE my_table",
    "COPY my_table FROM 's3://bucket/file'",
    "EXPORT TABLE my_table TO 's3://bucket/file'",
    "IMPORT TABLE my_table FROM 's3://bucket/file'"
])
def test_queries_not_starting_with_allowed_prefixes(aws_resource_querier, query):
    """Test that queries not starting with allowed prefixes fail validation."""
    result = aws_resource_querier.validate_query(query)
    assert result is not None, "Query not starting with allowed prefix should fail validation"
    assert "error" in result, "Result should contain an error message"
    assert "Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are allowed" in result["error"]

def test_empty_query(aws_resource_querier):
    """Test validation of an empty query."""
    result = aws_resource_querier.validate_query("")
    assert result is not None, "Empty query should fail validation"
    assert "error" in result, "Result should contain an error message"

def test_whitespace_only_query(aws_resource_querier):
    """Test validation of a query with only whitespace."""
    result = aws_resource_querier.validate_query("   \n   \t   ")
    assert result is not None, "Whitespace-only query should fail validation"
    assert "error" in result, "Result should contain an error message"

def test_case_insensitivity(aws_resource_querier):
    """Test that validation is case-insensitive."""
    # Valid queries with mixed case
    assert aws_resource_querier.validate_query("select * from my_table") is None
    assert aws_resource_querier.validate_query("SELECT * from My_Table") is None
    assert aws_resource_querier.validate_query("Select * From my_table") is None
    
    # Invalid queries with mixed case
    result = aws_resource_querier.validate_query("Insert INTO my_table VALUES (1, 'test')")
    assert result is not None, "Query with disallowed keyword should fail validation"

def test_query_with_leading_whitespace(aws_resource_querier):
    """Test validation of queries with leading whitespace."""
    assert aws_resource_querier.validate_query("  \n\t  SELECT * FROM my_table") is None
    assert aws_resource_querier.validate_query("\n\nSHOW TABLES") is None

def test_query_with_semicolon(aws_resource_querier):
    """Test validation of queries ending with semicolon."""
    assert aws_resource_querier.validate_query("SELECT * FROM my_table;") is None
    
    # Query with multiple statements (should fail due to second statement)
    result = aws_resource_querier.validate_query("SELECT * FROM table1; DROP TABLE table2;")
    assert result is not None, "Query with multiple statements including DROP should fail validation"

def test_regex_pattern_correctness(aws_resource_querier):
    """Test that the regex pattern used for keyword detection works correctly."""
    # This test directly examines the implementation detail of using \b word boundaries
    # to ensure keywords are matched as whole words
    
    # These should pass as the keywords are part of other words
    assert aws_resource_querier.validate_query("SELECT * FROM my_table WHERE column_name = 'DROPPING'") is None
    assert aws_resource_querier.validate_query("SELECT * FROM my_table WHERE name = 'CREATOR'") is None
    assert aws_resource_querier.validate_query("SELECT * FROM my_table WHERE status = 'INSERTED'") is None
    
    # These should fail as they contain the actual keywords
    result = aws_resource_querier.validate_query("SELECT * FROM my_table; DROP TABLE other_table")
    assert result is not None, "Query containing DROP keyword should fail validation"
    
    result = aws_resource_querier.validate_query("SELECT * FROM my_table WHERE condition INSERT INTO other_table")
    assert result is not None, "Query containing INSERT keyword should fail validation"
