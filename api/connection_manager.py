from __future__ import annotations

"""Planned module: connection manager. Implementation pending."""

"""
backend/connection_manager.py

Autonomous Retail Supply Chain AI 5.0

Authenticated WebSocket connection manager.

Python 3.10+
Dependencies:
    fastapi
    starlette

Features:
    - WebSocket connection lifecycle
    - Tenant-isolated connections
    - Authenticated user connections
    - Per-user connection limits
    - Tenant-wide broadcasts
    - User-specific messages
    - Agent execution updates
    - Inventory and stock alerts
    - Heartbeat / stale connection cleanup
    - Concurrent connection safety
    - Bounded outbound queues
    - Graceful shutdown

Security:
    - Never trust tenant IDs from clients
    - Authenticate before accepting sockets
    - Authorize every subscription
    - Never broadcast across tenants
    - Do not send credentials or secrets
    - Apply origin and message-size controls
    - Use Redis Pub/Sub or Streams for
      multi-worker deployments
"""


import asyncio
import json
import logging
import secrets
import time

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from starlette.websockets import WebSocketState

from backend.permissions import (
    Permission,
    Principal,
    permission_engine,
)


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_CONNECTIONS_PER_USER = 5
MAX_CONNECTIONS_PER_TENANT = 1000

MAX_QUEUE_SIZE = 100
MAX_MESSAGE_BYTES = 64 * 1024

HEARTBEAT_INTERVAL_SECONDS = 25
CONNECTION_IDLE_TIMEOUT_SECONDS = 90

SEND_TIMEOUT_SECONDS = 10


# ============================================================
# EVENT TYPES
# ============================================================

class RealtimeEventType(str, Enum):

    CONNECTED = "connected"
    HEARTBEAT = "heartbeat"
    PING = "ping"
    PONG = "pong"

    AGENT_STARTED = "agent_started"
    AGENT_PROGRESS = "agent_progress"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"

    INVENTORY_UPDATED = "inventory_updated"
    LOW_STOCK_ALERT = "low_stock_alert"
    STOCKOUT_ALERT = "stockout_alert"

    PURCHASE_ORDER_UPDATED = (
        "purchase_order_updated"
    )

    SHIPMENT_UPDATED = "shipment_updated"

    APPROVAL_REQUIRED = "approval_required"

    NOTIFICATION = "notification"
    SYSTEM_MESSAGE = "system_message"

    ERROR = "error"


# ============================================================
# MESSAGE MODEL
# ============================================================

@dataclass(frozen=True)
class RealtimeMessage:

    event: RealtimeEventType
    data: dict[str, Any]

    timestamp: str = field(
        default_factory=lambda: (
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )

    def serialize(self) -> str:

        return json.dumps(
            {
                "event": self.event.value,
                "data": self.data,
                "timestamp": self.timestamp,
            },
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


# ============================================================
# CONNECTION STATE
# ============================================================

@dataclass(eq=False)
class ClientConnection:

    connection_id: str

    websocket: WebSocket

    principal: Principal

    connected_at: float = field(
        default_factory=time.monotonic
    )

    last_seen: float = field(
        default_factory=time.monotonic
    )

    queue: asyncio.Queue[str] = field(
        default_factory=lambda: (
            asyncio.Queue(
                maxsize=MAX_QUEUE_SIZE
            )
        )
    )

    sender_task: asyncio.Task | None = None

    closed: bool = False

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id

    @property
    def user_id(self) -> str:
        return self.principal.principal_id


# ============================================================
# CONNECTION MANAGER
# ============================================================

class ConnectionManager:

    def __init__(self):

        self._connections: dict[
            str, ClientConnection
        ] = {}

        self._tenant_connections: dict[
            str, set[str]
        ] = {}

        self._user_connections: dict[
            tuple[str, str], set[str]
        ] = {}

        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        principal: Principal,
    ) -> ClientConnection:
        """
        Accept an already authenticated
        and authorized WebSocket principal.
        """

        permission_engine.require(
            principal,
            Permission.NOTIFICATION_READ,
        )

        if not principal.active:
            raise PermissionError(
                "Inactive principal"
            )

        async with self._lock:

            tenant_connections = (
                self._tenant_connections.get(
                    principal.tenant_id,
                    set(),
                )
            )

            user_key = (
                principal.tenant_id,
                principal.principal_id,
            )

            user_connections = (
                self._user_connections.get(
                    user_key,
                    set(),
                )
            )

            if len(user_connections) >= (
                MAX_CONNECTIONS_PER_USER
            ):
                raise ConnectionError(
                    "User connection limit reached"
                )

            if len(tenant_connections) >= (
                MAX_CONNECTIONS_PER_TENANT
            ):
                raise ConnectionError(
                    "Tenant connection limit reached"
                )

            connection_id = (
                secrets.token_urlsafe(24)
            )

            connection = ClientConnection(
                connection_id=connection_id,
                websocket=websocket,
                principal=principal,
            )

            # Accept while holding the lock
            # to avoid connection-limit races.
            await websocket.accept()

            self._connections[
                connection_id
            ] = connection

            self._tenant_connections.setdefault(
                principal.tenant_id,
                set(),
            ).add(connection_id)

            self._user_connections.setdefault(
                user_key,
                set(),
            ).add(connection_id)

        connection.sender_task = (
            asyncio.create_task(
                self._sender_loop(
                    connection
                )
            )
        )

        await self.send_to_connection(
            connection.connection_id,
            RealtimeMessage(
                event=RealtimeEventType.CONNECTED,
                data={
                    "connection_id": connection_id,
                    "status": "connected",
                },
            ),
        )

        return connection

    async def _sender_loop(
        self,
        connection: ClientConnection,
    ) -> None:

        try:

            while not connection.closed:

                payload = (
                    await connection.queue.get()
                )

                await asyncio.wait_for(
                    connection.websocket.send_text(
                        payload
                    ),
                    timeout=SEND_TIMEOUT_SECONDS,
                )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.warning(
                "WebSocket sender stopped",
                extra={
                    "connection_id": (
                        connection.connection_id
                    )
                },
            )

        finally:
            await self.disconnect(
                connection.connection_id
            )

    async def send_to_connection(
        self,
        connection_id: str,
        message: RealtimeMessage,
    ) -> bool:

        payload = message.serialize()

        if len(
            payload.encode("utf-8")
        ) > MAX_MESSAGE_BYTES:
            return False

        async with self._lock:

            connection = (
                self._connections.get(
                    connection_id
                )
            )

            if (
                connection is None
                or connection.closed
            ):
                return False

            try:
                connection.queue.put_nowait(
                    payload
                )

                return True

            except asyncio.QueueFull:
                return False

    async def send_to_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        message: RealtimeMessage,
    ) -> int:

        async with self._lock:

            connection_ids = list(
                self._user_connections.get(
                    (tenant_id, user_id),
                    set(),
                )
            )

        delivered = 0

        for connection_id in connection_ids:

            if await self.send_to_connection(
                connection_id,
                message,
            ):
                delivered += 1

        return delivered

    async def broadcast_to_tenant(
        self,
        *,
        tenant_id: str,
        message: RealtimeMessage,
        required_permission: Permission,
    ) -> int:
        """
        Tenant broadcast with per-recipient
        permission evaluation.
        """

        async with self._lock:

            connections = [
                self._connections[cid]
                for cid in (
                    self._tenant_connections.get(
                        tenant_id,
                        set(),
                    )
                )
                if cid in self._connections
            ]

        delivered = 0

        for connection in connections:

            decision = (
                permission_engine.evaluate(
                    connection.principal,
                    required_permission,
                )
            )

            if not decision.allowed:
                continue

            if await self.send_to_connection(
                connection.connection_id,
                message,
            ):
                delivered += 1

        return delivered

    async def disconnect(
        self,
        connection_id: str,
    ) -> None:

        async with self._lock:

            connection = (
                self._connections.pop(
                    connection_id,
                    None,
                )
            )

            if connection is None:
                return

            connection.closed = True

            tenant_set = (
                self._tenant_connections.get(
                    connection.tenant_id
                )
            )

            if tenant_set is not None:

                tenant_set.discard(
                    connection_id
                )

                if not tenant_set:
                    self._tenant_connections.pop(
                        connection.tenant_id,
                        None,
                    )

            user_key = (
                connection.tenant_id,
                connection.user_id,
            )

            user_set = (
                self._user_connections.get(
                    user_key
                )
            )

            if user_set is not None:

                user_set.discard(
                    connection_id
                )

                if not user_set:
                    self._user_connections.pop(
                        user_key,
                        None,
                    )

        task = connection.sender_task

        current = asyncio.current_task()

        if (
            task is not None
            and task is not current
            and not task.done()
        ):
            task.cancel()

            with suppress(
                asyncio.CancelledError
            ):
                await task

        if (
            connection.websocket.client_state
            == WebSocketState.CONNECTED
        ):

            with suppress(Exception):

                await connection.websocket.close(
                    code=1000
                )

    async def heartbeat(
        self,
        connection_id: str,
    ) -> bool:

        async with self._lock:

            connection = (
                self._connections.get(
                    connection_id
                )
            )

            if connection is None:
                return False

            connection.last_seen = (
                time.monotonic()
            )

            return True

    async def cleanup_stale_connections(
        self,
    ) -> int:

        now = time.monotonic()

        async with self._lock:

            stale_ids = [
                connection_id
                for connection_id, connection
                in self._connections.items()
                if (
                    now - connection.last_seen
                    > CONNECTION_IDLE_TIMEOUT_SECONDS
                )
            ]

        for connection_id in stale_ids:

            await self.disconnect(
                connection_id
            )

        return len(stale_ids)

    async def shutdown(self) -> None:

        async with self._lock:

            connection_ids = list(
                self._connections.keys()
            )

        for connection_id in connection_ids:

            await self.disconnect(
                connection_id
            )

    async def statistics(
        self,
    ) -> dict[str, int]:

        async with self._lock:

            return {
                "connections": len(
                    self._connections
                ),
                "tenants": len(
                    self._tenant_connections
                ),
                "users": len(
                    self._user_connections
                ),
            }


connection_manager = ConnectionManager()


# ============================================================
# WEBSOCKET AUTHENTICATION CONTRACT
# ============================================================

# Your authentication middleware must:
#
# 1. Validate a trusted session or token.
# 2. Load the user's active tenant membership.
# 3. Construct backend.permissions.Principal.
# 4. Store it in websocket.scope["state"].
#
# Do not accept tenant_id, roles, or
# permissions directly from the client.


def get_websocket_principal(
    websocket: WebSocket,
) -> Principal | None:

    state = websocket.scope.get(
        "state",
        {},
    )

    principal = state.get(
        "principal"
    )

    if isinstance(
        principal,
        Principal,
    ):
        return principal

    return None


# ============================================================
# WEBSOCKET ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/realtime",
    tags=["Realtime"],
)


@router.websocket("/ws")
async def realtime_websocket(
    websocket: WebSocket,
):

    principal = get_websocket_principal(
        websocket
    )

    if principal is None:

        await websocket.close(
            code=1008
        )

        return

    try:

        connection = (
            await connection_manager.connect(
                websocket,
                principal,
            )
        )

    except (
        PermissionError,
        ConnectionError,
    ):

        await websocket.close(
            code=1008
        )

        return

    try:

        while True:

            try:

                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=(
                        HEARTBEAT_INTERVAL_SECONDS
                    ),
                )

            except asyncio.TimeoutError:

                await connection_manager.send_to_connection(
                    connection.connection_id,
                    RealtimeMessage(
                        event=RealtimeEventType.PING,
                        data={},
                    ),
                )

                continue

            if len(
                raw.encode("utf-8")
            ) > MAX_MESSAGE_BYTES:

                await websocket.close(
                    code=1009
                )

                break

            try:
                message = json.loads(
                    raw
                )

            except json.JSONDecodeError:

                await connection_manager.send_to_connection(
                    connection.connection_id,
                    RealtimeMessage(
                        event=RealtimeEventType.ERROR,
                        data={
                            "code": "INVALID_JSON",
                        },
                    ),
                )

                continue

            if not isinstance(
                message,
                dict,
            ):
                continue

            event = message.get(
                "event"
            )

            if event == "pong":

                await connection_manager.heartbeat(
                    connection.connection_id
                )

            elif event == "ping":

                await connection_manager.heartbeat(
                    connection.connection_id
                )

                await connection_manager.send_to_connection(
                    connection.connection_id,
                    RealtimeMessage(
                        event=RealtimeEventType.PONG,
                        data={},
                    ),
                )

            else:

                await connection_manager.send_to_connection(
                    connection.connection_id,
                    RealtimeMessage(
                        event=RealtimeEventType.ERROR,
                        data={
                            "code": "UNSUPPORTED_EVENT",
                        },
                    ),
                )

    except WebSocketDisconnect:
        pass

    finally:

        await connection_manager.disconnect(
            connection.connection_id
        )


# ============================================================
# APPLICATION BROADCAST HELPERS
# ============================================================

async def publish_inventory_update(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
) -> int:

    return await connection_manager.broadcast_to_tenant(
        tenant_id=tenant_id,
        required_permission=(
            Permission.INVENTORY_READ
        ),
        message=RealtimeMessage(
            event=(
                RealtimeEventType.INVENTORY_UPDATED
            ),
            data={
                "product_id": product_id,
                "warehouse_id": warehouse_id,
            },
        ),
    )


async def publish_low_stock_alert(
    *,
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
    severity: str,
) -> int:

    return await connection_manager.broadcast_to_tenant(
        tenant_id=tenant_id,
        required_permission=(
            Permission.INVENTORY_READ
        ),
        message=RealtimeMessage(
            event=(
                RealtimeEventType.LOW_STOCK_ALERT
            ),
            data={
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "severity": severity,
            },
        ),
    )


async def publish_agent_progress(
    *,
    tenant_id: str,
    user_id: str,
    execution_id: str,
    progress_percent: int,
    message: str,
) -> int:

    return await connection_manager.send_to_user(
        tenant_id=tenant_id,
        user_id=user_id,
        message=RealtimeMessage(
            event=(
                RealtimeEventType.AGENT_PROGRESS
            ),
            data={
                "execution_id": execution_id,
                "progress_percent": (
                    max(
                        0,
                        min(
                            100,
                            progress_percent,
                        ),
                    )
                ),
                "message": message[:500],
            },
        ),
    )
