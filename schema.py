"""
Schema Inspector
Queries Oracle data dictionary views to introspect tables, columns, and stats.
Designed for 500+ table schemas with pagination.
"""

import logging
from typing import Optional
import oracledb

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


class SchemaInspector:
    def __init__(self, conn_manager):
        self.conn_manager = conn_manager

    def _cursor(self):
        return self.conn_manager.get_connection().cursor()

    def _owner_clause(self, alias: str = "t") -> tuple[str, list]:
        """Returns WHERE clause fragment and bind vars for schema filtering."""
        schema = self.conn_manager.get_schema()
        if schema:
            return f"{alias}.owner = :owner", [schema.upper()]
        else:
            return f"{alias}.owner = SYS_CONTEXT('USERENV','CURRENT_SCHEMA')", []

    async def get_schema(self, filter_pattern: Optional[str] = None, page: int = 1) -> dict:
        owner_clause, binds = self._owner_clause("t")
        offset = (page - 1) * PAGE_SIZE

        filter_clause = ""
        if filter_pattern:
            pattern = filter_pattern.upper().replace("*", "%")
            if "%" not in pattern:
                pattern = pattern + "%"
            filter_clause = "AND t.table_name LIKE :tname"
            binds.append(pattern)

        # Paginated table list with row counts
        table_sql = f"""
            SELECT t.table_name, t.num_rows, t.last_analyzed
            FROM all_tables t
            WHERE {owner_clause}
            {filter_clause}
            ORDER BY t.table_name
            OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY
        """
        binds_table = binds + [offset, PAGE_SIZE]

        with self._cursor() as cur:
            cur.execute(table_sql, binds_table)
            tables = [{"table": r[0], "num_rows": r[1], "last_analyzed": str(r[2])} for r in cur.fetchall()]

            if not tables:
                return {"page": page, "page_size": PAGE_SIZE, "tables": [], "message": "No tables found."}

            table_names = [t["table"] for t in tables]

            # Get columns for all tables in this page in one query
            placeholders = ",".join([f":t{i}" for i in range(len(table_names))])
            owner_col_clause, binds_col = self._owner_clause("c")
            col_sql = f"""
                SELECT c.table_name, c.column_name, c.data_type, c.data_length,
                       c.data_precision, c.data_scale, c.nullable, c.column_id
                FROM all_tab_columns c
                WHERE {owner_col_clause}
                AND c.table_name IN ({placeholders})
                ORDER BY c.table_name, c.column_id
            """
            col_binds = binds_col + table_names
            cur.execute(col_sql, col_binds)
            col_rows = cur.fetchall()

        # Group columns by table
        cols_by_table: dict[str, list] = {t["table"]: [] for t in tables}
        for row in col_rows:
            tname, cname, dtype, dlen, dprec, dscale, nullable, col_id = row
            if tname in cols_by_table:
                type_str = dtype
                if dtype in ("VARCHAR2", "NVARCHAR2", "CHAR"):
                    type_str = f"{dtype}({dlen})"
                elif dtype == "NUMBER" and dprec:
                    type_str = f"NUMBER({dprec},{dscale or 0})"
                cols_by_table[tname].append({
                    "column": cname,
                    "type": type_str,
                    "nullable": nullable == "Y"
                })

        for t in tables:
            t["columns"] = cols_by_table[t["table"]]

        # Total count
        count_sql = f"""
            SELECT COUNT(*) FROM all_tables t
            WHERE {owner_clause} {filter_clause}
        """
        with self._cursor() as cur:
            cur.execute(count_sql, binds)
            total = cur.fetchone()[0]

        return {
            "page": page,
            "page_size": PAGE_SIZE,
            "total_tables": total,
            "total_pages": (total + PAGE_SIZE - 1) // PAGE_SIZE,
            "tables": tables
        }

    async def get_all_table_columns(self, tables: Optional[list] = None) -> dict[str, list]:
        """Returns {table_name: [column_names]} — used by relationship inferer."""
        owner_clause, binds = self._owner_clause("c")

        table_filter = ""
        if tables:
            placeholders = ",".join([f":t{i}" for i in range(len(tables))])
            table_filter = f"AND c.table_name IN ({placeholders})"
            binds += [t.upper() for t in tables]

        sql = f"""
            SELECT c.table_name, c.column_name, c.data_type
            FROM all_tab_columns c
            WHERE {owner_clause}
            {table_filter}
            ORDER BY c.table_name, c.column_id
        """
        result: dict[str, list] = {}
        with self._cursor() as cur:
            cur.execute(sql, binds)
            for table_name, col_name, data_type in cur.fetchall():
                if table_name not in result:
                    result[table_name] = []
                result[table_name].append({"column": col_name, "type": data_type})

        return result

    async def explain_table(self, table: str, sample_rows: int = 5) -> dict:
        table = table.upper()
        owner_clause, binds = self._owner_clause("t")

        result = {"table": table}

        with self._cursor() as cur:
            # Row count + last analyzed
            cur.execute(
                f"SELECT num_rows, last_analyzed FROM all_tables t WHERE {owner_clause} AND t.table_name = :tname",
                binds + [table]
            )
            row = cur.fetchone()
            if not row:
                return {"error": f"Table {table} not found in schema."}
            result["num_rows_stats"] = row[0]
            result["last_analyzed"] = str(row[1])

            # Exact count (if table not too large)
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                result["num_rows_exact"] = cur.fetchone()[0]
            except Exception:
                result["num_rows_exact"] = "N/A (query failed)"

            # Column stats
            owner_col_clause, col_binds = self._owner_clause("c")
            cur.execute(f"""
                SELECT c.column_name, c.data_type, c.nullable,
                       c.num_distinct, c.num_nulls, c.low_value, c.high_value
                FROM all_tab_col_statistics c
                WHERE {owner_col_clause} AND c.table_name = :tname
                ORDER BY c.column_id
            """, col_binds + [table])
            col_stats = []
            for r in cur.fetchall():
                col_stats.append({
                    "column": r[0],
                    "type": r[1],
                    "nullable": r[2] == "Y",
                    "distinct_values": r[3],
                    "null_count": r[4]
                })
            result["column_stats"] = col_stats

            # Sample rows
            try:
                cur.execute(f"SELECT * FROM {table} FETCH FIRST :n ROWS ONLY", [sample_rows])
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                result["sample_data"] = {"columns": cols, "rows": rows}
            except Exception as e:
                result["sample_data"] = {"error": str(e)}

            # Indexes
            owner_idx_clause, idx_binds = self._owner_clause("i")
            cur.execute(f"""
                SELECT i.index_name, i.uniqueness, ic.column_name
                FROM all_indexes i
                JOIN all_ind_columns ic ON ic.index_name = i.index_name AND ic.table_owner = i.owner
                WHERE {owner_idx_clause} AND i.table_name = :tname
                ORDER BY i.index_name, ic.column_position
            """, idx_binds + [table])
            indexes: dict = {}
            for iname, uniqueness, col in cur.fetchall():
                if iname not in indexes:
                    indexes[iname] = {"unique": uniqueness == "UNIQUE", "columns": []}
                indexes[iname]["columns"].append(col)
            result["indexes"] = list(indexes.values())

        return result

    async def search_columns(self, pattern: str) -> list[dict]:
        pattern = pattern.upper().replace("*", "%")
        if "%" not in pattern:
            pattern = f"%{pattern}%"

        owner_clause, binds = self._owner_clause("c")
        sql = f"""
            SELECT c.table_name, c.column_name, c.data_type, c.nullable
            FROM all_tab_columns c
            WHERE {owner_clause}
            AND c.column_name LIKE :pattern
            ORDER BY c.table_name, c.column_id
        """
        with self._cursor() as cur:
            cur.execute(sql, binds + [pattern])
            return [
                {"table": r[0], "column": r[1], "type": r[2], "nullable": r[3] == "Y"}
                for r in cur.fetchall()
            ]
