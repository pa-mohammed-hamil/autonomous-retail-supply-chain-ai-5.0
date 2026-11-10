"""Planned module: hallucination monitor. Implementation pending."""

"""
ai/llmops/feedback_loop.py

Human feedback and continuous improvement
pipeline for Autonomous Retail Supply Chain AI.

Features:
- User feedback collection
- Human review workflow
- Feedback categorization
- Error and hallucination reports
- Agent performance feedback
- Training candidate selection
- Dataset export
- PII-safe storage
- Reviewer approvals
- Feedback statistics
- Audit history
- SQLite persistence

Important:
- No automatic model retraining
- No automatic production deployment
- Training exports require human approval
- Raw customer conversations are not stored
- Human feedback is not automatically treated
  as verified ground truth

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FEEDBACK_CATEGORIES = {
    "incorrect_answer",
    "hallucination",
    "missing_citation",
    "wrong_tool",
    "unsafe_response",
    "poor_relevance",
    "slow_response",
    "workflow_failure",
    "positive_feedback",
    "other",
}

REVIEW_STATUSES = {
    "pending",
    "approved",
    "rejected",
    "needs_investigation",
}

RATINGS = {1, 2, 3, 4, 5}


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class FeedbackLoopConfig:
    database_path: str = "data/llmops/feedback.db"
    export_directory: str = "data/llmops/approved_feedback"
    max_feedback_length: int = 2000
    require_review: bool = True


class FeedbackLoop:

    def __init__(
        self,
        config: FeedbackLoopConfig | None = None,
    ):
        self.config = config or FeedbackLoopConfig()

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

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                rating INTEGER NOT NULL,
                category TEXT NOT NULL,
                feedback_text TEXT NOT NULL,
                user_reference_hash TEXT,
                review_status TEXT NOT NULL,
                reviewer TEXT,
                review_reason TEXT,
                training_eligible INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (feedback_id)
                    REFERENCES feedback(feedback_id)
            );
        """)

        self.db.commit()

    @staticmethod
    def _hash_reference(
        user_reference: str | None,
    ) -> str | None:
        if not user_reference:
            return None

        # Pseudonymous reference, not guaranteed
        # anonymous. Use an HMAC with a secret key
        # in production to resist enumeration.
        return hashlib.sha256(
            user_reference.encode("utf-8")
        ).hexdigest()

    def submit_feedback(
        self,
        trace_id: str,
        agent_name: str,
        model: str,
        rating: int,
        category: str,
        feedback_text: str,
        user_reference: str | None = None,
        feedback_id: str | None = None,
    ) -> dict:
        if category not in FEEDBACK_CATEGORIES:
            raise ValueError(
                "Unsupported feedback category"
            )

        if (
            isinstance(rating, bool)
            or rating not in RATINGS
        ):
            raise ValueError(
                "Rating must be 1 to 5"
            )

        for value in (
            trace_id,
            agent_name,
            model,
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(
                    "Missing required metadata"
                )

        if not isinstance(feedback_text, str):
            raise ValueError(
                "Feedback text must be a string"
            )

        if (
            len(feedback_text)
            > self.config.max_feedback_length
        ):
            raise ValueError(
                "Feedback exceeds maximum length"
            )

        feedback_id = (
            feedback_id or uuid.uuid4().hex
        )

        # Feedback text should be redacted before
        # submission. Never store secrets or PII.
        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO feedback (
                    feedback_id,
                    trace_id,
                    agent_name,
                    model,
                    rating,
                    category,
                    feedback_text,
                    user_reference_hash,
                    review_status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    trace_id,
                    agent_name,
                    model,
                    rating,
                    category,
                    feedback_text,
                    self._hash_reference(
                        user_reference
                    ),
                    "pending",
                    utc_now(),
                ),
            )

            if cursor.rowcount:
                self.db.execute(
                    """
                    INSERT INTO feedback_audit (
                        feedback_id,
                        action,
                        actor,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        feedback_id,
                        "submitted",
                        "feedback_system",
                        utc_now(),
                    ),
                )

        return {
            "feedback_id": feedback_id,
            "submitted": cursor.rowcount == 1,
            "review_status": "pending",
        }

    def review_feedback(
        self,
        feedback_id: str,
        reviewer: str,
        decision: str,
        reason: str,
        training_eligible: bool = False,
    ) -> dict:
        if decision not in REVIEW_STATUSES - {
            "pending"
        }:
            raise ValueError(
                "Invalid review decision"
            )

        if not reviewer.strip():
            raise ValueError(
                "Reviewer required"
            )

        if not reason.strip():
            raise ValueError(
                "Review reason required"
            )

        if (
            training_eligible
            and decision != "approved"
        ):
            raise ValueError(
                "Only approved feedback can be training eligible"
            )

        with self.db:
            cursor = self.db.execute(
                """
                UPDATE feedback
                SET review_status = ?,
                    reviewer = ?,
                    review_reason = ?,
                    training_eligible = ?,
                    reviewed_at = ?
                WHERE feedback_id = ?
                  AND review_status = 'pending'
                """,
                (
                    decision,
                    reviewer,
                    reason,
                    int(training_eligible),
                    utc_now(),
                    feedback_id,
                ),
            )

            if cursor.rowcount:
                self.db.execute(
                    """
                    INSERT INTO feedback_audit (
                        feedback_id,
                        action,
                        actor,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        feedback_id,
                        f"reviewed:{decision}",
                        reviewer,
                        utc_now(),
                    ),
                )

        return {
            "feedback_id": feedback_id,
            "updated": cursor.rowcount == 1,
            "decision": decision,
            "training_eligible": (
                training_eligible
                if cursor.rowcount
                else False
            ),
        }

    def get_feedback(
        self,
        feedback_id: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM feedback
            WHERE feedback_id = ?
            """,
            (feedback_id,),
        ).fetchone()

        return dict(row) if row else None

    def list_feedback(
        self,
        status: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if status is not None:
            if status not in REVIEW_STATUSES:
                raise ValueError("Invalid status")

        if category is not None:
            if category not in FEEDBACK_CATEGORIES:
                raise ValueError("Invalid category")

        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        query = "SELECT * FROM feedback WHERE 1=1"
        params = []

        if status:
            query += " AND review_status = ?"
            params.append(status)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(
            query,
            params,
        ).fetchall()

        return [dict(row) for row in rows]

    def statistics(self) -> dict:
        rows = self.db.execute(
            "SELECT * FROM feedback"
        ).fetchall()

        if not rows:
            return {
                "total_feedback": 0,
                "average_rating": None,
                "categories": {},
                "review_statuses": {},
            }

        categories = {}
        statuses = {}
        agents = {}

        for row in rows:
            category = row["category"]
            status = row["review_status"]
            agent = row["agent_name"]

            categories[category] = (
                categories.get(category, 0) + 1
            )

            statuses[status] = (
                statuses.get(status, 0) + 1
            )

            agents.setdefault(
                agent,
                {"count": 0, "rating_sum": 0},
            )

            agents[agent]["count"] += 1
            agents[agent]["rating_sum"] += (
                row["rating"]
            )

        for metrics in agents.values():
            metrics["average_rating"] = round(
                metrics["rating_sum"]
                / metrics["count"],
                3,
            )
            del metrics["rating_sum"]

        return {
            "total_feedback": len(rows),
            "average_rating": round(
                sum(row["rating"] for row in rows)
                / len(rows),
                3,
            ),
            "categories": categories,
            "review_statuses": statuses,
            "agents": agents,
            "training_eligible_count": sum(
                bool(row["training_eligible"])
                for row in rows
            ),
        }

    def export_training_candidates(
        self,
        approved_by: str,
        filename: str = "feedback_candidates.jsonl",
    ) -> dict:
        """
        Export metadata for human-curated training.

        This is NOT a complete supervised
        fine-tuning dataset. It contains no
        prompts or model answers.

        A separate approved curation process
        must verify source material, consent,
        licenses and ground-truth labels.
        """

        if not approved_by.strip():
            raise ValueError(
                "Export approval required"
            )

        if (
            "/" in filename
            or "\\" in filename
            or not filename.endswith(".jsonl")
        ):
            raise ValueError(
                "Invalid export filename"
            )

        rows = self.db.execute(
            """
            SELECT *
            FROM feedback
            WHERE review_status = 'approved'
              AND training_eligible = 1
            ORDER BY created_at
            """
        ).fetchall()

        directory = Path(
            self.config.export_directory
        ).resolve()

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output = directory / filename

        # Only structured metadata is exported.
        # Feedback text is excluded to avoid
        # accidental PII leakage.
        with output.open(
            "w", encoding="utf-8"
        ) as handle:
            for row in rows:
                record = {
                    "feedback_id": row["feedback_id"],
                    "trace_id": row["trace_id"],
                    "agent_name": row["agent_name"],
                    "model": row["model"],
                    "rating": row["rating"],
                    "category": row["category"],
                    "reviewer": row["reviewer"],
                    "review_reason": row["review_reason"],
                    "training_eligible": True,
                }

                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    ) + "\n"
                )

        return {
            "exported": True,
            "path": str(output),
            "record_count": len(rows),
            "approved_by": approved_by,
            "contains_raw_conversations": False,
            "ready_for_training": False,
        }

    def audit_history(
        self,
        feedback_id: str,
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT *
            FROM feedback_audit
            WHERE feedback_id = ?
            ORDER BY audit_id
            """,
            (feedback_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        self.db.close()


if __name__ == "__main__":
    feedback = FeedbackLoop()

    result = feedback.submit_feedback(
        trace_id="trace-retail-001",
        agent_name="inventory_agent",
        model="retail-demo-llm",
        rating=2,
        category="incorrect_answer",
        feedback_text=(
            "The stock recommendation used "
            "an outdated inventory snapshot."
        ),
    )

    feedback_id = result["feedback_id"]

    print(result)

    print(
        feedback.review_feedback(
            feedback_id=feedback_id,
            reviewer="quality_reviewer",
            decision="approved",
            reason="Confirmed using inventory records",
            training_eligible=True,
        )
    )

    print(
        json.dumps(
            feedback.statistics(),
            indent=2,
        )
    )

    print(
        feedback.export_training_candidates(
            approved_by="mlops_manager"
        )
    )

    feedback.close()
