"""SQLite-backed identity, OAuth, and per-user integration storage."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from wai_music.auth.security import (
    decrypt_text,
    encrypt_text,
    hash_password,
    new_opaque_token,
    token_fingerprint,
    verify_password,
)


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    email: str
    created_at: str


@dataclass(frozen=True)
class SessionRecord:
    user_id: str
    email: str
    created_at: str
    expires_at: int


@dataclass(frozen=True)
class SpotifyConnection:
    user_id: str
    spotify_user_id: str
    token_payload: dict[str, Any]
    updated_at: str


@dataclass(frozen=True)
class PendingAuthorization:
    request_id: str
    client_id: str
    params: AuthorizationParams
    expires_at: int


@dataclass(frozen=True)
class PersonalAccessTokenRecord:
    token_fingerprint: str
    user_id: str
    label: str
    created_at: str
    expires_at: int
    last4: str


class SQLiteAuthStore:
    def __init__(self, path: str | Path, *, secret_key: str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_key = secret_key
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_fingerprint TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES auth_users(user_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spotify_connections (
                    user_id TEXT PRIMARY KEY,
                    spotify_user_id TEXT NOT NULL,
                    token_payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES auth_users(user_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spotify_oauth_states (
                    state TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    return_to TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES auth_users(user_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_clients (
                    client_id TEXT PRIMARY KEY,
                    client_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_pending_requests (
                    request_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
                    code TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                    token_fingerprint TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                    token_fingerprint TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_access_tokens (
                    token_fingerprint TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    last4 TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES auth_users(user_id)
                )
                """
            )

    def create_user(self, *, email: str, password: str) -> UserRecord:
        normalized_email = email.strip().lower()
        if "@" not in normalized_email or " " in normalized_email:
            raise ValueError("email must look like a valid address")
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters long")
        user_id = new_opaque_token(bytes_length=16)
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO auth_users(user_id, email, password_hash, created_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (user_id, normalized_email, hash_password(password), created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"user already exists for email {normalized_email!r}") from exc
        return UserRecord(user_id=user_id, email=normalized_email, created_at=created_at)

    def authenticate_user(self, *, email: str, password: str) -> UserRecord | None:
        normalized_email = email.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, email, password_hash, created_at
                FROM auth_users
                WHERE email = ?
                """,
                (normalized_email,),
            ).fetchone()
        if row is None:
            return None
        if not verify_password(password, str(row["password_hash"])):
            return None
        return UserRecord(
            user_id=str(row["user_id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
        )

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, email, created_at
                FROM auth_users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=str(row["user_id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
        )

    def create_session(self, *, user_id: str, ttl_seconds: int) -> str:
        session_token = new_opaque_token()
        created_at = datetime.now(UTC).isoformat()
        expires_at = int(time.time()) + ttl_seconds
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions(token_fingerprint, user_id, created_at, expires_at)
                VALUES(?, ?, ?, ?)
                """,
                (token_fingerprint(session_token), user_id, created_at, expires_at),
            )
        return session_token

    def get_session(self, session_token: str) -> SessionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.user_id, u.email, s.created_at, s.expires_at
                FROM auth_sessions s
                JOIN auth_users u ON u.user_id = s.user_id
                WHERE s.token_fingerprint = ?
                """,
                (token_fingerprint(session_token),),
            ).fetchone()
            if row is None:
                return None
            if int(row["expires_at"]) < int(time.time()):
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_fingerprint = ?",
                    (token_fingerprint(session_token),),
                )
                return None
        return SessionRecord(
            user_id=str(row["user_id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
            expires_at=int(row["expires_at"]),
        )

    def delete_session(self, session_token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_fingerprint = ?",
                (token_fingerprint(session_token),),
            )

    def create_spotify_oauth_state(self, *, user_id: str, ttl_seconds: int, return_to: str) -> str:
        state = new_opaque_token()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO spotify_oauth_states(state, user_id, return_to, expires_at)
                VALUES(?, ?, ?, ?)
                """,
                (state, user_id, return_to, int(time.time()) + ttl_seconds),
            )
        return state

    def consume_spotify_oauth_state(self, state: str) -> tuple[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, return_to, expires_at
                FROM spotify_oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()
            connection.execute("DELETE FROM spotify_oauth_states WHERE state = ?", (state,))
        if row is None or int(row["expires_at"]) < int(time.time()):
            return None
        return str(row["user_id"]), str(row["return_to"])

    def upsert_spotify_connection(
        self,
        *,
        user_id: str,
        spotify_user_id: str,
        token_payload: dict[str, Any],
    ) -> None:
        updated_at = datetime.now(UTC).isoformat()
        encrypted_payload = encrypt_text(self._secret_key, json.dumps(token_payload))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO spotify_connections(user_id, spotify_user_id, token_payload, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    spotify_user_id = excluded.spotify_user_id,
                    token_payload = excluded.token_payload,
                    updated_at = excluded.updated_at
                """,
                (user_id, spotify_user_id, encrypted_payload, updated_at),
            )

    def get_spotify_connection(self, user_id: str) -> SpotifyConnection | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, spotify_user_id, token_payload, updated_at
                FROM spotify_connections
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        token_payload = json.loads(decrypt_text(self._secret_key, str(row["token_payload"])))
        if not isinstance(token_payload, dict):
            raise ValueError("spotify connection payload must be a JSON object")
        return SpotifyConnection(
            user_id=str(row["user_id"]),
            spotify_user_id=str(row["spotify_user_id"]),
            token_payload=token_payload,
            updated_at=str(row["updated_at"]),
        )

    def save_oauth_client(self, client_info: OAuthClientInformationFull) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_clients(client_id, client_json, created_at)
                VALUES(?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    client_json = excluded.client_json
                """,
                (
                    client_info.client_id,
                    client_info.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_oauth_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT client_json FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(str(row["client_json"]))

    def create_pending_authorization(
        self,
        *,
        client_id: str,
        params: AuthorizationParams,
        ttl_seconds: int,
    ) -> str:
        request_id = new_opaque_token()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_pending_requests(request_id, client_id, params_json, expires_at)
                VALUES(?, ?, ?, ?)
                """,
                (
                    request_id,
                    client_id,
                    params.model_dump_json(),
                    int(time.time()) + ttl_seconds,
                ),
            )
        return request_id

    def get_pending_authorization(self, request_id: str) -> PendingAuthorization | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_id, client_id, params_json, expires_at
                FROM oauth_pending_requests
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        if row is None or int(row["expires_at"]) < int(time.time()):
            return None
        return PendingAuthorization(
            request_id=str(row["request_id"]),
            client_id=str(row["client_id"]),
            params=AuthorizationParams.model_validate_json(str(row["params_json"])),
            expires_at=int(row["expires_at"]),
        )

    def delete_pending_authorization(self, request_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM oauth_pending_requests WHERE request_id = ?",
                (request_id,),
            )

    def create_authorization_code(
        self,
        *,
        user_id: str,
        request: PendingAuthorization,
        ttl_seconds: int,
    ) -> str:
        code = new_opaque_token()
        expires_at = int(time.time()) + ttl_seconds
        payload = {
            "user_id": user_id,
            "client_id": request.client_id,
            "scopes": request.params.scopes or [],
            "code_challenge": request.params.code_challenge,
            "redirect_uri": str(request.params.redirect_uri),
            "redirect_uri_provided_explicitly": request.params.redirect_uri_provided_explicitly,
            "resource": request.params.resource,
            "expires_at": expires_at,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_authorization_codes(code, user_id, client_id, payload_json, expires_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    code,
                    user_id,
                    request.client_id,
                    json.dumps(payload),
                    expires_at,
                ),
            )
        self.delete_pending_authorization(request.request_id)
        return code

    def get_authorization_code_payload(self, code: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, expires_at
                FROM oauth_authorization_codes
                WHERE code = ?
                """,
                (code,),
            ).fetchone()
        if row is None or int(row["expires_at"]) < int(time.time()):
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise ValueError("authorization code payload must be a JSON object")
        return payload

    def consume_authorization_code(self, code: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM oauth_authorization_codes WHERE code = ?", (code,))

    def issue_oauth_token_pair(
        self,
        *,
        user_id: str,
        client_id: str,
        scopes: list[str],
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        resource: str | None = None,
    ) -> OAuthToken:
        access_token = new_opaque_token()
        refresh_token = new_opaque_token()
        access_payload = {
            "client_id": client_id,
            "user_id": user_id,
            "scopes": scopes,
            "expires_at": int(time.time()) + access_ttl_seconds,
            "resource": resource,
        }
        refresh_payload = {
            "client_id": client_id,
            "user_id": user_id,
            "scopes": scopes,
            "expires_at": int(time.time()) + refresh_ttl_seconds,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_access_tokens(token_fingerprint, payload_json)
                VALUES(?, ?)
                """,
                (token_fingerprint(access_token), json.dumps(access_payload)),
            )
            connection.execute(
                """
                INSERT INTO oauth_refresh_tokens(token_fingerprint, payload_json)
                VALUES(?, ?)
                """,
                (token_fingerprint(refresh_token), json.dumps(refresh_payload)),
            )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=access_ttl_seconds,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

    def create_personal_access_token(
        self,
        *,
        user_id: str,
        label: str,
        ttl_seconds: int,
        scopes: list[str],
        resource: str | None = None,
    ) -> tuple[PersonalAccessTokenRecord, str]:
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("token label is required")
        if len(normalized_label) > 80:
            raise ValueError("token label must be 80 characters or fewer")
        raw_token = new_opaque_token()
        created_at = datetime.now(UTC).isoformat()
        expires_at = int(time.time()) + ttl_seconds
        fingerprint = token_fingerprint(raw_token)
        payload = {
            "client_id": "personal-access-token",
            "user_id": user_id,
            "scopes": scopes,
            "expires_at": expires_at,
            "resource": resource,
            "kind": "personal_access_token",
            "label": normalized_label,
        }
        record = PersonalAccessTokenRecord(
            token_fingerprint=fingerprint,
            user_id=user_id,
            label=normalized_label,
            created_at=created_at,
            expires_at=expires_at,
            last4=raw_token[-4:],
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_access_tokens(token_fingerprint, payload_json)
                VALUES(?, ?)
                """,
                (fingerprint, json.dumps(payload)),
            )
            connection.execute(
                """
                INSERT INTO personal_access_tokens(
                    token_fingerprint,
                    user_id,
                    label,
                    created_at,
                    expires_at,
                    last4
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    record.token_fingerprint,
                    record.user_id,
                    record.label,
                    record.created_at,
                    record.expires_at,
                    record.last4,
                ),
            )
        return record, raw_token

    def list_personal_access_tokens(self, user_id: str) -> list[PersonalAccessTokenRecord]:
        now = int(time.time())
        with self._connect() as connection:
            expired_rows = connection.execute(
                """
                SELECT token_fingerprint
                FROM personal_access_tokens
                WHERE user_id = ? AND expires_at < ?
                """,
                (user_id, now),
            ).fetchall()
            for row in expired_rows:
                fingerprint = str(row["token_fingerprint"])
                connection.execute(
                    "DELETE FROM personal_access_tokens WHERE token_fingerprint = ?",
                    (fingerprint,),
                )
                connection.execute(
                    "DELETE FROM oauth_access_tokens WHERE token_fingerprint = ?",
                    (fingerprint,),
                )
            rows = connection.execute(
                """
                SELECT token_fingerprint, user_id, label, created_at, expires_at, last4
                FROM personal_access_tokens
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [
            PersonalAccessTokenRecord(
                token_fingerprint=str(row["token_fingerprint"]),
                user_id=str(row["user_id"]),
                label=str(row["label"]),
                created_at=str(row["created_at"]),
                expires_at=int(row["expires_at"]),
                last4=str(row["last4"]),
            )
            for row in rows
        ]

    def revoke_personal_access_token(self, *, user_id: str, token_fingerprint_value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM personal_access_tokens
                WHERE token_fingerprint = ? AND user_id = ?
                """,
                (token_fingerprint_value, user_id),
            )
            connection.execute(
                "DELETE FROM oauth_access_tokens WHERE token_fingerprint = ?",
                (token_fingerprint_value,),
            )

    def get_access_token_payload(self, token: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM oauth_access_tokens
                WHERE token_fingerprint = ?
                """,
                (token_fingerprint(token),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise ValueError("access token payload must be a JSON object")
        return payload

    def delete_access_token(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM oauth_access_tokens WHERE token_fingerprint = ?",
                (token_fingerprint(token),),
            )

    def get_refresh_token_payload(self, token: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM oauth_refresh_tokens
                WHERE token_fingerprint = ?
                """,
                (token_fingerprint(token),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise ValueError("refresh token payload must be a JSON object")
        return payload

    def delete_refresh_token(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM oauth_refresh_tokens WHERE token_fingerprint = ?",
                (token_fingerprint(token),),
            )
