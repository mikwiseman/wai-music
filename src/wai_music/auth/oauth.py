"""OAuth provider and token verifier for hosted wai-music MCP."""

from __future__ import annotations

import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenVerifier,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl

from wai_music.auth.store import PendingAuthorization, SQLiteAuthStore
from wai_music.settings import WaiMusicSettings


class WaiAuthorizationCode(AuthorizationCode):
    user_id: str


class WaiRefreshToken(RefreshToken):
    user_id: str


class WaiAccessToken(AccessToken):
    user_id: str


def build_auth_settings(settings: WaiMusicSettings) -> AuthSettings:
    issuer_url = settings.oauth_issuer_url
    resource_server_url = settings.oauth_resource_server_url
    if issuer_url is None or resource_server_url is None:
        raise RuntimeError("public_base_url must be configured for hosted OAuth mode")
    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer_url),
        resource_server_url=AnyHttpUrl(resource_server_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=settings.oauth_required_scopes,
            default_scopes=settings.oauth_required_scopes,
        ),
        required_scopes=settings.oauth_required_scopes,
    )


class WaiOAuthProvider(
    OAuthAuthorizationServerProvider[WaiAuthorizationCode, WaiRefreshToken, WaiAccessToken],
    TokenVerifier,
):
    def __init__(self, *, store: SQLiteAuthStore, settings: WaiMusicSettings) -> None:
        self._store = store
        self._settings = settings

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._store.get_oauth_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._store.save_oauth_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        request_id = self._store.create_pending_authorization(
            client_id=_client_id(client),
            params=params,
            ttl_seconds=self._settings.oauth_auth_request_ttl_seconds,
        )
        public_base_url = self._settings.public_base_url
        if public_base_url is None:
            raise RuntimeError("public_base_url must be configured for hosted OAuth mode")
        return f"{public_base_url.rstrip('/')}/oauth/approval?request_id={request_id}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> WaiAuthorizationCode | None:
        payload = self._store.get_authorization_code_payload(authorization_code)
        if payload is None:
            return None
        client_id = _client_id(client)
        if payload.get("client_id") != client_id:
            return None
        return WaiAuthorizationCode(
            code=authorization_code,
            scopes=list(payload.get("scopes", [])),
            expires_at=float(payload["expires_at"]) if "expires_at" in payload else time.time() + 1,
            client_id=client_id,
            code_challenge=str(payload["code_challenge"]),
            redirect_uri=AnyHttpUrl(str(payload["redirect_uri"])),
            redirect_uri_provided_explicitly=bool(payload["redirect_uri_provided_explicitly"]),
            resource=payload.get("resource"),
            user_id=str(payload["user_id"]),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: WaiAuthorizationCode,
    ) -> OAuthToken:
        self._store.consume_authorization_code(authorization_code.code)
        return self._store.issue_oauth_token_pair(
            user_id=authorization_code.user_id,
            client_id=_client_id(client),
            scopes=authorization_code.scopes,
            access_ttl_seconds=self._settings.oauth_access_token_ttl_seconds,
            refresh_ttl_seconds=self._settings.oauth_refresh_token_ttl_seconds,
            resource=authorization_code.resource,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> WaiRefreshToken | None:
        payload = self._store.get_refresh_token_payload(refresh_token)
        client_id = _client_id(client)
        if payload is None or payload.get("client_id") != client_id:
            return None
        return WaiRefreshToken(
            token=refresh_token,
            client_id=client_id,
            scopes=list(payload.get("scopes", [])),
            expires_at=int(payload["expires_at"])
            if payload.get("expires_at") is not None
            else None,
            user_id=str(payload["user_id"]),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: WaiRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self._store.delete_refresh_token(refresh_token.token)
        return self._store.issue_oauth_token_pair(
            user_id=refresh_token.user_id,
            client_id=_client_id(client),
            scopes=scopes,
            access_ttl_seconds=self._settings.oauth_access_token_ttl_seconds,
            refresh_ttl_seconds=self._settings.oauth_refresh_token_ttl_seconds,
        )

    async def load_access_token(self, token: str) -> WaiAccessToken | None:
        payload = self._store.get_access_token_payload(token)
        if payload is None:
            return None
        return WaiAccessToken(
            token=token,
            client_id=str(payload["client_id"]),
            scopes=list(payload.get("scopes", [])),
            expires_at=int(payload["expires_at"])
            if payload.get("expires_at") is not None
            else None,
            resource=payload.get("resource"),
            user_id=str(payload["user_id"]),
        )

    async def revoke_token(self, token: WaiAccessToken | WaiRefreshToken) -> None:
        if isinstance(token, WaiRefreshToken):
            self._store.delete_refresh_token(token.token)

    async def verify_token(self, token: str) -> WaiAccessToken | None:
        access_token = await self.load_access_token(token)
        if access_token is None:
            return None
        if access_token.expires_at is not None and access_token.expires_at < int(time.time()):
            return None
        return access_token

    def get_pending_request(self, request_id: str) -> PendingAuthorization | None:
        return self._store.get_pending_authorization(request_id)

    def approve_request(self, *, request_id: str, user_id: str) -> str:
        request = self._store.get_pending_authorization(request_id)
        if request is None:
            raise ValueError("authorization request does not exist or has expired")
        code = self._store.create_authorization_code(
            user_id=user_id,
            request=request,
            ttl_seconds=self._settings.oauth_authorization_code_ttl_seconds,
        )
        return code


def _client_id(client: OAuthClientInformationFull) -> str:
    if client.client_id is None:
        raise RuntimeError("OAuth client_id is missing")
    return client.client_id
