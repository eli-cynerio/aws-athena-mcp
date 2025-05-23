import sys
import os
from unittest.mock import patch, MagicMock

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.mcp_server_aws_resources.server import AWSResourceQuerier

def validate_and_debug_query(querier, query, description):
    """Helper function to validate a query and print debug information."""
    print(f"\n--- Testing {description} ---")
    
    # Validate the query
    result = querier.validate_query(query)
    
    # Print the result for debugging
    print("Validation result:", result)
    
    # Check if the query is valid
    if result is None:
        print("Query is valid")
    else:
        print("Query is invalid:", result.get("error", "Unknown error"))
    
    # Additional debugging
    normalized_query = query.strip().upper()
    print("Query starts with 'WITH ':", normalized_query.startswith('WITH '))
    print("First 20 characters:", repr(normalized_query[:20]))
    
    # Check for disallowed keywords
    disallowed_keywords = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 
        'TRUNCATE', 'MERGE', 'GRANT', 'REVOKE', 'VACUUM'
    ]
    
    import re
    for keyword in disallowed_keywords:
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, normalized_query):
            print(f"Found disallowed keyword: {keyword}")

def test_specific_query_validation():
    """Test validation of a specific query that's failing."""
    
    # Create a mock session to prevent actual AWS calls
    with patch('src.mcp_server_aws_resources.server.boto3.Session') as mock_session:
        mock_session_instance = MagicMock()
        mock_session.return_value = mock_session_instance
        
        # Create the querier instance
        querier = AWSResourceQuerier()
        
        # Original query with newlines
        original_query = """WITH today_entities AS (
  SELECT id, type, type_display_name
  FROM prod.historical_network_entities_assets
  WHERE cid = 1246
  AND mac IS NOT NULL AND mac != ''
  AND day = '2025-05-22'
),
last_week_entities AS (
  SELECT id
  FROM prod.historical_network_entities_assets
  WHERE cid = 1246
  AND day >= '2025-05-15' AND day < '2025-05-22'
)
SELECT 
  t.type, 
  t.type_display_name, 
  COUNT(*) as count
FROM today_entities t
LEFT JOIN last_week_entities l ON t.id = l.id
WHERE l.id IS NULL
GROUP BY t.type, t.type_display_name
ORDER BY count DESC"""
        
        # Test the original query
        validate_and_debug_query(querier, original_query, "Original Query")
        
        # Test the query with explicit newline characters
        explicit_newlines_query = "WITH today_entities AS (\n  SELECT id, type, type_display_name\n  FROM prod.historical_network_entities_assets\n  WHERE cid = 1246\n  AND mac IS NOT NULL AND mac != ''\n  AND day = '2025-05-22'\n),\nlast_week_entities AS (\n  SELECT id\n  FROM prod.historical_network_entities_assets\n  WHERE cid = 1246\n  AND day >= '2025-05-15' AND day < '2025-05-22'\n)\nSELECT \n  t.type, \n  t.type_display_name, \n  COUNT(*) as count\nFROM today_entities t\nLEFT JOIN last_week_entities l ON t.id = l.id\nWHERE l.id IS NULL\nGROUP BY t.type, t.type_display_name\nORDER BY count DESC"
        validate_and_debug_query(querier, explicit_newlines_query, "Query with Explicit Newlines")
        
        # Test the query as a single line
        single_line_query = "WITH today_entities AS (SELECT id, type, type_display_name FROM prod.historical_network_entities_assets WHERE cid = 1246 AND mac IS NOT NULL AND mac != '' AND day = '2025-05-22'), last_week_entities AS (SELECT id FROM prod.historical_network_entities_assets WHERE cid = 1246 AND day >= '2025-05-15' AND day < '2025-05-22') SELECT t.type, t.type_display_name, COUNT(*) as count FROM today_entities t LEFT JOIN last_week_entities l ON t.id = l.id WHERE l.id IS NULL GROUP BY t.type, t.type_display_name ORDER BY count DESC"
        validate_and_debug_query(querier, single_line_query, "Single Line Query")
        
        # Test the query with double quotes for string literals
        double_quotes_query = """WITH today_entities AS (
  SELECT id, type, type_display_name
  FROM prod.historical_network_entities_assets
  WHERE cid = 1246
  AND mac IS NOT NULL AND mac != ""
  AND day = "2025-05-22"
),
last_week_entities AS (
  SELECT id
  FROM prod.historical_network_entities_assets
  WHERE cid = 1246
  AND day >= "2025-05-15" AND day < "2025-05-22"
)
SELECT 
  t.type, 
  t.type_display_name, 
  COUNT(*) as count
FROM today_entities t
LEFT JOIN last_week_entities l ON t.id = l.id
WHERE l.id IS NULL
GROUP BY t.type, t.type_display_name
ORDER BY count DESC"""
        validate_and_debug_query(querier, double_quotes_query, "Query with Double Quotes")

if __name__ == "__main__":
    test_specific_query_validation()
