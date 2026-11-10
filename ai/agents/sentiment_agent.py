"""Planned module: sentiment agent. Implementation pending."""

"""
File: ai/agents/sentiment_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- analyze_sentiment
- batch_sentiment_analysis
- analyze_product_sentiment
- detect_customer_complaints

Baseline keyword model; not trained ML.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
)


POSITIVE_WORDS = {
    "excellent", "great", "good", "amazing",
    "fast", "perfect", "reliable", "happy",
    "satisfied", "quality", "affordable",
    "recommended", "love", "best",
}

NEGATIVE_WORDS = {
    "bad", "poor", "broken", "damaged",
    "late", "slow", "defective", "expensive",
    "terrible", "worst", "refund", "delay",
    "disappointed", "missing", "faulty",
}

ASPECTS = {
    "quality": {
        "quality", "broken", "damaged",
        "defective", "faulty", "durable",
    },
    "delivery": {
        "delivery", "shipping", "late",
        "delay", "courier", "arrived",
    },
    "pricing": {
        "price", "cost", "expensive",
        "cheap", "affordable",
    },
    "service": {
        "support", "service", "staff",
        "response", "refund",
    },
    "packaging": {
        "package", "packaging", "box",
        "seal", "packing",
    },
}

SAFETY_TERMS = {
    "fire", "smoke", "electric shock",
    "injury", "explosion", "overheating",
}


class SentimentAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="sentiment_agent",
            name="Retail Customer Sentiment Agent",
            capabilities={
                "analyze_sentiment",
                "batch_sentiment_analysis",
                "analyze_product_sentiment",
                "detect_customer_complaints",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise AgentValidationError(
                f"{name} is required."
            )

        if len(value) > 10000:
            raise AgentValidationError(
                f"{name} exceeds length limit."
            )

        return value.strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(
            r"[a-z]+",
            text.lower(),
        )

    def _analyze(self, payload: dict) -> dict:
        text = self._text(
            payload.get("text"), "text"
        )

        tokens = self._tokens(text)
        counts = Counter(tokens)

        positive_matches = sorted(
            word
            for word in POSITIVE_WORDS
            if counts[word] > 0
        )

        negative_matches = sorted(
            word
            for word in NEGATIVE_WORDS
            if counts[word] > 0
        )

        positive_count = sum(
            counts[word]
            for word in POSITIVE_WORDS
        )

        negative_count = sum(
            counts[word]
            for word in NEGATIVE_WORDS
        )

        total = (
            positive_count + negative_count
        )

        score = (
            (positive_count - negative_count)
            / total
            if total else 0.0
        )

        if score > 0.2:
            sentiment = "positive"
        elif score < -0.2:
            sentiment = "negative"
        else:
            sentiment = "neutral_or_mixed"

        detected_aspects = [
            aspect
            for aspect, keywords in ASPECTS.items()
            if any(
                counts[word] > 0
                for word in keywords
            )
        ]

        lower_text = text.lower()

        safety_flag = any(
            term in lower_text
            for term in SAFETY_TERMS
        )

        return {
            "sentiment": sentiment,
            "sentiment_score": round(score, 3),
            "positive_keywords": positive_matches,
            "negative_keywords": negative_matches,
            "detected_aspects": detected_aspects,
            "potential_safety_issue": safety_flag,
            "complaint_review_recommended": (
                sentiment == "negative"
                or safety_flag
            ),
            "method": "keyword_lexicon_baseline",
            "limitations": (
                "Negation, sarcasm, multilingual text "
                "and contextual meaning may be missed."
            ),
        }

    def _batch(self, payload: dict) -> dict:
        reviews = payload.get("reviews")

        if (
            not isinstance(reviews, list)
            or not 1 <= len(reviews) <= 500
        ):
            raise AgentValidationError(
                "Provide 1 to 500 reviews."
            )

        results = []

        for review in reviews:
            if not isinstance(review, dict):
                raise AgentValidationError(
                    "Review must be an object."
                )

            analysis = self._analyze(review)

            results.append({
                "review_id": review.get("review_id"),
                "product_id": review.get("product_id"),
                **analysis,
            })

        return {
            "review_count": len(results),
            "results": results,
        }

    def _product(self, payload: dict) -> dict:
        product_id = self._text(
            payload.get("product_id"),
            "product_id",
        )

        reviews = payload.get("reviews")

        if not isinstance(reviews, list):
            raise AgentValidationError(
                "reviews must be a list."
            )

        if not 1 <= len(reviews) <= 500:
            raise AgentValidationError(
                "Provide 1 to 500 reviews."
            )

        analyses = []

        for review in reviews:
            if not isinstance(review, dict):
                raise AgentValidationError(
                    "Review must be an object."
                )

            analyses.append(
                self._analyze(review)
            )

        sentiments = Counter(
            result["sentiment"]
            for result in analyses
        )

        aspects = Counter(
            aspect
            for result in analyses
            for aspect in result["detected_aspects"]
        )

        negative_count = sentiments.get(
            "negative", 0
        )

        negative_percent = (
            negative_count / len(analyses) * 100
        )

        return {
            "product_id": product_id,
            "review_count": len(analyses),
            "sentiment_distribution": dict(
                sentiments
            ),
            "negative_review_percent": round(
                negative_percent, 2
            ),
            "aspect_mentions": dict(aspects),
            "safety_review_count": sum(
                result["potential_safety_issue"]
                for result in analyses
            ),
            "escalation_recommended": (
                negative_percent >= 30
                or any(
                    result["potential_safety_issue"]
                    for result in analyses
                )
            ),
        }

    def _complaints(self, payload: dict) -> dict:
        reviews = payload.get("reviews")

        if (
            not isinstance(reviews, list)
            or not 1 <= len(reviews) <= 500
        ):
            raise AgentValidationError(
                "Provide 1 to 500 reviews."
            )

        complaints = []

        for index, review in enumerate(reviews):
            if not isinstance(review, dict):
                raise AgentValidationError(
                    "Review must be an object."
                )

            analysis = self._analyze(review)

            if analysis[
                "complaint_review_recommended"
            ]:
                complaints.append({
                    "review_id": review.get(
                        "review_id", str(index)
                    ),
                    "sentiment": analysis["sentiment"],
                    "aspects": analysis[
                        "detected_aspects"
                    ],
                    "safety_flag": analysis[
                        "potential_safety_issue"
                    ],
                })

        return {
            "complaint_count": len(complaints),
            "complaints": complaints,
            "automatic_escalation_executed": False,
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        payload = request.payload

        if task == "analyze_sentiment":
            return self._analyze(payload)

        if task == "batch_sentiment_analysis":
            return self._batch(payload)

        if task == "analyze_product_sentiment":
            return self._product(payload)

        if task == "detect_customer_complaints":
            return self._complaints(payload)

        raise AgentValidationError(
            "Unsupported sentiment task."
        )
