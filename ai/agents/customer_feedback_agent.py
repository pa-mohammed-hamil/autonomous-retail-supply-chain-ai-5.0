"""Planned module: customer feedback agent. Implementation pending."""

"""
Customer Feedback Intelligence Agent
Autonomous Retail Supply Chain AI 5.0

Features:
- Review and complaint analysis
- Rule-based sentiment detection
- Rating-aware sentiment scoring
- Complaint category identification
- Product-level feedback summaries
- Recurring issue detection
- Escalation recommendations
- Tenant-isolated feedback storage
- BaseAgent integration

Python 3.10+
Standard library only.

This is a lightweight baseline, not a trained
sentiment or multilingual NLP model.
"""

from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentContext,
    AgentValidationError,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CustomerFeedbackAgent(BaseAgent):

    POSITIVE_WORDS = {
        "good", "great", "excellent", "amazing",
        "perfect", "fast", "helpful", "fresh",
        "reliable", "satisfied", "love", "quality",
    }

    NEGATIVE_WORDS = {
        "bad", "poor", "broken", "damaged",
        "late", "delay", "defective", "expired",
        "missing", "wrong", "terrible",
        "disappointed", "refund", "unsafe",
    }

    ISSUE_KEYWORDS = {
        "delivery": {
            "late", "delay", "delivery",
            "shipping", "courier",
        },
        "product_quality": {
            "broken", "damaged", "defective",
            "expired", "quality", "unsafe",
        },
        "pricing": {
            "expensive", "overpriced",
            "price", "cost",
        },
        "inventory": {
            "stockout", "unavailable",
            "out of stock", "missing",
        },
        "customer_service": {
            "support", "staff", "service",
            "response", "rude",
        },
        "returns": {
            "refund", "return", "replacement",
        },
    }

    def __init__(
        self,
        working_memory: Any | None = None,
        escalation_threshold: int = 3,
    ) -> None:
        super().__init__(
            agent_id="customer_feedback_agent",
            name="Customer Feedback Intelligence Agent",
            capabilities={
                "analyze_feedback",
                "batch_feedback_analysis",
                "product_feedback_summary",
                "feedback_trends",
            },
            working_memory=working_memory,
        )

        if (
            isinstance(escalation_threshold, bool)
            or not isinstance(escalation_threshold, int)
            or escalation_threshold <= 0
        ):
            raise ValueError(
                "escalation_threshold must be positive."
            )

        self.escalation_threshold = escalation_threshold
        self._feedback: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(
            r"[a-z]+(?:'[a-z]+)?",
            text.lower(),
        )

    def _sentiment(
        self,
        text: str,
        rating: int | None,
    ) -> dict[str, Any]:
        tokens = self._tokens(text)

        positive = sum(
            token in self.POSITIVE_WORDS
            for token in tokens
        )

        negative = sum(
            token in self.NEGATIVE_WORDS
            for token in tokens
        )

        score = positive - negative

        if rating is not None:
            score += rating - 3

        if score > 0:
            label = "positive"
        elif score < 0:
            label = "negative"
        else:
            label = "neutral"

        return {
            "label": label,
            "score": score,
            "positive_matches": positive,
            "negative_matches": negative,
            "method": "keyword_rating_baseline",
        }

    def _categories(self, text: str) -> list[str]:
        normalized = text.lower()
        tokens = set(self._tokens(text))
        categories = []

        for category, keywords in (
            self.ISSUE_KEYWORDS.items()
        ):
            if any(
                keyword in tokens
                if " " not in keyword
                else keyword in normalized
                for keyword in keywords
            ):
                categories.append(category)

        return categories

    def _analyze(
        self,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        product_id = payload.get("product_id")
        feedback_text = payload.get("feedback_text")
        rating = payload.get("rating")

        if (
            not isinstance(product_id, str)
            or not product_id.strip()
        ):
            raise AgentValidationError(
                "product_id is required."
            )

        if (
            not isinstance(feedback_text, str)
            or not feedback_text.strip()
        ):
            raise AgentValidationError(
                "feedback_text is required."
            )

        if rating is not None and (
            isinstance(rating, bool)
            or not isinstance(rating, int)
            or not 1 <= rating <= 5
        ):
            raise AgentValidationError(
                "rating must be an integer from 1 to 5."
            )

        feedback_id = payload.get("feedback_id") or str(
            uuid4()
        )

        if (
            not isinstance(feedback_id, str)
            or not feedback_id.strip()
        ):
            raise AgentValidationError(
                "Invalid feedback_id."
            )

        sentiment = self._sentiment(
            feedback_text,
            rating,
        )

        categories = self._categories(feedback_text)

        urgent = (
            "unsafe" in self._tokens(feedback_text)
            or "expired" in self._tokens(feedback_text)
        )

        result = {
            "feedback_id": feedback_id,
            "tenant_id": tenant_id,
            "product_id": product_id,
            "rating": rating,
            "sentiment": sentiment,
            "issue_categories": categories,
            "urgent_safety_review": urgent,
            "analyzed_at": utc_now(),
        }

        key = f"{tenant_id}:{feedback_id}"

        with self._lock:
            existing = self._feedback.get(key)

            if existing is not None:
                raise AgentValidationError(
                    "feedback_id already exists."
                )

            self._feedback[key] = result

        return result

    def _product_summary(
        self,
        tenant_id: str,
        product_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            records = [
                item.copy()
                for item in self._feedback.values()
                if item["tenant_id"] == tenant_id
                and item["product_id"] == product_id
            ]

        sentiments = Counter(
            item["sentiment"]["label"]
            for item in records
        )

        issues = Counter(
            category
            for item in records
            for category in item["issue_categories"]
        )

        ratings = [
            item["rating"]
            for item in records
            if item["rating"] is not None
        ]

        recurring = [
            category
            for category, count in issues.items()
            if count >= self.escalation_threshold
        ]

        urgent = any(
            item["urgent_safety_review"]
            for item in records
        )

        return {
            "product_id": product_id,
            "feedback_count": len(records),
            "average_rating": (
                round(sum(ratings) / len(ratings), 2)
                if ratings else None
            ),
            "sentiment_distribution": dict(sentiments),
            "issue_counts": dict(issues),
            "recurring_issues": recurring,
            "escalation_recommended": (
                bool(recurring) or urgent
            ),
            "reason": (
                "Safety-related feedback requires review."
                if urgent
                else "Recurring customer complaints."
                if recurring
                else "No configured escalation trigger."
            ),
        }

    def process(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        tenant_id = request.context.tenant_id
        task = request.task_type
        payload = request.payload

        if task == "analyze_feedback":
            return self._analyze(
                tenant_id,
                payload,
            )

        if task == "batch_feedback_analysis":
            items = payload.get("feedback_items")

            if not isinstance(items, list):
                raise AgentValidationError(
                    "feedback_items must be a list."
                )

            if len(items) > 100:
                raise AgentValidationError(
                    "Batch exceeds 100 feedback items."
                )

            results = []

            for item in items:
                if not isinstance(item, dict):
                    raise AgentValidationError(
                        "Each feedback item must be an object."
                    )

                results.append(
                    self._analyze(tenant_id, item)
                )

            return {
                "processed": len(results),
                "results": results,
            }

        if task == "product_feedback_summary":
            product_id = payload.get("product_id")

            if not isinstance(product_id, str):
                raise AgentValidationError(
                    "product_id is required."
                )

            return self._product_summary(
                tenant_id,
                product_id,
            )

        if task == "feedback_trends":
            with self._lock:
                records = [
                    item.copy()
                    for item in self._feedback.values()
                    if item["tenant_id"] == tenant_id
                ]

            categories = Counter(
                category
                for item in records
                for category in item["issue_categories"]
            )

            return {
                "total_feedback": len(records),
                "top_issue_categories": (
                    categories.most_common(10)
                ),
                "negative_feedback_count": sum(
                    item["sentiment"]["label"]
                    == "negative"
                    for item in records
                ),
            }

        raise AgentValidationError(
            "Unsupported feedback task."
        )


if __name__ == "__main__":
    agent = CustomerFeedbackAgent()

    context = AgentContext(
        tenant_id="retail_company_001",
        user_id="customer_service_manager",
        workflow_id="WF-FEEDBACK-001",
        task_id="TASK-001",
    )

    response = agent.execute(
        AgentRequest(
            task_type="analyze_feedback",
            context=context,
            payload={
                "feedback_id": "FB-1001",
                "product_id": "SKU-1001",
                "rating": 2,
                "feedback_text": (
                    "The product arrived late "
                    "and the packaging was damaged."
                ),
            },
        )
    )

    print(response)
