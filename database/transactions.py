from __future__ import annotations

"""Planned module: transactions. Implementation pending."""

"""
backend/database/transactions.py

Autonomous Retail Supply Chain AI 5.0

Production-oriented synchronous transaction
utilities for PostgreSQL and SQLAlchemy 2.x.

Features:
- Atomic transaction boundaries
- Automatic rollback
- Tenant-scoped transaction context
- Read-only transactions
- Isolation level selection
- Nested SAVEPOINT support
- Bounded retry for serialization failures
- Advisory transaction locks
- Commit and rollback hooks
- Explicit session ownership

Dependencies:
    SQLAlchemy >= 2.0
    psycopg >= 3

Requires:
    backend.database.engine
"""


import hashlib
import logging
import random
import time

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.database.engine import (
    get_database_manager,
)


logger = logging.getLogger(__name__)

T = TypeVar("T")


class TransactionError(RuntimeError):
    pass


class TransactionRetryExhausted(
    TransactionError
):
    pass


class IsolationLevel(str, Enum):
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"


# PostgreSQL SQLSTATE codes:
# 40001: serialization_failure
# 40P01: deadlock_detected
RETRYABLE_SQLSTATES = frozenset({
    "40001",
    "40P01",
})


@dataclass(frozen=True)
class TransactionOptions:
    tenant_id: str | None = None
    isolation: IsolationLevel = (
        IsolationLevel.READ_COMMITTED
    )
    read_only: bool = False
    statement_timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        if (
            self.tenant_id is not None
            and not self.tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id cannot be blank"
            )

        if not (
            100 <= self.statement_timeout_ms
            <= 300_000
        ):
            raise ValueError(
                "statement_timeout_ms must be "
                "between 100 and 300000"
            )


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError(
                "max_attempts must be 1-10"
            )

        if (
            self.base_delay_seconds < 0
            or self.max_delay_seconds < 0
        ):
            raise ValueError(
                "Retry delays cannot be negative"
            )


@dataclass
class TransactionHooks:
    """
    Hooks execute after the transaction
    context has completed.

    Do not use hooks for critical delivery.
    Use a transactional outbox instead.
    """

    after_commit: list[
        Callable[[], None]
    ] = field(default_factory=list)

    after_rollback: list[
        Callable[[], None]
    ] = field(default_factory=list)

    def on_commit(
        self,
        callback: Callable[[], None],
    ) -> None:
        self.after_commit.append(callback)

    def on_rollback(
        self,
        callback: Callable[[], None],
    ) -> None:
        self.after_rollback.append(callback)


def get_sqlstate(
    exc: DBAPIError,
) -> str | None:
    original = exc.orig

    return (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
    )


def is_retryable_transaction_error(
    exc: BaseException,
) -> bool:
    return (
        isinstance(exc, DBAPIError)
        and get_sqlstate(exc)
        in RETRYABLE_SQLSTATES
    )


def _configure_transaction(
    session: Session,
    options: TransactionOptions,
) -> None:
    """
    Apply PostgreSQL transaction settings
    before application queries.

    SQL identifiers are selected from
    trusted enums, not user input.
    """

    isolation_sql = {
        IsolationLevel.READ_COMMITTED:
            "READ COMMITTED",
        IsolationLevel.REPEATABLE_READ:
            "REPEATABLE READ",
        IsolationLevel.SERIALIZABLE:
            "SERIALIZABLE",
    }[options.isolation]

    read_mode = (
        "READ ONLY"
        if options.read_only
        else "READ WRITE"
    )

    session.execute(
        text(
            "SET TRANSACTION ISOLATION LEVEL "
            f"{isolation_sql}, {read_mode}"
        )
    )

    session.execute(
        text(
            "SELECT set_config("
            "'statement_timeout', "
            ":timeout_value, true)"
        ),
        {
            "timeout_value": str(
                options.statement_timeout_ms
            )
        },
    )

    if options.tenant_id is not None:
        session.info["tenant_id"] = (
            options.tenant_id
        )

        session.execute(
            text(
                "SELECT set_config("
                "'app.current_tenant', "
                ":tenant_id, true)"
            ),
            {
                "tenant_id": options.tenant_id
            },
        )


@contextmanager
def atomic_transaction(
    options: TransactionOptions | None = None,
) -> Iterator[Session]:
    """
    Create one atomic transaction.

    The session must not be shared
    across concurrent requests or threads.
    """

    options = options or TransactionOptions()

    session = (
        get_database_manager()
        .session_factory()
    )

    try:
        with session.begin():
            _configure_transaction(
                session,
                options,
            )

            yield session

    except Exception:
        session.rollback()
        raise

    finally:
        session.info.pop(
            "tenant_id", None
        )
        session.close()


@contextmanager
def savepoint(
    session: Session,
) -> Iterator[Session]:
    """
    Create a nested SAVEPOINT.

    The caller owns the outer transaction.
    """

    if not session.in_transaction():
        raise TransactionError(
            "SAVEPOINT requires an "
            "active transaction"
        )

    with session.begin_nested():
        yield session


def execute_with_retry(
    operation: Callable[[Session], T],
    *,
    options: TransactionOptions | None = None,
    retry_policy: RetryPolicy | None = None,
) -> T:
    """
    Retry the complete database transaction
    for serialization failures or deadlocks.

    The operation must be safe to repeat.

    Do not perform external API calls,
    emails, payments, or irreversible side
    effects inside a retried operation.
    """

    retry_policy = (
        retry_policy or RetryPolicy()
    )

    for attempt in range(
        1,
        retry_policy.max_attempts + 1,
    ):
        try:
            with atomic_transaction(
                options
            ) as session:
                return operation(session)

        except DBAPIError as exc:
            if not is_retryable_transaction_error(
                exc
            ):
                raise

            if (
                attempt
                >= retry_policy.max_attempts
            ):
                raise TransactionRetryExhausted(
                    "Transaction retry limit "
                    "exceeded"
                ) from exc

            delay = min(
                retry_policy.max_delay_seconds,
                retry_policy.base_delay_seconds
                * (2 ** (attempt - 1)),
            )

            # Jitter reduces retry collisions.
            time.sleep(
                random.uniform(
                    0,
                    delay,
                )
            )

    raise TransactionRetryExhausted(
        "Transaction failed"
    )


def advisory_lock_key(
    namespace: str,
    resource_id: str,
) -> int:
    """
    Produce a deterministic signed 64-bit
    key for PostgreSQL advisory locks.
    """

    if not namespace or not resource_id:
        raise ValueError(
            "Lock identifiers are required"
        )

    value = (
        f"{namespace}:{resource_id}"
        .encode("utf-8")
    )

    digest = hashlib.sha256(
        value
    ).digest()[:8]

    return int.from_bytes(
        digest,
        byteorder="big",
        signed=True,
    )


def acquire_advisory_lock(
    session: Session,
    *,
    namespace: str,
    resource_id: str,
) -> None:
    """
    Acquire a transaction-scoped
    PostgreSQL advisory lock.

    Automatically released when the
    transaction commits or rolls back.
    """

    if not session.in_transaction():
        raise TransactionError(
            "An active transaction is required"
        )

    lock_key = advisory_lock_key(
        namespace,
        resource_id,
    )

    session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            ":lock_key)"
        ),
        {"lock_key": lock_key},
    )


def try_advisory_lock(
    session: Session,
    *,
    namespace: str,
    resource_id: str,
) -> bool:
    """
    Attempt a transaction-scoped lock
    without waiting.
    """

    if not session.in_transaction():
        raise TransactionError(
            "An active transaction is required"
        )

    lock_key = advisory_lock_key(
        namespace,
        resource_id,
    )

    return bool(
        session.execute(
            text(
                "SELECT pg_try_advisory_xact_lock("
                ":lock_key)"
            ),
            {"lock_key": lock_key},
        ).scalar_one()
    )


def execute_with_hooks(
    operation: Callable[
        [Session, TransactionHooks], T
    ],
    *,
    options: TransactionOptions | None = None,
) -> T:
    """
    Execute one transaction with
    post-commit and post-rollback hooks.

    Hook failures are logged after the
    database transaction has completed.
    """

    hooks = TransactionHooks()

    try:
        with atomic_transaction(
            options
        ) as session:
            result = operation(
                session,
                hooks,
            )

    except Exception:
        for callback in hooks.after_rollback:
            try:
                callback()
            except Exception:
                logger.exception(
                    "Rollback hook failed"
                )

        raise

    for callback in hooks.after_commit:
        try:
            callback()
        except Exception:
            logger.exception(
                "Commit hook failed"
            )

    return result
