from __future__ import annotations

"""Planned module: email notifier. Implementation pending."""

"""
backend/notifications/email_notifier.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard Library SMTP

Features:
- SMTP SSL or STARTTLS
- Plain-text and HTML email
- Transactional retail alert templates
- Async-compatible sending
- Recipient and header validation
- HTML escaping
- Structured send results
- No hardcoded credentials
- SMTP response classification

This module is a transport adapter.
Authentication, consent, idempotency, persistence,
and retry scheduling belong to upstream services.
"""


import asyncio
import logging
import os
import re
import smtplib
import ssl

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from enum import Enum
from html import escape
from typing import Mapping


logger = logging.getLogger(__name__)


class EmailSecurity(str, Enum):
    SSL = "ssl"
    STARTTLS = "starttls"


class EmailCategory(str, Enum):
    LOW_STOCK = "low_stock"
    STOCKOUT_RISK = "stockout_risk"
    SUPPLIER_DELAY = "supplier_delay"
    WAREHOUSE_CAPACITY = "warehouse_capacity"
    QUALITY_DEFECT = "quality_defect"
    DELIVERY_DELAY = "delivery_delay"
    FINANCIAL_ANOMALY = "financial_anomaly"
    INCIDENT = "incident"
    GENERAL = "general"


class EmailTransportError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    sender_email: str
    sender_name: str = "Retail AI Alerts"
    security: EmailSecurity = EmailSecurity.STARTTLS
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("SMTP host required")

        if not 1 <= self.port <= 65535:
            raise ValueError("Invalid SMTP port")

        if not self.username or not self.password:
            raise ValueError("SMTP credentials required")

        validate_email(self.sender_email)
        safe_header(self.sender_name, "sender_name")

        if self.timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        return cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ["SMTP_USERNAME"],
            password=os.environ["SMTP_PASSWORD"],
            sender_email=os.environ["SMTP_SENDER_EMAIL"],
            sender_name=os.environ.get(
                "SMTP_SENDER_NAME",
                "Retail AI Alerts",
            ),
            security=EmailSecurity(
                os.environ.get(
                    "SMTP_SECURITY",
                    "starttls",
                )
            ),
            timeout_seconds=float(
                os.environ.get(
                    "SMTP_TIMEOUT_SECONDS",
                    "15",
                )
            ),
        )


@dataclass(frozen=True)
class EmailPayload:
    recipient_email: str
    subject: str
    text_body: str
    html_body: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class EmailSendResult:
    accepted: bool
    recipient_email: str
    message_id: str
    provider_response: str


def safe_header(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")

    value = value.strip()

    if not value:
        raise ValueError(f"{field} is required")

    if any(c in value for c in "\r\n\x00"):
        raise ValueError(
            f"Unsafe characters in {field}"
        )

    if len(value) > 300:
        raise ValueError(
            f"{field} is too long"
        )

    return value


_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*"
    r"[A-Za-z0-9])?)+$"
)


def validate_email(value: str) -> str:
    address = safe_header(value, "email")

    display_name, parsed = parseaddr(address)

    if display_name or parsed != address:
        raise ValueError(
            "Email must be a bare address"
        )

    if (
        len(address) > 254
        or not _EMAIL_RE.fullmatch(address)
    ):
        raise ValueError("Invalid email address")

    return address


class RetailEmailTemplates:
    TITLES = {
        EmailCategory.LOW_STOCK:
            "Low Inventory Alert",
        EmailCategory.STOCKOUT_RISK:
            "Predicted Stockout Risk",
        EmailCategory.SUPPLIER_DELAY:
            "Supplier Delivery Delay",
        EmailCategory.WAREHOUSE_CAPACITY:
            "Warehouse Capacity Warning",
        EmailCategory.QUALITY_DEFECT:
            "Product Quality Alert",
        EmailCategory.DELIVERY_DELAY:
            "Shipment Delay Alert",
        EmailCategory.FINANCIAL_ANOMALY:
            "Financial Anomaly Review",
        EmailCategory.INCIDENT:
            "Operational Incident",
        EmailCategory.GENERAL:
            "Retail Operations Update",
    }

    @classmethod
    def render(
        cls,
        *,
        category: EmailCategory,
        severity: str,
        resource_id: str,
        description: str,
        recommended_action: str,
    ) -> tuple[str, str, str]:
        if not isinstance(category, EmailCategory):
            raise ValueError("Invalid email category")

        severity = safe_header(
            severity, "severity"
        ).upper()

        if severity not in {
            "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"
        }:
            raise ValueError("Invalid severity")

        resource_id = safe_header(
            resource_id, "resource_id"
        )

        if not isinstance(description, str):
            raise ValueError("Description must be text")

        if not isinstance(recommended_action, str):
            raise ValueError(
                "Recommended action must be text"
            )

        if len(description) > 5000:
            raise ValueError("Description too long")

        if len(recommended_action) > 2000:
            raise ValueError("Action too long")

        title = cls.TITLES[category]

        subject = (
            f"[{severity}] {title} - {resource_id}"
        )

        text_body = (
            f"{title}\n\n"
            f"Severity: {severity}\n"
            f"Resource: {resource_id}\n\n"
            f"Details:\n{description}\n\n"
            f"Recommended action:\n"
            f"{recommended_action}\n\n"
            "This is an automated operational alert."
        )

        html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
</head>
<body style="
    margin:0;
    padding:24px;
    background:#f3f5f9;
    font-family:Arial,sans-serif;
    color:#172033;
">
<table role="presentation"
       style="
         max-width:620px;
         width:100%;
         margin:auto;
         background:#ffffff;
         border-radius:12px;
         border-collapse:collapse;
       ">
<tr>
<td style="padding:28px;">
<h2 style="margin-top:0;">
{escape(title)}
</h2>
<p>
<strong>Severity:</strong>
{escape(severity)}
</p>
<p>
<strong>Resource:</strong>
{escape(resource_id)}
</p>
<hr style="border:0;border-top:1px solid #ddd;">
<h3>Alert details</h3>
<p style="white-space:pre-wrap;">
{escape(description)}
</p>
<h3>Recommended action</h3>
<p style="white-space:pre-wrap;">
{escape(recommended_action)}
</p>
<p style="
  font-size:12px;
  color:#6b7280;
  margin-top:32px;
">
Automated notification from
Autonomous Retail Supply Chain AI.
</p>
</td>
</tr>
</table>
</body>
</html>
"""

        return subject, text_body, html_body


class RetailEmailNotifier:
    def __init__(
        self,
        config: SMTPConfig,
    ) -> None:
        self.config = config

    def _build_message(
        self,
        payload: EmailPayload,
    ) -> EmailMessage:
        recipient = validate_email(
            payload.recipient_email
        )

        subject = safe_header(
            payload.subject, "subject"
        )

        if not isinstance(payload.text_body, str):
            raise ValueError(
                "text_body must be text"
            )

        if not payload.text_body.strip():
            raise ValueError(
                "text_body cannot be empty"
            )

        if len(payload.text_body) > 100_000:
            raise ValueError(
                "Email body too large"
            )

        if (
            payload.html_body is not None
            and len(payload.html_body) > 200_000
        ):
            raise ValueError(
                "HTML body too large"
            )

        message = EmailMessage()

        message["From"] = formataddr((
            self.config.sender_name,
            self.config.sender_email,
        ))

        message["To"] = recipient
        message["Subject"] = subject

        if payload.correlation_id is not None:
            correlation_id = safe_header(
                payload.correlation_id,
                "correlation_id",
            )
            message["X-Correlation-ID"] = (
                correlation_id
            )

        message.set_content(payload.text_body)

        if payload.html_body:
            message.add_alternative(
                payload.html_body,
                subtype="html",
            )

        return message

    def send(
        self,
        payload: EmailPayload,
    ) -> EmailSendResult:
        message = self._build_message(payload)

        recipient = validate_email(
            payload.recipient_email
        )

        context = ssl.create_default_context()

        try:
            if self.config.security == EmailSecurity.SSL:
                with smtplib.SMTP_SSL(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                    context=context,
                ) as server:
                    server.login(
                        self.config.username,
                        self.config.password,
                    )

                    refused = server.send_message(
                        message
                    )

            else:
                with smtplib.SMTP(
                    self.config.host,
                    self.config.port,
                    timeout=self.config.timeout_seconds,
                ) as server:
                    server.ehlo()

                    if not server.has_extn("starttls"):
                        raise EmailTransportError(
                            "SMTP server does not support STARTTLS",
                            retryable=False,
                        )

                    server.starttls(context=context)
                    server.ehlo()

                    server.login(
                        self.config.username,
                        self.config.password,
                    )

                    refused = server.send_message(
                        message
                    )

            if refused:
                raise EmailTransportError(
                    "Recipient rejected by SMTP server",
                    retryable=False,
                )

            logger.info(
                "SMTP accepted email for correlation=%s",
                payload.correlation_id,
            )

            return EmailSendResult(
                accepted=True,
                recipient_email=recipient,
                message_id=(
                    message.get("Message-ID") or ""
                ),
                provider_response="SMTP accepted message",
            )

        except EmailTransportError:
            raise

        except smtplib.SMTPAuthenticationError as exc:
            raise EmailTransportError(
                "SMTP authentication failed",
                retryable=False,
            ) from exc

        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailTransportError(
                "SMTP recipient refused",
                retryable=False,
            ) from exc

        except smtplib.SMTPResponseException as exc:
            retryable = (
                400 <= exc.smtp_code < 500
            )

            raise EmailTransportError(
                f"SMTP error {exc.smtp_code}",
                retryable=retryable,
            ) from exc

        except (
            smtplib.SMTPException,
            TimeoutError,
            OSError,
        ) as exc:
            raise EmailTransportError(
                "SMTP transport failure",
                retryable=True,
            ) from exc

    async def send_async(
        self,
        payload: EmailPayload,
    ) -> EmailSendResult:
        return await asyncio.to_thread(
            self.send, payload
        )

    async def send_alert(
        self,
        *,
        recipient_email: str,
        category: EmailCategory,
        severity: str,
        resource_id: str,
        description: str,
        recommended_action: str,
        correlation_id: str | None = None,
    ) -> EmailSendResult:
        subject, text_body, html_body = (
            RetailEmailTemplates.render(
                category=category,
                severity=severity,
                resource_id=resource_id,
                description=description,
                recommended_action=recommended_action,
            )
        )

        return await self.send_async(
            EmailPayload(
                recipient_email=recipient_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                correlation_id=correlation_id,
            )
        )


if __name__ == "__main__":
    # Configure SMTP_* environment variables first.
    # This example renders a preview without sending.

    subject, text, html = RetailEmailTemplates.render(
        category=EmailCategory.LOW_STOCK,
        severity="critical",
        resource_id="WH001:SKU001",
        description=(
            "Available inventory has dropped to "
            "12 units. Reorder point: 100 units."
        ),
        recommended_action=(
            "Review replenishment and supplier "
            "lead time immediately."
        ),
    )

    print("Subject:", subject)
    print("Text preview:\n", text)

    # To send a real message:
    #
    # notifier = RetailEmailNotifier(
    #     SMTPConfig.from_env()
    # )
    #
    # asyncio.run(
    #     notifier.send_alert(
    #         recipient_email="authorized@example.com",
    #         category=EmailCategory.LOW_STOCK,
    #         severity="critical",
    #         resource_id="WH001:SKU001",
    #         description="12 units remaining",
    #         recommended_action="Review replenishment",
    #     )
    # )
