import argparse
import logging
import json
from typing import Any, Dict, List, Optional
import boto3
import os
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio
from pydantic import AnyUrl
import ast
from operator import itemgetter

logger = logging.getLogger('mcp_aws_resources_server')


def parse_arguments() -> argparse.Namespace:
    """Use argparse to allow values to be set as CLI switches
    or environment variables

    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--access-key-id', default=os.environ.get('AWS_ACCESS_KEY_ID')
    )
    parser.add_argument(
        '--secret-access-key', default=os.environ.get('AWS_SECRET_ACCESS_KEY')
    )
    parser.add_argument(
        '--session-token', default=os.environ.get('AWS_SESSION_TOKEN')
    )
    parser.add_argument(
        '--profile', default=os.environ.get('AWS_PROFILE')
    )
    parser.add_argument(
        '--region',
        default=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
    )
    parser.add_argument(
        '--athena-workgroup',
        default=os.environ.get('AWS_ATHENA_WORKGROUP', 'primary')
    )
    parser.add_argument(
        '--athena-output-location',
        default=os.environ.get('AWS_ATHENA_OUTPUT_LOCATION', 's3://aws-athena-query-results-qa-ue1/query-results/')
    )
    return parser.parse_args()


class CodeExecutor(ast.NodeTransformer):
    """Custom AST NodeTransformer to validate and transform the code"""

    def __init__(self):
        self.has_result = False
        self.imported_modules = set()

    def visit_Assign(self, node):
        """Track if 'result' variable is assigned"""
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'result':
                self.has_result = True
        return node

    def visit_Import(self, node):
        """Track imported modules"""
        for alias in node.names:
            self.imported_modules.add(alias.name)
        return node

    def visit_ImportFrom(self, node):
        """Track imported modules"""
        self.imported_modules.add(node.module)
        return node

class AWSResourceQuerier:
    def __init__(self):
        """Initialize AWS session using environment variables"""
        args = parse_arguments()
        self.session = boto3.Session(
            aws_access_key_id=args.access_key_id,
            aws_secret_access_key=args.secret_access_key,
            aws_session_token=args.session_token,
            profile_name=args.profile,
            region_name=args.region
        )
        
        # Store Athena configuration
        self.athena_workgroup = args.athena_workgroup
        self.athena_output_location = args.athena_output_location

        if (not args.profile and
                (not args.access_key_id or not args.secret_access_key)):
            logger.warning("AWS credentials not found in environment variables")
            
    def execute_athena_query(self, query_string: str, workgroup: str = None, 
                            output_location: str = None,
                            wait_for_completion: bool = False) -> dict:
        """
        Execute an Athena query and return the execution details
        
        Args:
            query_string (str): The SQL query to execute (SELECT queries only)
            workgroup (str, optional): The Athena workgroup to use. If None, uses the server's default.
            output_location (str, optional): S3 location to store query results. If None, uses the server's default.
            wait_for_completion (bool): Whether to wait for query completion
            
        Returns:
            dict: Query execution details including execution ID and result location
        """
        try:
            # Use server defaults if parameters are not provided
            workgroup = workgroup or self.athena_workgroup
            output_location = output_location or self.athena_output_location
            
            # Validate query is SELECT only
            normalized_query = query_string.strip().upper()
            
            # Check if query starts with SELECT or SHOW or DESCRIBE
            if not (normalized_query.startswith('SELECT ') or 
                   normalized_query.startswith('WITH ') or 
                    normalized_query.startswith('SHOW ') or 
                   normalized_query.startswith('DESCRIBE ') or
                   normalized_query == 'SHOW DATABASES' or
                   normalized_query.startswith('EXPLAIN ')):
                return {
                    "error": "Security restriction: Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are allowed"
                }
                
            # Additional security check for common SQL injection patterns
            disallowed_keywords = [
                'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 
                'TRUNCATE', 'MERGE', 'GRANT', 'REVOKE', 'VACUUM'
            ]
            
            # Check for disallowed keywords in the query
            for keyword in disallowed_keywords:
                pattern = r'\b' + keyword + r'\b'
                import re
                if re.search(pattern, normalized_query):
                    return {
                        "error": f"Security restriction: Query contains disallowed keyword: {keyword}"
                    }
            
            # Create Athena client
            athena_client = self.session.client('athena')
            
            # Execute the query
            response = athena_client.start_query_execution(
                QueryString=query_string,
                WorkGroup=workgroup,
                ResultConfiguration={
                    'OutputLocation': output_location
                }
            )
            
            query_execution_id = response['QueryExecutionId']
            result = {
                'QueryExecutionId': query_execution_id,
                'OutputLocation': f"{output_location}{query_execution_id}.csv"
            }
            
            # Optionally wait for query completion
            if wait_for_completion:
                import time
                
                # Check query status
                status = 'RUNNING'
                max_retries = 100
                retry_count = 0
                
                while status in ['QUEUED', 'RUNNING'] and retry_count < max_retries:
                    status_response = athena_client.get_query_execution(
                        QueryExecutionId=query_execution_id
                    )
                    status = status_response['QueryExecution']['Status']['State']
                    
                    if status in ['QUEUED', 'RUNNING']:
                        time.sleep(1)  # Wait 1 second before checking again
                    retry_count += 1
                
                result['Status'] = status
                
                # Get results if query succeeded
                if status == 'SUCCEEDED':
                    results_response = athena_client.get_query_results(
                        QueryExecutionId=query_execution_id
                    )
                    result['Results'] = results_response
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing Athena query: {str(e)}")
            return {"error": str(e)}
            
    def get_athena_query_results(self, query_execution_id: str, max_results: int = 1000) -> dict:
        """
        Get the results of a previously executed Athena query
        
        Args:
            query_execution_id (str): The execution ID of the query
            max_results (int): Maximum number of results to return
            
        Returns:
            dict: Query results and metadata
        """
        try:
            # Create Athena client
            athena_client = self.session.client('athena')
            
            # Check query status first
            status_response = athena_client.get_query_execution(
                QueryExecutionId=query_execution_id
            )
            
            status = status_response['QueryExecution']['Status']['State']
            result = {
                'QueryExecutionId': query_execution_id,
                'Status': status,
                'StatisticsDetails': status_response['QueryExecution'].get('Statistics', {}),
                'OutputLocation': status_response['QueryExecution']['ResultConfiguration'].get('OutputLocation', '')
            }
            
            # Include error information if query failed
            if status == 'FAILED':
                if 'StateChangeReason' in status_response['QueryExecution']['Status']:
                    result['ErrorMessage'] = status_response['QueryExecution']['Status']['StateChangeReason']
            
            # Only get results if query succeeded
            if status == 'SUCCEEDED':
                results_response = athena_client.get_query_results(
                    QueryExecutionId=query_execution_id,
                    MaxResults=max_results
                )
                
                # Process column info
                column_info = []
                if 'ResultSet' in results_response and 'ResultSetMetadata' in results_response['ResultSet']:
                    for col in results_response['ResultSet']['ResultSetMetadata'].get('ColumnInfo', []):
                        column_info.append({
                            'Name': col.get('Name', ''),
                            'Type': col.get('Type', '')
                        })
                
                # Process rows
                rows = []
                if 'ResultSet' in results_response and 'Rows' in results_response['ResultSet']:
                    header_processed = False
                    
                    for row in results_response['ResultSet']['Rows']:
                        if not header_processed:
                            # Skip header row
                            header_processed = True
                            continue
                            
                        data = {}
                        for i, col_info in enumerate(column_info):
                            if i < len(row['Data']):
                                data[col_info['Name']] = row['Data'][i].get('VarCharValue', '')
                        
                        rows.append(data)
                
                result['ColumnInfo'] = column_info
                result['Rows'] = rows
                result['RowCount'] = len(rows)
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting Athena query results: {str(e)}")
            return {"error": str(e)}

    # def execute_query(self, code_snippet: str) -> str:
    #     """
    #     Execute a boto3 code snippet and return the results

    #     Args:
    #         code_snippet (str): Python code using boto3 to query AWS resources

    #     Returns:
    #         str: JSON string containing the query results or error message
    #     """
    #     try:
    #         # Parse the code into an AST
    #         tree = ast.parse(code_snippet)

    #         # Analyze the code
    #         executor = CodeExecutor()
    #         executor.visit(tree)

    #         # Validate imports
    #         allowed_modules = {'boto3', 'operator', 'json', 'datetime', 'pytz', 'dateutil', 're', 'time'}
    #         unauthorized_imports = executor.imported_modules - allowed_modules
    #         if unauthorized_imports:
    #             return json.dumps({
    #                 "error": f"Unauthorized imports: {', '.join(unauthorized_imports)}. "
    #                         f"Only {', '.join(allowed_modules)} are allowed."
    #             })

    #         # Create execution namespace
    #         local_ns = {
    #             'boto3': boto3,
    #             'session': self.session,
    #             'result': None,
    #             'itemgetter': itemgetter,
    #             '__builtins__': {
    #                 name: getattr(__builtins__, name)
    #                 for name in [
    #                     'dict', 'list', 'tuple', 'set', 'str', 'int', 'float', 'bool',
    #                     'len', 'max', 'min', 'sorted', 'filter', 'map', 'sum', 'any', 'all',
    #                     '__import__', 'hasattr', 'getattr', 'isinstance', 'print'
    #                 ]
    #             }
    #         }

    #         # Compile and execute the code
    #         compiled_code = compile(tree, '<string>', 'exec')
    #         exec(compiled_code, local_ns)

    #         # Get the result
    #         result = local_ns.get('result')

    #         # Validate result was set
    #         if not executor.has_result:
    #             return json.dumps({
    #                 "error": "Code must set a 'result' variable with the query output"
    #             })

    #         # Convert result to JSON-serializable format
    #         if result is not None:
    #             if hasattr(result, 'to_dict'):
    #                 result = result.to_dict()
    #             return json.dumps(result, default=str)
    #         else:
    #             return json.dumps({"error": "Result cannot be None"})

    #     except SyntaxError as e:
    #         logger.error(f"Syntax error in code: {str(e)}")
    #         return json.dumps({"error": f"Syntax error: {str(e)}"})
    #     except Exception as e:
    #         logger.error(f"Error executing query: {str(e)}")
    #         return json.dumps({"error": str(e)})

async def main():
    """Run the AWS Resources MCP server."""
    logger.info("Server starting")
    aws_querier = AWSResourceQuerier()
    server = Server("aws-resources-manager")

    @server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> str:
        return ""

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            # types.Tool(
            #     name="aws_resources_query_or_modify",
            #     description="Execute a boto3 code snippet to query or modify AWS resources",
            #     inputSchema={
            #         "type": "object",
            #         "properties": {
            #             "code_snippet": {
            #                 "type": "string",
            #                 "description": "Python code using boto3 to query or modify AWS resources. The code should have default execution setting variable named 'result'. Example code: 'result = boto3.client('s3').list_buckets()' or for Athena: 'athena_client = session.client(\"athena\"); response = athena_client.start_query_execution(QueryString=\"select * from prod.historical_risks limit 10;\", WorkGroup=\"superset\", ResultConfiguration={\"OutputLocation\": \"s3://cynerio-athena-results/query-results/\"}); result = {\"QueryExecutionId\": response[\"QueryExecutionId\"], \"OutputLocation\": f\"s3://cynerio-athena-results/query-results/{response[\"QueryExecutionId\"]}.csv\"}'"
            #             }
            #         },
            #         "required": ["code_snippet"]
            #     },
            # ),
            types.Tool(
                name="aws_athena_query",
                description="Execute an Athena SQL query and return the execution details",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query_string": {
                            "type": "string",
                            "description": "The SQL query to execute in Athena"
                        },
                        "workgroup": {
                            "type": "string",
                            "description": "The Athena workgroup to use. If not provided, uses the server's configured default."
                        },
                        "output_location": {
                            "type": "string",
                            "description": "S3 location to store query results. If not provided, uses the server's configured default."
                        },
                        "wait_for_completion": {
                            "type": "boolean",
                            "description": "Whether to wait for query completion",
                            "default": False
                        }
                    },
                    "required": ["query_string"]
                },
            ),
            types.Tool(
                name="aws_athena_get_query_results",
                description="Get the results of a previously executed Athena query",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query_execution_id": {
                            "type": "string",
                            "description": "The execution ID of the query to get results for"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return",
                            "default": 1000
                        }
                    },
                    "required": ["query_execution_id"]
                },
            )
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            # if name == "aws_resources_query_or_modify":
            #     if not arguments or "code_snippet" not in arguments:
            #         raise ValueError("Missing code_snippet argument")

            #     results = aws_querier.execute_query(arguments["code_snippet"])
            #     return [types.TextContent(type="text", text=str(results))]
            if name == "aws_athena_query":
                if not arguments or "query_string" not in arguments:
                    raise ValueError("Missing query_string argument")
                
                # Extract arguments with defaults
                query_string = arguments["query_string"]
                workgroup = arguments.get("workgroup")  # Will use server default if None
                output_location = arguments.get("output_location")  # Will use server default if None
                wait_for_completion = arguments.get("wait_for_completion", False)
                
                # Execute the Athena query
                result = aws_querier.execute_athena_query(
                    query_string=query_string,
                    workgroup=workgroup,
                    output_location=output_location,
                    wait_for_completion=wait_for_completion
                )
                
                return [types.TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "aws_athena_get_query_results":
                if not arguments or "query_execution_id" not in arguments:
                    raise ValueError("Missing query_execution_id argument")
                
                # Extract arguments with defaults
                query_execution_id = arguments["query_execution_id"]
                max_results = arguments.get("max_results", 1000)
                
                # Get the Athena query results
                result = aws_querier.get_athena_query_results(
                    query_execution_id=query_execution_id,
                    max_results=max_results
                )
                
                return [types.TextContent(type="text", text=json.dumps(result, default=str))]
            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logger.info("Server running with stdio transport")
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="aws-resources",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
