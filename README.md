# AWS Athena MCP Server

## Overview

A Model Context Protocol (MCP) server implementation that provides access to AWS Athena for executing SQL queries and retrieving results. This server allows Claude to interact with your AWS Athena service to run queries and analyze data stored in S3.

## Components

### Tools

The server offers two tools for interacting with AWS Athena:

#### 1. aws_athena_query

Execute an Athena SQL query and return the execution details.

**Input Parameters:**
- `query_string` (required): The SQL query to execute in Athena
- `workgroup` (optional): The Athena workgroup to use. If not provided, uses the server's configured default.
- `output_location` (optional): S3 location to store query results. If not provided, uses the server's configured default.
- `wait_for_completion` (optional): Whether to wait for query completion (default: false)

**Security Restrictions:**
- Only SELECT, SHOW, DESCRIBE, and EXPLAIN queries are allowed
- Disallowed keywords: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, GRANT, REVOKE, VACUUM

**Example:**
```
<use_mcp_tool>
<server_name>aws</server_name>
<tool_name>aws_athena_query</tool_name>
<arguments>
{
  "query_string": "SELECT * FROM my_database.my_table LIMIT 10",
  "workgroup": "primary",
  "wait_for_completion": true
}
</arguments>
</use_mcp_tool>
```

#### 2. aws_athena_get_query_results

Get the results of a previously executed Athena query.

**Input Parameters:**
- `query_execution_id` (required): The execution ID of the query to get results for
- `max_results` (optional): Maximum number of results to return (default: 1000)

**Example:**
```
<use_mcp_tool>
<server_name>aws</server_name>
<tool_name>aws_athena_get_query_results</tool_name>
<arguments>
{
  "query_execution_id": "12345678-1234-1234-1234-123456789012"
}
</arguments>
</use_mcp_tool>
```

## Setup

### Prerequisites

You'll need AWS credentials with appropriate permissions to use Athena. You can obtain these by:
1. Creating an IAM user in your AWS account
2. Generating access keys for programmatic access
3. Ensuring the IAM user has necessary permissions for Athena and S3

The following environment variables or command-line arguments are supported:
- `AWS_ACCESS_KEY_ID` / `--access-key-id`: Your AWS access key
- `AWS_SECRET_ACCESS_KEY` / `--secret-access-key`: Your AWS secret key
- `AWS_SESSION_TOKEN` / `--session-token`: (Optional) AWS session token if using temporary credentials
- `AWS_DEFAULT_REGION` / `--region`: AWS region (defaults to 'us-east-1' if not set)
- `AWS_PROFILE` / `--profile`: AWS profile name to use from /Users/<your-user>/.aws/credentials
- `AWS_ATHENA_WORKGROUP` / `--athena-workgroup`: Athena workgroup to use (defaults to 'primary')
- `AWS_ATHENA_OUTPUT_LOCATION` / `--athena-output-location`: S3 location for query results

Note: Keep your AWS credentials secure and never commit them to version control.

### Docker Installation

#### Option 1: Pull from Docker Hub
```bash
docker pull elicynerio/aws-athena-mcp:latest
```

#### Option 2: Build Locally
```bash
docker build -t aws-athena-mcp .
```

Run the container:
```bash
# If using the pulled image:
docker run \
  -e AWS_ACCESS_KEY_ID=your_access_key_id_here \
  -e AWS_SECRET_ACCESS_KEY=your_secret_access_key_here \
  -e AWS_DEFAULT_REGION=your_region \
  -e AWS_ATHENA_WORKGROUP=your_workgroup \
  -e AWS_ATHENA_OUTPUT_LOCATION=s3://your-bucket/path/ \
  elicynerio/aws-athena-mcp:latest

# If using the locally built image:
docker run \
  -e AWS_ACCESS_KEY_ID=your_access_key_id_here \
  -e AWS_SECRET_ACCESS_KEY=your_secret_access_key_here \
  -e AWS_DEFAULT_REGION=your_region \
  -e AWS_ATHENA_WORKGROUP=your_workgroup \
  -e AWS_ATHENA_OUTPUT_LOCATION=s3://your-bucket/path/ \
  aws-athena-mcp
```

Or using stored credentials and a profile:
```bash
# If using the pulled image:
docker run \
  -e AWS_PROFILE=your_profile_name \
  -v /Users/<your-user>/.aws:/root/.aws \
  elicynerio/aws-athena-mcp:latest

# If using the locally built image:
docker run \
  -e AWS_PROFILE=your_profile_name \
  -v /Users/<your-user>/.aws:/root/.aws \
  aws-athena-mcp
```

## Usage with Claude

### Running with Docker

#### Using direct AWS credentials:
```json
{
  "mcpServers": {
    "aws": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "AWS_ACCESS_KEY_ID=your_access_key_id_here",
        "-e",
        "AWS_SECRET_ACCESS_KEY=your_secret_access_key_here",
        "-e",
        "AWS_DEFAULT_REGION=us-east-1",
        "-e",
        "AWS_ATHENA_WORKGROUP=primary",
        "-e",
        "AWS_ATHENA_OUTPUT_LOCATION=s3://your-bucket/path/",
        "elicynerio/aws-athena-mcp:latest"
      ]
    }
  }
}
```

#### Using AWS profile:
```json
{
  "mcpServers": {
    "aws": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "AWS_PROFILE=your_profile_name",
        "-e",
        "AWS_DEFAULT_REGION=us-east-1",
        "-e",
        "AWS_ATHENA_WORKGROUP=primary",
        "-e",
        "AWS_ATHENA_OUTPUT_LOCATION=s3://your-bucket/path/",
        "-v",
        "/Users/<your-user>/.aws:/root/.aws",
        "elicynerio/aws-athena-mcp:latest"
      ]
    }
  }
}
```

### Running with Local Installation

```json
{
  "mcpServers": {
    "aws": {
      "command": "python",
      "args": [
        "-m",
        "src/mcp_server_aws_resources/server.py",
        "--profile",
        "your_profile_name",
        "--athena-workgroup",
        "primary",
        "--athena-output-location",
        "s3://your-bucket/path/"
      ]
    }
  }
}
```

Or using uv:
```json
{
  "mcpServers": {
    "aws": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/aws-athena-mcp",
        "run",
        "src/mcp_server_aws_resources/server.py",
        "--profile",
        "your_profile_name"
      ]
    }
  }
}
```

## Example Workflow

1. Execute a query:
```
<use_mcp_tool>
<server_name>aws</server_name>
<tool_name>aws_athena_query</tool_name>
<arguments>
{
  "query_string": "SELECT * FROM my_database.my_table LIMIT 10"
}
</arguments>
</use_mcp_tool>
```

2. Get the query execution ID from the response

3. Retrieve the results:
```
<use_mcp_tool>
<server_name>aws</server_name>
<tool_name>aws_athena_get_query_results</tool_name>
<arguments>
{
  "query_execution_id": "query_execution_id_from_previous_response"
}
</arguments>
</use_mcp_tool>
