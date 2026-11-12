# Deploying to the production host

The app runs on one shared host from images that GitHub builds. The host never builds anything.
This page is the whole path: build, first-time setup, deploy, check, roll back. [DEPLOY.md](DEPLOY.md)
has the short version of the deploy step and [bedrock-droplet-test.md](bedrock-droplet-test.md) is the
smoke test for a Bedrock draft.

## Why the host does not build

The host has under 2 GB of RAM and already runs other production workloads, including an
`ai-client-engagement` app, authelia, nginx and a Prometheus/Grafana/Loki stack. Building the api
image (onnxruntime, matplotlib) or the web image (`vue-tsc`, `vite build`) there would very likely
invoke the OOM killer, which picks its victim by score and could take a neighbour down. **Never run
`--build` on this host.** `docker-compose.server.yml` resets `build` for both services, so compose has
nothing to build even with the flag.

## How the images are built and published

The **Publish images** workflow (`.github/workflows/publish-images.yml`) runs on every push to `main`
and by hand. It builds two images for linux/amd64 and pushes them to ghcr.io, each tagged
`sha-<short commit>` and `latest`:

| Image | Built from | Target |
| --- | --- | --- |
| `ghcr.io/clivemisiko/cytonn-weekly-api` | `backend/` | `runtime` (the test stage is never published) |
| `ghcr.io/clivemisiko/cytonn-weekly-web` | `frontend/` | `runner` (`vite preview`, port 3000) |

Merge a pull request, wait for that workflow to go green on the Actions tab, then deploy. The proxy
image is the exception: it is not published (see First-time setup).

## What the host holds

One flat folder (the steps below call it `~/cytonn-weekly`) with:

| File | From the repo | Notes |
| --- | --- | --- |
| `docker-compose.yml` | `docker-compose.yml` | The base: api and web. |
| `docker-compose.server.yml` | `deploy/docker-compose.server.yml` | The override for this host. |
| `deploy.sh` | `deploy/deploy.sh` | Pulls and recreates api and web. |
| `Caddyfile` | `deploy/Caddyfile` | Mounted into the proxy. |
| `.env` | none (see `.env.example`) | The api's settings. Server only, never committed. |
| `.env.proxy` | none | The proxy's settings. Server only, never committed. |

`deploy.sh` also works from a git clone (it then runs `git pull --ff-only` first and finds the override
in `deploy/`). On a plain copy it skips the pull, so copy any changed compose file or the Caddyfile by
hand. The `./Caddyfile`, `./.env` and `./.env.proxy` paths in the compose files are relative to the
folder holding `docker-compose.yml`.

## What the override changes

- **Images from ghcr.io, no build.** Both services use `ghcr.io/clivemisiko/cytonn-weekly-<name>:${IMAGE_TAG:-latest}`
  with `build` reset. `deploy.sh` sets `IMAGE_TAG`.
- **The api is published on 8010**, not 8000 (another project holds 8000), and the web on 5173. Both are
  bound to `127.0.0.1`.
- **`mem_limit`:** api 768m, web 256m, proxy 96m. They exist so that if this app does not fit, the kernel
  kills one of its containers and not a neighbour. Raise a limit if a container is killed under real use;
  do not remove it.
- **The api runs as the deploy user's uid** (`user:` in the override) with `HOME` and `MPLCONFIGDIR`
  inside `/app/data`. The image builds a home for uid 10001, but the bind-mounted data folder is owned by
  the deploy user and root was not available to change it. Without the redirect, matplotlib's font cache
  has nowhere to write. Revert both once the data folder is `chown`ed to 10001.
- **The proxy** (`proxy` service) is the only service reachable from outside: port 443 only. It forwards
  to the web container, which proxies `/api` to the api. See Reaching it.

## First-time setup

1. **Create the folder** and copy in the four files from the table above.
2. **Write `.env`** from `.env.example` (names in the next section). `chmod 600 .env .env.proxy`.
3. **Write `.env.proxy`** with the proxy's four settings (next section).
4. **Let the host pull the images.** Make the two ghcr.io packages public (GitHub profile, Packages, the
   package, Package settings, Change visibility): the images hold the built app only, no secrets. Or, if
   they stay private, log the host in once with `docker login ghcr.io` using a token that has only
   `read:packages`, entered at the prompt.
5. **Get the proxy image onto the host.** It is built from `Dockerfile.proxy` (Caddy with a DNS module)
   and is not published:
   ```sh
   docker build -f deploy/Dockerfile.proxy -t cytonn-weekly-proxy:<date> deploy
   ```
   The compose override names that exact tag and never pulls it, so the image has to be on the host
   under that name (copy it over with `docker save` and `docker load`, then update the tag in
   `docker-compose.server.yml` if you built a new one).
6. **Start everything once:**
   ```sh
   cd ~/cytonn-weekly
   ./deploy.sh
   docker compose -f docker-compose.yml -f docker-compose.server.yml up -d proxy
   ```
   `deploy.sh` starts only api and web. The proxy is started by the second command and is not touched
   by later deploys.

## Deploying a new build

```sh
cd ~/cytonn-weekly
./deploy.sh
```

It uses `docker-compose.yml` plus `docker-compose.server.yml`, pulls `api` and `web`, recreates only
those two services, prunes dangling images and prints `docker compose ps`. The proxy is not recreated,
so its certificate and login are left alone. `.env` and `.env.proxy` are never read, copied or changed
by a deploy.

After **any** `.env` edit the api must be recreated, because `env_file` is read only when the container
is created. A restart is not enough:

```sh
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --force-recreate api
```

## Environment variables (names only)

**Never put values in this repo, a chat or a log.** Do not run `docker compose config` without
`--quiet` or `--no-env-resolution`: it prints what `.env` holds.

`.env` (the api reads all of it through `env_file`):

| Group | Names |
| --- | --- |
| Database | `CYTONN_DATABASE_URL` (required: the Docker app refuses to start without it) |
| Provider | `CYTONN_LLM_PROVIDER` (`bedrock` in production; unset means `anthropic`) |
| Bedrock | `BEDROCK_MODEL_ID`, `AWS_REGION` (or `AWS_DEFAULT_REGION`), then either `AWS_BEARER_TOKEN_BEDROCK` or `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ `AWS_SESSION_TOKEN` for temporary keys) |
| Anthropic path | `ANTHROPIC_API_KEY`, `CYTONN_LLM_MODEL` (only when the provider is `anthropic`) |
| Source gathering | `EXA_API_KEY`, `CYTONN_SOURCES_ENOUGH`, `CYTONN_SOURCES_MAX_QUERIES`, `CYTONN_SOURCES_MAX_PAGES`, `CYTONN_SOURCES_GATHER_SECONDS`, `CYTONN_SOURCES_MARKET` |
| Bedrock retries | `CYTONN_BEDROCK_RETRIES`, `CYTONN_BEDROCK_RETRY_BASE_SECONDS` |
| Draft concurrency | `CYTONN_DRAFT_CONCURRENCY`, `CYTONN_DRAFT_QUEUE_MAX` |
| Proxy and web | `SITE_DOMAIN` (see below) |

`.env.proxy` (read by the proxy only, as a file, because a bcrypt hash is full of `$` signs and
compose would mangle them as variable references): `SITE_DOMAIN`, the DNS provider token the
Caddyfile names, `BASIC_AUTH_USER` and `BASIC_AUTH_HASH`. It holds nothing else, so the model keys never
enter the proxy container.

How a name reaches a container:

- The api gets everything in `.env` (`env_file` in `docker-compose.yml`). Both compose files also list
  the Bedrock, Exa and draft-concurrency names under `environment:`, with no value: a value is then taken
  from the shell or compose's own `.env` when one is set, and nothing is passed when it is not.
- **Any other container gets only what its compose entry names.** A new setting for web or the proxy
  needs a line in the compose file as well as a value in `.env` or `.env.proxy`.
- **`SITE_DOMAIN` is passed to web** as `VITE_ALLOWED_HOSTS`. `vite preview` refuses a request whose Host
  header it does not know, so without the real name every request is "Blocked request". The override
  reads `${SITE_DOMAIN}` from the shell or from `.env` beside `docker-compose.yml`, and the Caddyfile
  reads it from `.env.proxy`, so set it in both places.

## Check after deploying

1. `docker compose -f docker-compose.yml -f docker-compose.server.yml ps`: api and web healthy, proxy up.
2. **The startup line.** It names which AWS variables reached the api and never a value:
   ```sh
   docker compose -f docker-compose.yml -f docker-compose.server.yml logs --tail 50 api | grep "Drafting with Amazon Bedrock"
   ```
   It reads like `Drafting with Amazon Bedrock, model <id> (from BEDROCK_MODEL_ID). AWS variables set: ...; not set: ...`.
   Check that the model is the one you meant, "(from BEDROCK_MODEL_ID)" appears if you set it, and the
   credential you intended is under "set". If there is no such line, the provider is not bedrock: check
   `CYTONN_LLM_PROVIDER` and recreate the api.
3. **The screen.** Open the overview: the side rail says **Production · bedrock** and there is no DEV MODE
   ribbon (a DEV ribbon means the provider is the local one).
4. **Logs.** `docker compose -f docker-compose.yml -f docker-compose.server.yml logs --tail 50 api`. Each
   Bedrock request writes one line (number, model, token counts, stop reason; counts only):
   `... logs --since 15m api | grep "Bedrock request"`.
5. The full ordered smoke test, with the sentences a failure shows, is in
   [bedrock-droplet-test.md](bedrock-droplet-test.md).

## Rolling back

Find the commit on the Actions tab or with `git log`, then:

```sh
./deploy.sh sha-abc1234
```

That tag stays in use until the next `./deploy.sh` with no argument, which goes back to `latest`.

To go back to the Anthropic provider with no new build, change `.env` alone: set
`CYTONN_LLM_PROVIDER=anthropic` (or delete the line), make sure `ANTHROPIC_API_KEY` and
`CYTONN_LLM_MODEL` are set, then recreate the api (command above). The Bedrock lines can stay. Every
"Draft again" on the overview spends real model budget; `CYTONN_LLM_PROVIDER=local` makes an instance
free to run, with every draft marked for development only.

## Reaching it

Through the proxy's address. The Caddy proxy (`Caddyfile`, image from `Dockerfile.proxy`) listens on 443
only, takes its certificate by DNS challenge (port 80 belongs to another project on the host), asks for
one shared password (HTTP basic auth from `.env.proxy`) and forwards to the web container. A production
host may also put its own separate sign-in in front of this one.

As a fallback that bypasses the proxy, both ports are bound to the host's loopback, so an SSH tunnel
works:

```sh
ssh -L 8010:127.0.0.1:8010 -L 5173:127.0.0.1:5173 <deploy-user>@<production-host>
```

Then open <http://127.0.0.1:5173>.

## Still open

The proxy's password is shared, so it gates access but does not record who approved a section. It
stays until Cytonn SSO is unblocked (`backend/api/sso.py` is still a stub).
