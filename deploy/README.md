# Deploying to the shared server

`docker-compose.server.yml` is the override for the one host the app runs on (`159.223.140.184`,
deployed 2026-10-28). It is kept here so the deployment is not folklore; it is copied to the server
by hand, not applied from a checkout.

## Why the images are not built on the server

That box has under 2 GB of RAM and already runs other production workloads, including an
`ai-client-engagement` app, authelia, nginx and a Prometheus/Grafana/Loki stack. Building the api
image (onnxruntime, matplotlib) or the web image (`vue-tsc`, `vite build`) there would very likely
invoke the OOM killer, which picks its victim by score and could take a neighbour down.

So the images are built elsewhere and shipped as tarballs. **Never run `--build` on this server.**

## What the override changes

- **`image:` plus `pull_policy: never`** on both services, with `build:` reset, so compose uses the
  loaded images and never builds or reaches for a registry.
- **The api is published on 8010**, not 8000: `ai-client-engagement-ace-1` holds 8000.
- **`mem_limit` on both services.** These exist so that if this app does not fit, the kernel kills
  one of its containers and not a neighbour. Raise a limit if a container is killed under real use;
  do not remove it.
- **The api runs as uid 1007 (`clive`) with `HOME` and `MPLCONFIGDIR` inside `/app/data`.** The
  image builds a home for uid 10001, but the bind-mounted data folder is owned by `clive` and root
  was not available to change it. Without the redirect, matplotlib's font cache has nowhere to
  write. Revert both once the data folder is `chown`ed to 10001.

Both ports stay bound to `127.0.0.1`. The app has no sign-in (the Cytonn SSO stub is still blocked),
so it must not be published on `0.0.0.0` or put behind anything another machine can reach.

## Deploying a new build

From the repo root, with the images built locally:

```powershell
docker tag cytonn_weekly-api:latest cytonn-weekly-api:<date>
docker tag cytonn_weekly-web:latest cytonn-weekly-web:<date>
docker save cytonn-weekly-api:<date> -o $env:TEMP\api.tar     # -o, not a pipe: PowerShell
docker save cytonn-weekly-web:<date> -o $env:TEMP\web.tar     # mangles binary on a pipe
scp $env:TEMP\api.tar $env:TEMP\web.tar clive@159.223.140.184:~/cytonn-weekly/
```

Then on the server, after updating the two tags in `docker-compose.server.yml`:

```sh
cd ~/cytonn-weekly
docker load -i api.tar && docker load -i web.tar
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --no-build
rm api.tar web.tar
```

The tags are dated rather than `latest` so a redeploy cannot silently run a different build.

## Reaching it

```sh
ssh -L 8010:127.0.0.1:8010 -L 5173:127.0.0.1:5173 clive@159.223.140.184
```

Then open <http://127.0.0.1:5173>.

## Secrets

`.env` lives only on the server, at mode 600, and is never committed. It holds
`CYTONN_DATABASE_URL` (the same Supabase database as a native run), `ANTHROPIC_API_KEY`,
`EXA_API_KEY` and `CYTONN_LLM_PROVIDER`. Do not run `docker compose config` without `--quiet` or
`--no-env-resolution`: it prints what `.env` holds.

The provider is `anthropic`, so **every "Draft again" on the overview spends real API budget**.
Set `CYTONN_LLM_PROVIDER=local` and recreate the api to make the instance free to run.

## Rollback

```sh
cd ~/cytonn-weekly
docker compose -f docker-compose.yml -f docker-compose.server.yml down
docker image rm cytonn-weekly-api:<date> cytonn-weekly-web:<date>
```

Nothing else on the host is touched: no other container, service, nginx config or port binding.

## Still open

The box already runs authelia and nginx. Putting this app behind them would replace the SSH tunnel
with real authentication and is the better long-term answer than a tunnel.
