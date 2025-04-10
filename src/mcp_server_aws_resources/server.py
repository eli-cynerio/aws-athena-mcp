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

        if (not args.profile and
                (not args.access_key_id or not args.secret_access_key)):
            logger.warning("AWS credentials not found in environment variables")

    def execute_query(self, code_snippet: str) -> str:
        """
        Execute a boto3 code snippet and return the results

        Args:
            code_snippet (str): Python code using boto3 to query AWS resources

        Returns:
            str: JSON string containing the query results or error message
        """
        try:
            # Parse the code into an AST
            tree = ast.parse(code_snippet)

            # Analyze the code
            executor = CodeExecutor()
            executor.visit(tree)

            # Validate imports
            allowed_modules = {'boto3', 'operator', 'json', 'datetime', 'pytz', 'dateutil', 're', 'time'}
            unauthorized_imports = executor.imported_modules - allowed_modules
            if unauthorized_imports:
                return json.dumps({
                    "error": f"Unauthorized imports: {', '.join(unauthorized_imports)}. "
                            f"Only {', '.join(allowed_modules)} are allowed."
                })

            # Create execution namespace
            local_ns = {
                'boto3': boto3,
                'session': self.session,
                'result': None,
                'itemgetter': itemgetter,
                '__builtins__': {
                    name: getattr(__builtins__, name)
                    for name in [
                        'dict', 'list', 'tuple', 'set', 'str', 'int', 'float', 'bool',
                        'len', 'max', 'min', 'sorted', 'filter', 'map', 'sum', 'any', 'all',
                        '__import__', 'hasattr', 'getattr', 'isinstance', 'print'
                    ]
                }
            }

            # Compile and execute the code
            compiled_code = compile(tree, '<string>', 'exec')
            exec(compiled_code, local_ns)

            # Get the result
            result = local_ns.get('result')

            # Validate result was set
            if not executor.has_result:
                return json.dumps({
                    "error": "Code must set a 'result' variable with the query output"
                })

            # Convert result to JSON-serializable format
            if result is not None:
                if hasattr(result, 'to_dict'):
                    result = result.to_dict()
                return json.dumps(result, default=str)
            else:
                return json.dumps({"error": "Result cannot be None"})

        except SyntaxError as e:
            logger.error(f"Syntax error in code: {str(e)}")
            return json.dumps({"error": f"Syntax error: {str(e)}"})
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            return json.dumps({"error": str(e)})

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
            types.Tool(
                name="aws_resources_query_or_modify",
                description="Execute a boto3 code snippet to query or modify AWS resources",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code_snippet": {
                            "type": "string",
                            "description": "Python code using boto3 to query or modify AWS resources. The code should have default execution setting variable named 'result'. Example code: 'result = boto3.client('s3').list_buckets()'"
                        }
                    },
                    "required": ["code_snippet"]
                },
            )
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Handle tool execution requests"""
        try:
            if name == "aws_resources_query_or_modify":
                if not arguments or "code_snippet" not in arguments:
                    raise ValueError("Missing code_snippet argument")

                results = aws_querier.execute_query(arguments["code_snippet"])
                return [types.TextContent(type="text", text=str(results))]
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
