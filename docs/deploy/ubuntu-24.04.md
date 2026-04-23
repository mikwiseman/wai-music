# Deploying `wai-music` on Ubuntu 24.04

This deployment targets `music.waiwai.is` and runs the hosted multi-user web UI plus the MCP endpoint.

## 1. Spotify setup

In Spotify Developer Dashboard, add this redirect URI:

`https://music.waiwai.is/auth/spotify/callback`

Keep the existing local redirect only if you still want the local helper script.

## 2. Server bootstrap

Install Docker and the Compose plugin on the VPS, then create runtime directories:

```bash
apt-get update
apt-get install -y ca-certificates curl git
install -d -m 755 /etc/wai-music /var/lib/wai-music
```

Clone the repo and place the production env file outside the checkout:

```bash
git clone https://github.com/mikwiseman/wai-music.git /opt/wai-music
cp /opt/wai-music/deploy/env/music.waiwai.is.env.example /etc/wai-music/music.env
```

Edit `/etc/wai-music/music.env` and set:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `WAI_MUSIC_SECRET_KEY`

Recommended for the first public beta:

- keep `WAI_MUSIC_ENABLE_PERSONAL_ACCESS_TOKENS=false`
- use the default sign-up/sign-in rate limits unless you have a stronger edge rate limiter in front of the app

## 3. DNS and TLS

Point `music.waiwai.is` at the VPS public IP before starting the stack.

Caddy will provision TLS automatically once the DNS record resolves.

## 4. Start the stack

```bash
cd /opt/wai-music
docker compose up -d --build
```

## 5. Smoke checks

```bash
curl -I https://music.waiwai.is/healthz
curl -I https://music.waiwai.is/
curl -i https://music.waiwai.is/mcp
```

Expected:

- `/healthz` returns `200`
- `/` returns `200`
- `/mcp` without auth returns `401` once hosted OAuth is enabled

## 6. Claude / MCP

Add this remote MCP URL in Claude:

`https://music.waiwai.is/mcp`

The server exposes OAuth metadata and handles browser login plus user consent through the built-in web UI.
