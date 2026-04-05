"""
ERD Generator
Produces Mermaid erDiagram output from tables + inferred relationships.
Claude renders Mermaid natively, so the output displays as a live diagram.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

CONFIDENCE_STYLES = {
    "high":   "||--o{",   # solid line, many
    "medium": "|o--o{",   # optional on one side
    "low":    "}o--o{",   # optional both sides
}


class ERDGenerator:
    def __init__(self, schema_inspector, relationship_inferer):
        self.inspector = schema_inspector
        self.inferer = relationship_inferer

    async def generate(
        self,
        tables: list[str],
        include_columns: bool = True,
        min_confidence: str = "medium"
    ) -> str:
        tables = [t.upper() for t in tables]

        # Load columns for requested tables
        all_cols = await self.inspector.get_all_table_columns(tables)

        # Infer relationships scoped to these tables
        rel_result = await self.inferer.infer(tables=tables, min_confidence=min_confidence)
        relationships = rel_result["relationships"]

        # Filter relationships to only those between the selected tables
        table_set = set(tables)
        filtered_rels = [
            r for r in relationships
            if r["from_table"] in table_set and r["to_table"] in table_set
        ]

        lines = ["```mermaid", "erDiagram"]

        # Entity definitions
        for table in tables:
            cols = all_cols.get(table, [])
            if include_columns and cols:
                lines.append(f"    {table} {{")
                for col in cols[:30]:  # cap at 30 cols per table for readability
                    # Sanitize type for Mermaid (no parentheses)
                    dtype = col["type"].split("(")[0]
                    nullable = "" if col.get("nullable", True) else " PK"
                    lines.append(f'        {dtype} {col["column"]}{nullable}')
                if len(cols) > 30:
                    lines.append(f"        -- ...{len(cols) - 30} more columns --")
                lines.append("    }")
            else:
                lines.append(f"    {table} {{")
                lines.append("    }")

        lines.append("")

        # Relationships
        seen_rels = set()
        for rel in filtered_rels:
            ft = rel["from_table"]
            fc = rel["from_column"]
            tt = rel["to_table"]
            tc = rel["to_column"]
            conf = rel["confidence"]
            style = CONFIDENCE_STYLES.get(conf, "|o--o{")

            # Deduplicate bidirectional
            key = tuple(sorted([f"{ft}.{fc}", f"{tt}.{tc}"]))
            if key in seen_rels:
                continue
            seen_rels.add(key)

            label = f"{fc}"
            lines.append(f'    {tt} {style} {ft} : "{label}"')

        lines.append("```")

        # Summary footer
        lines.append("")
        lines.append(f"**Tables:** {len(tables)} | **Inferred relationships:** {len(seen_rels)} | **Min confidence:** {min_confidence}")
        if filtered_rels:
            high = sum(1 for r in filtered_rels if r["confidence"] == "high")
            med = sum(1 for r in filtered_rels if r["confidence"] == "medium")
            low = sum(1 for r in filtered_rels if r["confidence"] == "low")
            lines.append(f"**Relationship breakdown:** {high} high · {med} medium · {low} low confidence")

        return "\n".join(lines)
