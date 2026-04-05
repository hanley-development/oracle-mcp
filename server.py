"""
Oracle ADB MCP Server
Connects via OCI Bastion Service + SSH tunnel + Wallet
"""

import asyncio
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json

from connection import ConnectionManager
from schema import SchemaInspector
from relationships import RelationshipInferer
from diagram import ERDGenerator
from query import QueryExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("oracle-adb-mcp")
conn_manager = ConnectionManager()


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="connect",
            description="Establish connection to Oracle ADB via OCI Bastion tunnel and wallet. Call this first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "Database schema/owner to inspect (e.g. 'APPS', 'HR'). Leave empty for current user."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_schema",
            description="Get all tables and their columns for the connected schema. Returns table names, column names, data types, nullable flags.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Optional table name prefix/pattern to filter (e.g. 'HR_', 'AP_%')"
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number for pagination (50 tables per page). Default 1."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="infer_relationships",
            description="Heuristically infer foreign key relationships between tables based on column naming patterns, even without explicit FK constraints. Returns likely joins.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific table names to analyze. If empty, analyzes all tables (may be slow for 500+)."
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Minimum confidence level for returned relationships. Default: medium"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="generate_erd",
            description="Generate an Entity Relationship Diagram in Mermaid format for a set of tables and their inferred relationships.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Table names to include in the ERD. Keep to <30 tables for readable diagrams."
                    },
                    "include_columns": {
                        "type": "boolean",
                        "description": "Include column details in the diagram. Default true."
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Minimum confidence for relationships to include. Default: medium"
                    }
                },
                "required": ["tables"]
            }
        ),
        Tool(
            name="explain_table",
            description="Get detailed stats and explanation for a specific table: row count, column stats, nullability, sample data, top values for key columns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "Table name to explain"
                    },
                    "sample_rows": {
                        "type": "integer",
                        "description": "Number of sample rows to return. Default 5."
                    }
                },
                "required": ["table"]
            }
        ),
        Tool(
            name="query",
            description="Execute a read-only SQL query against the Oracle ADB. Only SELECT statements are permitted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL SELECT statement to execute"
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": "Maximum rows to return. Default 100, max 1000."
                    }
                },
                "required": ["sql"]
            }
        ),
        Tool(
            name="search_columns",
            description="Search across all tables for columns matching a name pattern. Useful for finding where a concept (e.g. 'EMPLOYEE', 'INVOICE') appears across the schema.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Column name pattern to search (e.g. 'EMPLOYEE_ID', '%_DATE', 'AMOUNT')"
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="disconnect",
            description="Close the database connection and SSH tunnel cleanly.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "connect":
            result = await conn_manager.connect(arguments.get("schema"))
            return [TextContent(type="text", text=result)]

        if not conn_manager.is_connected():
            return [TextContent(type="text", text="❌ Not connected. Please call 'connect' first.")]

        if name == "get_schema":
            inspector = SchemaInspector(conn_manager)
            result = await inspector.get_schema(
                filter_pattern=arguments.get("filter"),
                page=arguments.get("page", 1)
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "infer_relationships":
            inspector = SchemaInspector(conn_manager)
            inferer = RelationshipInferer(inspector)
            result = await inferer.infer(
                tables=arguments.get("tables"),
                min_confidence=arguments.get("confidence", "medium")
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "generate_erd":
            inspector = SchemaInspector(conn_manager)
            inferer = RelationshipInferer(inspector)
            generator = ERDGenerator(inspector, inferer)
            result = await generator.generate(
                tables=arguments["tables"],
                include_columns=arguments.get("include_columns", True),
                min_confidence=arguments.get("confidence", "medium")
            )
            return [TextContent(type="text", text=result)]

        elif name == "explain_table":
            inspector = SchemaInspector(conn_manager)
            result = await inspector.explain_table(
                table=arguments["table"],
                sample_rows=arguments.get("sample_rows", 5)
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "query":
            executor = QueryExecutor(conn_manager)
            result = await executor.execute(
                sql=arguments["sql"],
                max_rows=min(arguments.get("max_rows", 100), 1000)
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

        elif name == "search_columns":
            inspector = SchemaInspector(conn_manager)
            result = await inspector.search_columns(arguments["pattern"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "disconnect":
            result = await conn_manager.disconnect()
            return [TextContent(type="text", text=result)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"Tool {name} error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ Error in {name}: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
