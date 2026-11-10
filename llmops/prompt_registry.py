"""Planned module: prompt registry. Implementation pending."""

"""
ai/llmops/prompt_registry.py

Prompt registry for Autonomous Retail
Supply Chain AI 5.0.

Features:
- Centralized prompt templates
- Agent-specific prompt management
- Strict variable validation
- Safe template rendering
- Prompt metadata and ownership
- Draft and production stages
- SHA-256 content integrity
- SQLite persistence
- Prompt discovery
- Audit history
- Integration with prompt_versioning.py

Security:
- No eval(), exec() or dynamic expressions
- No arbitrary Python format attributes
- No automatic production promotion
- No secrets in prompt templates
- Rendering values are treated as data
- Registry writes require trusted callers

Standard library only. Python 3.10+.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import string
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


PROMPT_STAGES = {
    "draft",
    "staging",
    "production",
    "archived",
}

PROMPT_ROLES = {
    "system",
    "developer",
    "user",
}

NAME_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]{0,127}$"
)


@dataclass(frozen=True)
class PromptRegistryConfig:
    database_path: str = "data/llmops/prompts.db"
    max_template_length: int = 100_000
    max_rendered_length: int = 200_000


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    name: str
    agent_name: str
    role: str
    template: str
    description: str
    owner: str
    variables: tuple[str, ...]
    stage: str = "draft"

    def __post_init__(self):
        if not NAME_PATTERN.fullmatch(self.prompt_id):
            raise ValueError("Invalid prompt ID")

        if not NAME_PATTERN.fullmatch(self.agent_name):
            raise ValueError("Invalid agent name")

        if self.role not in PROMPT_ROLES:
            raise ValueError("Invalid prompt role")

        if self.stage not in PROMPT_STAGES:
            raise ValueError("Invalid prompt stage")

        if not self.name.strip() or not self.owner.strip():
            raise ValueError("Prompt name and owner required")

        if not self.template.strip():
            raise ValueError("Prompt template cannot be empty")

        if len(self.variables) != len(set(self.variables)):
            raise ValueError("Duplicate template variables")

        for variable in self.variables:
            if not NAME_PATTERN.fullmatch(variable):
                raise ValueError(
                    f"Invalid variable name: {variable}"
                )


class PromptRegistry:

    def __init__(
        self,
        config: PromptRegistryConfig | None = None,
    ):
        self.config = config or PromptRegistryConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS prompts (
                prompt_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                role TEXT NOT NULL,
                template TEXT NOT NULL,
                description TEXT NOT NULL,
                owner TEXT NOT NULL,
                variables_json TEXT NOT NULL,
                stage TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_prompts_agent
            ON prompts(agent_name, stage);

            CREATE TABLE IF NOT EXISTS prompt_registry_audit (
                audit_id TEXT PRIMARY KEY,
                prompt_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    @staticmethod
    def checksum(template: str) -> str:
        return hashlib.sha256(
            template.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def extract_variables(
        template: str,
    ) -> tuple[str, ...]:
        formatter = string.Formatter()
        variables = []

        for _, field_name, format_spec, conversion in (
            formatter.parse(template)
        ):
            if field_name is None:
                continue

            # Prevent attribute/index traversal,
            # conversion and custom format logic.
            if (
                not NAME_PATTERN.fullmatch(field_name)
                or format_spec
                or conversion
            ):
                raise ValueError(
                    "Only simple {variable} fields are allowed"
                )

            if field_name not in variables:
                variables.append(field_name)

        return tuple(variables)

    def register(
        self,
        prompt: PromptTemplate,
        actor: str,
    ) -> dict:
        if not actor.strip():
            raise ValueError("Actor required")

        if (
            len(prompt.template)
            > self.config.max_template_length
        ):
            raise ValueError("Template too long")

        actual_variables = self.extract_variables(
            prompt.template
        )

        if set(actual_variables) != set(prompt.variables):
            raise ValueError(
                "Declared variables do not match template"
            )

        # Production deployment is handled by
        # prompt_versioning.py with approval.
        if prompt.stage == "production":
            raise ValueError(
                "Register as draft or staging; "
                "production requires approved version promotion"
            )

        timestamp = utc_now()
        digest = self.checksum(prompt.template)

        with self.db:
            self.db.execute(
                """
                INSERT INTO prompts (
                    prompt_id, name, agent_name,
                    role, template, description,
                    owner, variables_json, stage,
                    checksum, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt.prompt_id,
                    prompt.name,
                    prompt.agent_name,
                    prompt.role,
                    prompt.template,
                    prompt.description,
                    prompt.owner,
                    json.dumps(prompt.variables),
                    prompt.stage,
                    digest,
                    timestamp,
                    timestamp,
                ),
            )

            self._audit(
                prompt.prompt_id,
                "registered",
                actor,
            )

        return {
            "prompt_id": prompt.prompt_id,
            "registered": True,
            "stage": prompt.stage,
            "checksum": digest,
        }

    def _audit(
        self,
        prompt_id: str,
        action: str,
        actor: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO prompt_registry_audit (
                audit_id, prompt_id,
                action, actor, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                prompt_id,
                action,
                actor,
                utc_now(),
            ),
        )

    def get(
        self,
        prompt_id: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM prompts
            WHERE prompt_id = ?
            """,
            (prompt_id,),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["variables"] = json.loads(
            result.pop("variables_json")
        )

        if self.checksum(result["template"]) != (
            result["checksum"]
        ):
            raise RuntimeError(
                "Prompt content integrity check failed"
            )

        return result

    def list_prompts(
        self,
        agent_name: str | None = None,
        stage: str | None = None,
    ) -> list[dict]:
        if stage is not None and stage not in PROMPT_STAGES:
            raise ValueError("Invalid stage")

        query = "SELECT prompt_id FROM prompts WHERE 1=1"
        params = []

        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)

        if stage:
            query += " AND stage = ?"
            params.append(stage)

        query += " ORDER BY agent_name, name"

        rows = self.db.execute(
            query, params
        ).fetchall()

        return [
            self.get(row["prompt_id"])
            for row in rows
        ]

    def render(
        self,
        prompt_id: str,
        variables: dict[str, Any],
    ) -> dict:
        prompt = self.get(prompt_id)

        if prompt is None:
            raise ValueError("Unknown prompt")

        if not isinstance(variables, dict):
            raise ValueError("Variables must be a dictionary")

        expected = set(prompt["variables"])
        supplied = set(variables)

        if supplied != expected:
            raise ValueError(
                f"Variable mismatch. Missing: "
                f"{sorted(expected - supplied)}; "
                f"Unexpected: {sorted(supplied - expected)}"
            )

        safe_values = {}

        for key, value in variables.items():
            if not isinstance(
                value, (str, int, float, bool)
            ):
                raise ValueError(
                    f"Unsupported value for {key}"
                )

            safe_values[key] = str(value)

        rendered = prompt["template"].format_map(
            safe_values
        )

        if (
            len(rendered)
            > self.config.max_rendered_length
        ):
            raise ValueError(
                "Rendered prompt exceeds maximum length"
            )

        return {
            "prompt_id": prompt_id,
            "role": prompt["role"],
            "content": rendered,
            "template_checksum": prompt["checksum"],
            "stage": prompt["stage"],
        }

    def search(self, query: str) -> list[dict]:
        query = query.strip().casefold()

        if not query:
            return []

        results = []

        for prompt in self.list_prompts():
            searchable = " ".join([
                prompt["name"],
                prompt["agent_name"],
                prompt["description"],
                prompt["owner"],
            ]).casefold()

            if query in searchable:
                results.append(prompt)

        return results

    def audit_history(
        self,
        prompt_id: str,
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT *
            FROM prompt_registry_audit
            WHERE prompt_id = ?
            ORDER BY created_at, audit_id
            """,
            (prompt_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        self.db.close()


if __name__ == "__main__":
    registry = PromptRegistry()

    prompt = PromptTemplate(
        prompt_id="inventory_analysis",
        name="Inventory Analysis Assistant",
        agent_name="inventory_agent",
        role="system",
        description=(
            "Grounded inventory analysis prompt"
        ),
        owner="retail_ai_team",
        template=(
            "You are an inventory analysis assistant.\n"
            "Use only authorized inventory data.\n"
            "Warehouse: {warehouse_id}\n"
            "Available stock: {available_stock}\n"
            "Demand forecast: {forecast_units}\n"
            "Explain recommendations with evidence.\n"
            "Never execute purchases without approval."
        ),
        variables=(
            "warehouse_id",
            "available_stock",
            "forecast_units",
        ),
    )

    try:
        print(
            registry.register(
                prompt,
                actor="mlops_engineer",
            )
        )
    except sqlite3.IntegrityError:
        print("Prompt already registered")

    result = registry.render(
        "inventory_analysis",
        {
            "warehouse_id": "WH-KOCHI",
            "available_stock": 160,
            "forecast_units": 220,
        },
    )

    print(json.dumps(result, indent=2))

    registry.close()
