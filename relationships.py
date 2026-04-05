"""
Relationship Inferer
Detects likely FK relationships heuristically — no explicit constraints needed.
Strategies (in confidence order):
  HIGH   — exact column name match across tables (e.g. EMPLOYEE_ID → EMPLOYEES.EMPLOYEE_ID)
  MEDIUM — name pattern match with type compatibility (e.g. DEPT_ID → DEPARTMENTS.ID)
  LOW    — suffix/prefix conventions (_CODE, _KEY, _NO) with type match
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}

# Common ERP suffix patterns that indicate FK columns
FK_SUFFIXES = ("_ID", "_CODE", "_NO", "_NUM", "_KEY", "_REF", "_TYPE", "_FLAG", "_STATUS")

# Known ERP table → likely PK column mappings for boosting confidence
ERP_HINTS = {
    "EMPLOYEES": ["EMPLOYEE_ID"],
    "DEPARTMENTS": ["DEPARTMENT_ID"],
    "LOCATIONS": ["LOCATION_ID"],
    "COUNTRIES": ["COUNTRY_ID"],
    "REGIONS": ["REGION_ID"],
    "JOBS": ["JOB_ID"],
    "JOB_HISTORY": ["EMPLOYEE_ID"],
    "SUPPLIERS": ["SUPPLIER_ID", "VENDOR_ID"],
    "CUSTOMERS": ["CUSTOMER_ID"],
    "ORDERS": ["ORDER_ID"],
    "ORDER_LINES": ["ORDER_ID", "LINE_ID"],
    "INVOICES": ["INVOICE_ID"],
    "GL_ACCOUNTS": ["ACCOUNT_ID", "CODE_COMBINATION_ID"],
    "LEDGERS": ["LEDGER_ID"],
    "PERIODS": ["PERIOD_NAME"],
    "CURRENCIES": ["CURRENCY_CODE"],
}


class RelationshipInferer:
    def __init__(self, schema_inspector):
        self.inspector = schema_inspector
        self._cache: dict = {}

    async def infer(
        self,
        tables: Optional[list] = None,
        min_confidence: str = "medium"
    ) -> dict:
        min_score = CONFIDENCE_ORDER.get(min_confidence, 2)

        # Load schema
        all_cols = await self.inspector.get_all_table_columns(tables)
        all_tables = list(all_cols.keys())

        # Build lookup: column_name → [tables that have it]
        col_to_tables: dict[str, list] = {}
        for tname, cols in all_cols.items():
            for col in cols:
                cname = col["column"]
                col_to_tables.setdefault(cname, []).append({"table": tname, "type": col["type"]})

        # Build lookup: table → column names set
        table_col_set: dict[str, set] = {
            t: {c["column"] for c in cols} for t, cols in all_cols.items()
        }

        relationships = []

        for source_table, cols in all_cols.items():
            for col in cols:
                cname = col["column"]
                ctype = col["type"]

                # Skip obvious non-FK columns
                if cname in ("CREATED_BY", "UPDATED_BY", "LAST_UPDATED_BY",
                             "CREATION_DATE", "LAST_UPDATE_DATE", "LAST_UPDATE_LOGIN"):
                    continue

                # Strategy 1 — HIGH: column name exists in another table with same name
                # and that other table has it as a likely PK (singular form or known hint)
                for other_entry in col_to_tables.get(cname, []):
                    other_table = other_entry["table"]
                    if other_table == source_table:
                        continue
                    if not self._types_compatible(ctype, other_entry["type"]):
                        continue

                    confidence = "high" if self._is_likely_pk(cname, other_table) else "medium"
                    score = CONFIDENCE_ORDER[confidence]

                    if score >= min_score:
                        relationships.append({
                            "from_table": source_table,
                            "from_column": cname,
                            "to_table": other_table,
                            "to_column": cname,
                            "confidence": confidence,
                            "reason": "Exact column name match"
                        })

                # Strategy 2 — MEDIUM: column name ends in _ID/_CODE etc,
                # strip suffix and look for a table whose name matches
                if not any(cname.endswith(sfx) for sfx in FK_SUFFIXES):
                    continue

                for suffix in FK_SUFFIXES:
                    if not cname.endswith(suffix):
                        continue
                    base = cname[: -len(suffix)]  # e.g. EMPLOYEE from EMPLOYEE_ID

                    # Candidate table names: exact, plural, with underscores
                    candidates = [
                        base,
                        base + "S",
                        base + "ES",
                        base.rstrip("S"),
                    ]
                    for candidate in candidates:
                        if candidate in table_col_set:
                            # Look for ID or primary-looking column in target
                            target_pk = self._find_pk_column(candidate, table_col_set[candidate])
                            if target_pk is None:
                                continue
                            target_type = next(
                                (c["type"] for c in all_cols[candidate] if c["column"] == target_pk),
                                None
                            )
                            if not self._types_compatible(ctype, target_type or "NUMBER"):
                                continue
                            if CONFIDENCE_ORDER["medium"] >= min_score:
                                relationships.append({
                                    "from_table": source_table,
                                    "from_column": cname,
                                    "to_table": candidate,
                                    "to_column": target_pk,
                                    "confidence": "medium",
                                    "reason": f"Name pattern: {cname} → {candidate}.{target_pk}"
                                })

        # Deduplicate
        seen = set()
        unique_rels = []
        for r in relationships:
            key = (r["from_table"], r["from_column"], r["to_table"], r["to_column"])
            if key not in seen:
                seen.add(key)
                unique_rels.append(r)

        # Sort by confidence desc
        unique_rels.sort(key=lambda r: CONFIDENCE_ORDER[r["confidence"]], reverse=True)

        return {
            "total_relationships": len(unique_rels),
            "min_confidence": min_confidence,
            "relationships": unique_rels
        }

    def _is_likely_pk(self, col_name: str, table_name: str) -> bool:
        """Check if col_name is likely the primary key of table_name."""
        # ERP hints
        if table_name in ERP_HINTS and col_name in ERP_HINTS[table_name]:
            return True
        # Heuristic: table_name (singular) + _ID
        singular = table_name.rstrip("S")
        if col_name in (f"{singular}_ID", f"{table_name}_ID", "ID"):
            return True
        return False

    def _find_pk_column(self, table_name: str, columns: set) -> Optional[str]:
        """Best guess at the PK column of a table given its column set."""
        singular = table_name.rstrip("S")
        candidates = [
            f"{singular}_ID",
            f"{table_name}_ID",
            "ID",
            f"{singular}_CODE",
            f"{singular}_NO",
        ]
        for c in candidates:
            if c in columns:
                return c
        # Check ERP hints
        if table_name in ERP_HINTS:
            for hint in ERP_HINTS[table_name]:
                if hint in columns:
                    return hint
        return None

    def _types_compatible(self, t1: str, t2: str) -> bool:
        """Loosely check if two Oracle types could join."""
        numeric = {"NUMBER", "INTEGER", "INT", "FLOAT"}
        string = {"VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "CLOB"}

        def base(t):
            return re.split(r"[\(\s]", t)[0].upper()

        b1, b2 = base(t1), base(t2)
        if b1 == b2:
            return True
        if b1 in numeric and b2 in numeric:
            return True
        if b1 in string and b2 in string:
            return True
        return False
