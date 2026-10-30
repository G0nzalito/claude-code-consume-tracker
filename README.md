# Claude Code usage widget for Glance

Two progress bars, refreshed every minute: the **5-hour session** limit and the
**weekly** limit of your Claude subscription. A small sidecar container reads
your Claude Code login, asks Anthropic for the current usage and serves it to
Glance as an `extension` widget.

Claude has no daily limit. Its short window is the rolling 5-hour session, so
that is what the first bar shows.

## Setup

### 1. Give the container a Claude login

On the homelab host, log in to Claude Code once so it has its own credentials:

```sh
claude          # then run /login
mkdir -p data && cp ~/.claude/.credentials.json data/credentials.json
```

Use a separate login rather than copying the one from your laptop. Refresh
tokens rotate, so if two machines share one login, whichever refreshes second
gets logged out. (On macOS the login lives in the Keychain item
`Claude Code-credentials`, not in a file.)

The container refreshes the access token itself and writes the new tokens back
to `data/credentials.json`, so the directory must stay writable.

### 2. Start the sidecar

Add the service from `docker-compose.yml` to the compose file that runs Glance
(same network), then:

```sh
docker compose up -d --build claude-usage
```

### 3. Add the widget to `glance.yml`

```yaml
- type: extension
  url: http://claude-usage:8080
  cache: 1m
  allow-potentially-dangerous-html: true
```

Restart Glance. `allow-potentially-dangerous-html` is required because the bars
are HTML; the service is only reachable inside your compose network.

## Behaviour

- Bars turn orange at 70% and red at 90%.
- Anthropic is queried at most once every 45 s (`MIN_FETCH_INTERVAL`).
- If a refresh fails, the last good numbers stay on screen with a warning.
- If login has expired for good (`invalid_grant`), repeat step 1.

## Caveats

The usage endpoint (`api.anthropic.com/api/oauth/usage`) is not officially
documented; it is the one Claude Code's own `/usage` screen uses. Anthropic can
change it. The service reads the `limits` list and falls back to the older
`five_hour` / `seven_day` fields.
