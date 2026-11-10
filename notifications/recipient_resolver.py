from __future__ import annotations

"""Planned module: recipient resolver. Implementation pending."""

"""
backend/notifications/recipient_resolver.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+

Features:
- Tenant-scoped recipient resolution
- Role-based access control
- Warehouse-level authorization
- Active-user filtering
- Notification channel preferences
- Escalation role support
- Optional explicit user targeting
- Deduplication by user ID
- Structured resolution metrics
- Integration with notification_router.py

The repository must enforce tenant isolation.
Never trust roles or warehouse grants from clients.
"""


from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Protocol


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} is required"
        )
    return value.strip()


class RecipientStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class RecipientChannel(str, Enum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


@dataclass(frozen=True)
class RecipientUser:
    tenant_id: str
    user_id: str
    status: RecipientStatus
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    global_warehouse_access: bool = False

    allowed_channels: frozenset[
        RecipientChannel
    ] = frozenset({
        RecipientChannel.DASHBOARD,
        RecipientChannel.EMAIL,
    })

    disabled_channels: frozenset[
        RecipientChannel
    ] = frozenset()

    verified_channels: frozenset[
        RecipientChannel
    ] = frozenset({
        RecipientChannel.DASHBOARD,
    })

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.user_id, "user_id")


@dataclass(frozen=True)
class RecipientQuery:
    tenant_id: str

    required_roles: frozenset[str] = frozenset()

    warehouse_id: str | None = None

    requested_channels: frozenset[
        RecipientChannel
    ] = frozenset({
        RecipientChannel.DASHBOARD,
        RecipientChannel.EMAIL,
    })

    explicit_user_ids: frozenset[str] = frozenset()

    require_all_roles: bool = False

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")

        if self.warehouse_id is not None:
            required(
                self.warehouse_id,
                "warehouse_id",
            )

        if not self.requested_channels:
            raise ValueError(
                "At least one channel is required"
            )


@dataclass(frozen=True)
class ResolvedRecipient:
    tenant_id: str
    user_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str]
    global_warehouse_access: bool
    channels: frozenset[RecipientChannel]


@dataclass(frozen=True)
class RecipientResolutionResult:
    tenant_id: str
    recipients: tuple[ResolvedRecipient, ...]
    examined_users: int
    rejected_users: int
    rejected_inactive: int
    rejected_access: int
    rejected_channels: int


class RecipientRepository(Protocol):
    """
    Must return trusted tenant-scoped user records.

    The concrete implementation should query
    user_repository.py and associated role,
    warehouse, and preference tables.
    """

    def list_users_for_notification(
        self,
        *,
        tenant_id: str,
    ) -> Iterable[RecipientUser]:
        ...


class RetailRecipientResolver:
    def __init__(
        self,
        repository: RecipientRepository,
    ) -> None:
        self.repository = repository

    @staticmethod
    def _roles_match(
        user: RecipientUser,
        query: RecipientQuery,
    ) -> bool:
        if not query.required_roles:
            return True

        if query.require_all_roles:
            return query.required_roles.issubset(
                user.roles
            )

        return bool(
            query.required_roles.intersection(
                user.roles
            )
        )

    @staticmethod
    def _warehouse_match(
        user: RecipientUser,
        warehouse_id: str | None,
    ) -> bool:
        if warehouse_id is None:
            return True

        return (
            user.global_warehouse_access
            or warehouse_id in user.warehouse_ids
        )

    @staticmethod
    def _channels(
        user: RecipientUser,
        query: RecipientQuery,
    ) -> frozenset[RecipientChannel]:
        return frozenset(
            query.requested_channels
            & user.allowed_channels
            & user.verified_channels
            - user.disabled_channels
        )

    def resolve(
        self,
        query: RecipientQuery,
    ) -> RecipientResolutionResult:
        users = self.repository.list_users_for_notification(
            tenant_id=query.tenant_id
        )

        recipients: list[ResolvedRecipient] = []
        seen: set[str] = set()

        examined = 0
        rejected_inactive = 0
        rejected_access = 0
        rejected_channels = 0

        for user in users:
            examined += 1

            if user.tenant_id != query.tenant_id:
                rejected_access += 1
                continue

            if user.user_id in seen:
                continue

            seen.add(user.user_id)

            if user.status != RecipientStatus.ACTIVE:
                rejected_inactive += 1
                continue

            if (
                query.explicit_user_ids
                and user.user_id
                    not in query.explicit_user_ids
            ):
                rejected_access += 1
                continue

            # Explicit targeting narrows the audience;
            # it never bypasses role/warehouse access.
            if not self._roles_match(user, query):
                rejected_access += 1
                continue

            if not self._warehouse_match(
                user,
                query.warehouse_id,
            ):
                rejected_access += 1
                continue

            channels = self._channels(
                user,
                query,
            )

            if not channels:
                rejected_channels += 1
                continue

            recipients.append(
                ResolvedRecipient(
                    tenant_id=user.tenant_id,
                    user_id=user.user_id,
                    roles=user.roles,
                    warehouse_ids=user.warehouse_ids,
                    global_warehouse_access=(
                        user.global_warehouse_access
                    ),
                    channels=channels,
                )
            )

        recipients.sort(
            key=lambda recipient: recipient.user_id
        )

        rejected = (
            rejected_inactive
            + rejected_access
            + rejected_channels
        )

        return RecipientResolutionResult(
            tenant_id=query.tenant_id,
            recipients=tuple(recipients),
            examined_users=examined,
            rejected_users=rejected,
            rejected_inactive=rejected_inactive,
            rejected_access=rejected_access,
            rejected_channels=rejected_channels,
        )

    def resolve_escalation(
        self,
        *,
        tenant_id: str,
        recipient_roles: tuple[str, ...],
        warehouse_id: str | None,
        channels: frozenset[RecipientChannel],
    ) -> RecipientResolutionResult:
        if not recipient_roles:
            raise ValueError(
                "Escalation roles are required"
            )

        return self.resolve(
            RecipientQuery(
                tenant_id=tenant_id,
                required_roles=frozenset(
                    recipient_roles
                ),
                warehouse_id=warehouse_id,
                requested_channels=channels,
            )
        )


class InMemoryRecipientRepository:
    """
    Demo repository only.

    Production should use persistent,
    authenticated, tenant-scoped records.
    """

    def __init__(
        self,
        users: Iterable[RecipientUser],
    ) -> None:
        self.users = tuple(users)

    def list_users_for_notification(
        self,
        *,
        tenant_id: str,
    ) -> Iterable[RecipientUser]:
        return (
            user
            for user in self.users
            if user.tenant_id == tenant_id
        )


if __name__ == "__main__":
    repository = InMemoryRecipientRepository(
        users=[
            RecipientUser(
                tenant_id="retail-demo",
                user_id="EMP001",
                status=RecipientStatus.ACTIVE,
                roles=frozenset({
                    "inventory_manager",
                }),
                warehouse_ids=frozenset({
                    "WH001",
                }),
                verified_channels=frozenset({
                    RecipientChannel.DASHBOARD,
                    RecipientChannel.EMAIL,
                }),
            ),
            RecipientUser(
                tenant_id="retail-demo",
                user_id="EMP002",
                status=RecipientStatus.ACTIVE,
                roles=frozenset({
                    "warehouse_manager",
                }),
                warehouse_ids=frozenset({
                    "WH001",
                }),
                verified_channels=frozenset({
                    RecipientChannel.DASHBOARD,
                }),
            ),
            RecipientUser(
                tenant_id="retail-demo",
                user_id="EMP003",
                status=RecipientStatus.SUSPENDED,
                roles=frozenset({
                    "inventory_manager",
                }),
                warehouse_ids=frozenset({
                    "WH001",
                }),
            ),
        ]
    )

    resolver = RetailRecipientResolver(
        repository
    )

    result = resolver.resolve(
        RecipientQuery(
            tenant_id="retail-demo",
            required_roles=frozenset({
                "inventory_manager",
                "warehouse_manager",
            }),
            warehouse_id="WH001",
            requested_channels=frozenset({
                RecipientChannel.DASHBOARD,
                RecipientChannel.EMAIL,
            }),
        )
    )

    print(
        "Eligible recipients:",
        len(result.recipients),
    )

    for recipient in result.recipients:
        print(
            recipient.user_id,
            sorted(
                channel.value
                for channel in recipient.channels
            ),
        )
