# Claude Code usage widget for Glance

A small widget for [Glance](https://github.com/glanceapp/glance) that shows your
Claude subscription usage as two progress bars:

- **Session (5h)**: your current 5-hour rolling limit
- **Weekly**: your weekly limit

It refreshes every minute. The bars turn orange at 70% and red at 90%.

It runs as a second container next to Glance, so it needs Docker Compose.

> **Single account only.** This shows the usage of the one Claude login you give
> it. Don't expose it to the internet.

## What you need

- A Claude subscription (Pro or Max) and Claude Code installed on the machine
  where you run this
- Glance running with Docker Compose
- Git and Docker on the homelab host

## Quick start

Do these steps on the machine that runs Glance.

### 1. Clone this repository next to your Glance files

```sh
cd /path/to/your/glance          # the folder with your compose file and glance.yml
git clone https://github.com/G0nzalito/claude-code-consume-tracker.git
```

Your folder should look like this:

```text
glance/
├── compose.yaml                 # your Glance compose file
├── glance.yml                   # your Glance config
└── claude-code-consume-tracker/
```

### 2. Create a login for the widget

The widget needs its own copy of a Claude Code login. Log in once on the
homelab host:

```sh
claude            # then type /login and follow the browser steps
```

Copy the credentials into the project's `data/` folder:

```sh
cd claude-code-consume-tracker
mkdir -p data
cp ~/.claude/.credentials.json data/credentials.json
cd ..
```

**Notes:**

- On **macOS**, Claude Code keeps the login in the Keychain, not in that file.
  Export it from the Keychain instead (this prints it to a file, so keep it
  private):

  ```sh
  mkdir -p data
  security find-generic-password -s "Claude Code-credentials" -w > data/credentials.json
  ```

  Remember to run this from the `claude-code-consume-tracker` folder.
- **Don't share one login between two machines or tools.** Login tokens rotate
  on refresh. If your laptop and the widget use the same login, whichever
  refreshes second gets logged out. After copying the file, use the widget's
  copy only.
- The widget refreshes its token by itself and saves the new one to
  `data/credentials.json`, so keep that folder writable.

### 3. Add the service to your Glance compose file

Add this under `services:` in your compose file (the same file that runs
Glance):

```yaml
services:
  # ...your existing glance service...

  claude-usage:
    build: ./claude-code-consume-tracker
    container_name: claude-usage
    restart: unless-stopped
    environment:
      CREDENTIALS_FILE: /data/credentials.json
    volumes:
      - ./claude-code-consume-tracker/data:/data
    # No "ports:" section on purpose. Glance reaches it over the compose network.
```

If Glance is in a different compose file, put both services on the same Docker
network. The sidecar is reached by its service name, `claude-usage`.

### 4. Start the widget

```sh
docker compose up -d --build claude-usage
```

Check that it is healthy:

```sh
docker compose ps claude-usage                                   # STATUS: "healthy" after ~30 s
docker compose exec claude-usage wget -qO- http://127.0.0.1:8080/healthz   # prints "ok"
```

### 5. Add the widget to Glance

Copy the block from [`glance-widget.yml`](glance-widget.yml) into a column in
your `glance.yml`:

```yaml
- type: extension
  url: http://claude-usage:8080
  cache: 1m
  allow-potentially-dangerous-html: true
```

Then restart Glance:

```sh
docker compose restart glance
```

The widget appears as **Claude Code**.

`allow-potentially-dangerous-html: true` is required because the widget returns
HTML. It is safe here because the source is your own container, reachable only
from your compose network.

## Check that it works

1. Open your Glance dashboard. You should see two bars with percentages and
   reset times.
2. Compare the numbers with `/usage` in Claude Code. They should match.
3. Watch the logs:

   ```sh
   docker compose logs -f claude-usage
   ```

   You should see `listening on :8080`. Errors show up here.

## Troubleshooting

| You see | Cause | Fix |
| --- | --- | --- |
| `... not found - see README, step 2` | `data/credentials.json` is missing or in the wrong folder | Redo step 2. Check the volume path in step 3. |
| `HTTP 400 ... invalid_grant` | The login has expired or was logged out | Log in again with `claude` and `/login`, then copy the file again (step 2). |
| `HTTP 403 ... error code: 1010` | Cloudflare rejected the request | Update to the latest version of this repo. |
| `Showing data from Nm ago - refresh failing` | A refresh failed, but old numbers are still shown | Usually temporary. Check the logs. If it persists, redo step 2. |
| `No such host` in Glance | Glance and `claude-usage` are not on the same network | Put both services in the same compose file, or on the same network. |
| Widget shows raw HTML tags as text | `allow-potentially-dangerous-html` is missing | Add it as shown in step 5. |
| Container is `unhealthy` | The server did not start | Run `docker compose logs claude-usage`. |

## How it works

1. Glance asks `http://claude-usage:8080` for the widget (once per minute).
2. The sidecar reads the login from `data/credentials.json`.
3. If the access token has expired, it refreshes it and saves the new tokens.
4. It asks Anthropic for your current usage and returns two bars as HTML.
5. If a refresh fails, it keeps showing the last good numbers with a warning.

The sidecar asks Anthropic at most once every 45 seconds, so it stays light on
requests.

## Security

- **Never commit `data/`.** It holds a working login. This repo's `.gitignore`
  already excludes it. Don't remove that rule.
- **Don't publish the port.** The service has no `ports:` entry. Keep it that
  way unless you put authentication in front of it.
- **Don't share the `data/` folder.** Anyone with it can use your Claude login.

## Caveats

- Claude has no daily limit, so the first bar shows the 5-hour session window.
- The usage endpoint (`api.anthropic.com/api/oauth/usage`) is not officially
  documented. It is the one Claude Code's `/usage` screen uses. Anthropic can
  change it at any time. The widget reads the newer `limits` list and falls
  back to the older `five_hour` and `seven_day` fields.
- It works only for one account per running container. For several people,
  run one container per account, each with its own `data/` folder.
