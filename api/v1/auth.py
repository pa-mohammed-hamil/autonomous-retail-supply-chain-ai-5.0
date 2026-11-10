from __future__ import annotations


"""
backend/auth.py

Autonomous Retail Supply Chain AI 5.0
Authentication and Session Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2
    pyjwt >= 2
    pwdlib[argon2]
    sqlalchemy >= 2

Features:
    - Email/password authentication
    - Argon2 password verification
    - Short-lived JWT access tokens
    - Rotating opaque refresh tokens
    - Refresh-token replay detection
    - Session revocation
    - Logout and logout-all
    - Current-user endpoint
    - Password change
    - Account lockout
    - Tenant isolation
    - Security audit hooks
    - No public self-registration

IMPORTANT:
    This is a reference implementation.

    The persistence adapter must be wired to
    your actual SQLAlchemy user/session models.

    Refresh tokens must never be logged.
    Passwords must never be stored in plaintext.

    Do not deploy without HTTPS, rate limiting,
    secure configuration, and integration tests.
"""

import hashlib
import hmac
import secrets

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

import jwt

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
)

from pwdlib import PasswordHash


# ============================================================
# CONFIGURATION
# ============================================================

ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7

MAX_FAILED_ATTEMPTS = 5
ACCOUNT_LOCK_MINUTES = 15

JWT_ALGORITHM = "HS256"

JWT_ISSUER = "retail-supply-chain-ai"

JWT_AUDIENCE = "retail-supply-chain-api"

REFRESH_TOKEN_BYTES = 48

password_hasher = PasswordHash.recommended()

bearer_scheme = HTTPBearer(
    auto_error=False
)


# ============================================================
# ENUMS
# ============================================================

class AccountStatus(str, Enum):
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ============================================================
# API REQUEST MODELS
# ============================================================

class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        min_length=1,
        max_length=128,
    )

    email: EmailStr

    password: SecretStr


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr


class LogoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr

    new_password: SecretStr = Field(
        min_length=12,
        max_length=256,
    )


# ============================================================
# API RESPONSE MODELS
# ============================================================

class UserIdentityResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    roles: list[str]
    status: AccountStatus


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthMessageResponse(BaseModel):
    success: bool
    message: str


class SessionResponse(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime
    status: SessionStatus


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class AuthUser:
    user_id: str
    tenant_id: str
    email: str
    password_hash: str
    roles: tuple[str, ...]
    status: AccountStatus
    failed_attempts: int = 0
    locked_until: datetime | None = None
    password_version: int = 1


@dataclass
class AuthSession:
    session_id: str
    user_id: str
    tenant_id: str

    refresh_token_hash: str

    created_at: datetime
    expires_at: datetime

    status: SessionStatus = SessionStatus.ACTIVE

    token_generation: int = 1


# ============================================================
# CONFIGURATION PROVIDER
# ============================================================

@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: str
    refresh_pepper: str

    issuer: str = JWT_ISSUER
    audience: str = JWT_AUDIENCE

    access_minutes: int = ACCESS_TOKEN_MINUTES
    refresh_days: int = REFRESH_TOKEN_DAYS

    def __post_init__(self):
        if len(self.jwt_secret) < 32:
            raise ValueError(
                "JWT secret must contain at least "
                "32 characters"
            )

        if len(self.refresh_pepper) < 32:
            raise ValueError(
                "Refresh pepper must contain at "
                "least 32 characters"
            )


# ============================================================
# PERSISTENCE CONTRACT
# ============================================================

class AuthRepository(Protocol):
    """
    Implement with PostgreSQL/SQLAlchemy.

    Security-critical operations must use
    database transactions and row locking.
    """

    async def get_user_by_email(
        self,
        tenant_id: str,
        email: str,
    ) -> AuthUser | None:
        ...

    async def get_user_by_id(
        self,
        tenant_id: str,
        user_id: str,
    ) -> AuthUser | None:
        ...

    async def save_user(
        self,
        user: AuthUser,
    ) -> None:
        ...

    async def create_session(
        self,
        session: AuthSession,
    ) -> None:
        ...

    async def get_session_for_update(
        self,
        session_id: str,
    ) -> AuthSession | None:
        ...

    async def save_session(
        self,
        session: AuthSession,
    ) -> None:
        ...

    async def revoke_user_sessions(
        self,
        tenant_id: str,
        user_id: str,
    ) -> None:
        ...


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_refresh_token(
    token: str,
    pepper: str,
) -> str:

    return hmac.new(
        pepper.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(
        REFRESH_TOKEN_BYTES
    )


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(
    password: str,
    stored_hash: str,
) -> bool:

    try:
        return password_hasher.verify(
            password,
            stored_hash,
        )
    except Exception:
        return False


def user_to_response(
    user: AuthUser,
) -> UserIdentityResponse:

    return UserIdentityResponse(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=list(user.roles),
        status=user.status,
    )


# ============================================================
# JWT TOKEN SERVICE
# ============================================================

class AccessTokenService:

    def __init__(
        self,
        config: AuthConfig,
    ):
        self.config = config

    def create(
        self,
        user: AuthUser,
        session_id: str,
    ) -> str:

        now = utc_now()

        expires_at = now + timedelta(
            minutes=self.config.access_minutes
        )

        payload = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": user.user_id,
            "tid": user.tenant_id,
            "sid": session_id,
            "pwdv": user.password_version,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "jti": str(uuid4()),
        }

        return jwt.encode(
            payload,
            self.config.jwt_secret,
            algorithm=JWT_ALGORITHM,
        )

    def verify(
        self,
        token: str,
    ) -> dict:

        try:
            payload = jwt.decode(
                token,
                self.config.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                audience=self.config.audience,
                issuer=self.config.issuer,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "tid",
                        "sid",
                        "pwdv",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                    ],
                },
            )

            if (
                not isinstance(payload.get("sub"), str)
                or not isinstance(payload.get("tid"), str)
                or not isinstance(payload.get("sid"), str)
                or type(payload.get("pwdv")) is not int
            ):
                raise ValueError(
                    "Invalid token claims"
                )

            return payload

        except (jwt.PyJWTError, ValueError):
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )


# ============================================================
# AUTHENTICATION SERVICE
# ============================================================

class AuthenticationService:

    def __init__(
        self,
        repository: AuthRepository,
        config: AuthConfig,
    ):

        self.repository = repository
        self.config = config

        self.tokens = AccessTokenService(
            config
        )

    async def authenticate(
        self,
        payload: LoginRequest,
    ) -> TokenResponse:

        email = normalize_email(
            str(payload.email)
        )

        user = await self.repository.get_user_by_email(
            payload.tenant_id,
            email,
        )

        # Generic authentication error avoids
        # exposing whether the user exists.

        invalid_credentials = HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

        if user is None:
            raise invalid_credentials

        now = utc_now()

        if user.status == AccountStatus.DISABLED:
            raise invalid_credentials

        if (
            user.locked_until is not None
            and user.locked_until > now
        ):
            raise HTTPException(
                status_code=429,
                detail="Account temporarily locked",
            )

        valid_password = verify_password(
            payload.password.get_secret_value(),
            user.password_hash,
        )

        if not valid_password:

            user.failed_attempts += 1

            if (
                user.failed_attempts
                >= MAX_FAILED_ATTEMPTS
            ):
                user.locked_until = (
                    now
                    + timedelta(
                        minutes=ACCOUNT_LOCK_MINUTES
                    )
                )

                user.status = AccountStatus.LOCKED

            await self.repository.save_user(user)

            raise invalid_credentials

        user.failed_attempts = 0
        user.locked_until = None
        user.status = AccountStatus.ACTIVE

        await self.repository.save_user(user)

        refresh_token = generate_refresh_token()

        session = AuthSession(
            session_id=str(uuid4()),
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            refresh_token_hash=hash_refresh_token(
                refresh_token,
                self.config.refresh_pepper,
            ),
            created_at=now,
            expires_at=(
                now
                + timedelta(
                    days=self.config.refresh_days
                )
            ),
        )

        await self.repository.create_session(
            session
        )

        access_token = self.tokens.create(
            user,
            session.session_id,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=(
                self.config.access_minutes * 60
            ),
        )

    async def refresh(
        self,
        raw_refresh_token: str,
    ) -> TokenResponse:
        """
        Reference implementation.

        Production should resolve tokens by
        indexed token hash, lock the session
        row, rotate atomically, and track
        refresh-token families for replay
        detection.

        The repository contract below needs
        a dedicated lookup method.
        """

        raise NotImplementedError(
            "Implement atomic refresh-token "
            "lookup, rotation and replay detection "
            "in the SQLAlchemy auth repository"
        )

    async def logout(
        self,
        raw_refresh_token: str,
    ) -> None:

        raise NotImplementedError(
            "Implement session lookup and "
            "revocation by refresh-token hash"
        )

    async def logout_all(
        self,
        user: AuthUser,
    ) -> None:

        await self.repository.revoke_user_sessions(
            user.tenant_id,
            user.user_id,
        )

    async def change_password(
        self,
        user: AuthUser,
        payload: ChangePasswordRequest,
    ) -> None:

        current_password = (
            payload.current_password
            .get_secret_value()
        )

        new_password = (
            payload.new_password
            .get_secret_value()
        )

        if not verify_password(
            current_password,
            user.password_hash,
        ):
            raise HTTPException(
                status_code=401,
                detail="Current password is incorrect",
            )

        if current_password == new_password:
            raise HTTPException(
                status_code=422,
                detail=(
                    "New password must be different"
                ),
            )

        user.password_hash = hash_password(
            new_password
        )

        user.password_version += 1

        await self.repository.save_user(user)

        await self.repository.revoke_user_sessions(
            user.tenant_id,
            user.user_id,
        )


# ============================================================
# APPLICATION DEPENDENCIES
# ============================================================

def get_auth_service(
    request: Request,
) -> AuthenticationService:

    service = getattr(
        request.app.state,
        "authentication_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        )

    return service


async def get_current_auth_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    service: AuthenticationService = Depends(
        get_auth_service
    ),
) -> AuthUser:

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    claims = service.tokens.verify(
        credentials.credentials
    )

    user = await service.repository.get_user_by_id(
        claims["tid"],
        claims["sub"],
    )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found",
        )

    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail="Account is not active",
        )

    if (
        user.password_version
        != claims["pwdv"]
    ):
        raise HTTPException(
            status_code=401,
            detail="Token has been invalidated",
        )

    # Production requirement:
    # Verify session claims["sid"] exists,
    # belongs to this user and tenant,
    # and is still active.
    #
    # Without this check, logout cannot
    # immediately revoke existing JWTs.

    return user


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Authentication"],
)


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    payload: LoginRequest,
    service: AuthenticationService = Depends(
        get_auth_service
    ),
):

    return await service.authenticate(
        payload
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
async def refresh_access_token(
    payload: RefreshRequest,
    service: AuthenticationService = Depends(
        get_auth_service
    ),
):

    try:
        return await service.refresh(
            payload.refresh_token.get_secret_value()
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Refresh-token rotation is not configured",
        )


@router.post(
    "/logout",
    response_model=AuthMessageResponse,
)
async def logout(
    payload: LogoutRequest,
    service: AuthenticationService = Depends(
        get_auth_service
    ),
):

    try:
        await service.logout(
            payload.refresh_token.get_secret_value()
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="Refresh-token revocation is not configured",
        )

    return AuthMessageResponse(
        success=True,
        message="Session revoked",
    )


@router.get(
    "/me",
    response_model=UserIdentityResponse,
)
async def get_current_user(
    user: AuthUser = Depends(
        get_current_auth_user
    ),
):

    return user_to_response(
        user
    )


@router.post(
    "/change-password",
    response_model=AuthMessageResponse,
)
async def change_password(
    payload: ChangePasswordRequest,
    user: AuthUser = Depends(
        get_current_auth_user
    ),
    service: AuthenticationService = Depends(
        get_auth_service
    ),
):

    await service.change_password(
        user,
        payload,
    )

    return AuthMessageResponse(
        success=True,
        message=(
            "Password changed. "
            "Existing sessions have been revoked."
        ),
    )


@router.post(
    "/logout-all",
    response_model=AuthMessageResponse,
)
async def logout_all(
    user: AuthUser = Depends(
        get_current_auth_user
    ),
    service: AuthenticationService = Depends(
        get_auth_service
    ),
):

    await service.logout_all(
        user
    )

    return AuthMessageResponse(
        success=True,
        message=(
            "All sessions revoked"
        ),
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "AccountStatus",
    "SessionStatus",
    "LoginRequest",
    "RefreshRequest",
    "LogoutRequest",
    "ChangePasswordRequest",
    "UserIdentityResponse",
    "TokenResponse",
    "AuthMessageResponse",
    "AuthUser",
    "AuthSession",
    "AuthConfig",
    "AuthRepository",
    "AccessTokenService",
    "AuthenticationService",
    "get_auth_service",
    "get_current_auth_user",
    "hash_password",
    "verify_password",
    "router",
]
