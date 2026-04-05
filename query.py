"""
Query Executor
Read-only SQL execution with safety checks.
"""

import logging
import re

logger = logging.getLogger(__name__)

FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|EXECUTE|EXEC|GRANT|REVOKE|COMMIT|ROLLBACK)\b",
    re.IGNORECASE
)


class QueryExecutor:
    def __init__(self, conn_manager):
        self.conn_manager = conn_manager

    def _cursor(self):
        return self.conn_manager.get_connection().cursor()

    async def execute(self, sql: str, max_rows: int = 100) -> dict:
        # Safety check
        stripped = sql.strip()
        if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
            return {"error": "Only SELECT and WITH (CTE) statements are permitted."}

        if FORBIDDEN_PATTERNS.search(stripped):
            return {"error": "Query contains forbidden DML/DDL keywords."}

        try:
            with self._cursor() as cur:
                cur.execute(sql)
                columns = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows)
                fetched = len(rows)
                rows_out = [dict(zip(columns, row)) for row in rows]

            return {
                "columns": columns,
                "rows": rows_out,
                "row_count": fetched,
                "truncated": fetched == max_rows
            }
        except Exception as e:
            return {"error": str(e)}
