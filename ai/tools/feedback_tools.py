"""Planned module: feedback tools. Implementation pending."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


POSITIVE_WORDS = {
    "excellent", "great", "good", "amazing",
    "perfect", "fast", "happy", "satisfied",
    "reliable", "quality", "love"
}

NEGATIVE_WORDS = {
    "bad", "poor", "broken", "damaged",
    "late", "delay", "defective", "terrible",
    "worst", "refund", "complaint", "missing"
}

ISSUE_KEYWORDS = {
    "delivery": {"late", "delay", "delivery", "shipping"},
    "product_quality": {
        "broken", "damaged", "defective", "quality"
    },
    "refund": {"refund", "return", "money"},
    "missing_item": {"missing", "incomplete", "lost"},
    "service": {"support", "service", "staff", "rude"},
}


@dataclass
class FeedbackRecord:
    feedback_id: str
    product_id: str
    customer_id: str
    rating: int
    comment: str
    created_at: str | None = None


def _validate_rating(rating: int) -> None:
    if isinstance(rating, bool) or not isinstance(rating, int):
        raise ValueError("Rating must be an integer.")

    if not 1 <= rating <= 5:
        raise ValueError("Rating must be between 1 and 5.")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z]+\b", text.lower())


def analyze_sentiment(
    comment: str,
    rating: int | None = None
) -> dict[str, Any]:

    if rating is not None:
        _validate_rating(rating)

    words = _tokenize(comment)

    positive_count = sum(
        word in POSITIVE_WORDS for word in words
    )

    negative_count = sum(
        word in NEGATIVE_WORDS for word in words
    )

    score = positive_count - negative_count

    if rating is not None:
        score += rating - 3

    if score > 0:
        sentiment = "positive"
    elif score < 0:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "positive_matches": positive_count,
        "negative_matches": negative_count,
        "method": "rule_based_baseline"
    }


def detect_complaint_categories(
    comment: str
) -> list[str]:

    words = set(_tokenize(comment))

    return [
        category
        for category, keywords in ISSUE_KEYWORDS.items()
        if words.intersection(keywords)
    ]


def classify_feedback_severity(
    rating: int,
    comment: str
) -> dict[str, Any]:

    _validate_rating(rating)

    sentiment = analyze_sentiment(comment, rating)
    categories = detect_complaint_categories(comment)

    if rating == 1:
        severity = "critical"
    elif rating == 2:
        severity = "high"
    elif rating == 3:
        severity = "medium"
    else:
        severity = "low"

    if "product_quality" in categories and rating <= 2:
        severity = "critical"

    return {
        "severity": severity,
        "sentiment": sentiment["sentiment"],
        "complaint_categories": categories,
        "requires_review": severity in {"critical", "high"}
    }


def analyze_customer_feedback(
    feedback: FeedbackRecord
) -> dict[str, Any]:

    _validate_rating(feedback.rating)

    sentiment = analyze_sentiment(
        feedback.comment,
        feedback.rating
    )

    classification = classify_feedback_severity(
        feedback.rating,
        feedback.comment
    )

    return {
        "feedback_id": feedback.feedback_id,
        "product_id": feedback.product_id,
        "customer_id": feedback.customer_id,
        "rating": feedback.rating,
        "sentiment": sentiment,
        "classification": classification,
        "analyzed_at": datetime.now(
            timezone.utc
        ).isoformat()
    }


def summarize_product_feedback(
    feedback_records: list[FeedbackRecord]
) -> dict[str, Any]:

    if not feedback_records:
        return {
            "total_feedback": 0,
            "average_rating": None,
            "sentiment_distribution": {},
            "complaint_distribution": {}
        }

    sentiment_counts = Counter()
    complaint_counts = Counter()
    rating_total = 0

    for record in feedback_records:
        result = analyze_customer_feedback(record)

        rating_total += record.rating

        sentiment_counts.update([
            result["sentiment"]["sentiment"]
        ])

        complaint_counts.update(
            result["classification"]["complaint_categories"]
        )

    return {
        "total_feedback": len(feedback_records),
        "average_rating": round(
            rating_total / len(feedback_records), 2
        ),
        "sentiment_distribution": dict(sentiment_counts),
        "complaint_distribution": dict(complaint_counts)
    }


def generate_feedback_alert(
    feedback: FeedbackRecord
) -> dict[str, Any] | None:

    analysis = analyze_customer_feedback(feedback)
    classification = analysis["classification"]

    if not classification["requires_review"]:
        return None

    return {
        "alert_type": "negative_customer_feedback",
        "feedback_id": feedback.feedback_id,
        "product_id": feedback.product_id,
        "severity": classification["severity"],
        "message": (
            f"Customer feedback {feedback.feedback_id} "
            "requires employee review."
        ),
        "requires_human_review": True,
        "status": "pending"
    }