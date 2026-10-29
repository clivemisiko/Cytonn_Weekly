# Deploying api and web from ghcr.io

## The flow

1. Merge a pull request into `main`.
2. Wait for the **Publish images** run on the Actions tab to go green. It builds two images and
   tags each with `sha-<short commit>` and `latest`:
   - `ghcr.io/clivemisiko/cytonn-weekly-api`
   - `ghcr.io/clivemisiko/cytonn-weekly-web`
3. On the server:

   ```sh
   cd ~/cytonn-weekly
   ./deploy.sh
   ```

   It pulls the compose files with `git pull --ff-only` if the folder is a git clone (on a plain
   copy it skips that, so copy changed compose files or the Caddyfile by hand). Then it pulls the
   two images, recreates `api` and `web`, prunes dangling images and prints `docker compose ps`.
   The proxy is not recreated, so its certificate and login are left alone.

Nothing is built on the server: `build` is reset for both services in `docker-compose.server.yml`.

## Rolling back

Find the commit on the Actions tab or with `git log`, then:

```sh
./deploy.sh sha-abc1234
```

That tag stays in use until the next `./deploy.sh` with no argument, which goes back to `latest`.

## One-time: make the packages public

After the first run, both packages exist but are private. For each of `cytonn-weekly-api` and
`cytonn-weekly-web`: GitHub profile, **Packages**, the package, **Package settings**,
**Change visibility**, Public. The images hold the built app only, no secrets.

If they stay private instead, the owner logs the server in once with a personal access token that
has only `read:packages`:

```sh
docker login ghcr.io -u clivemisiko
```

and pastes the token at the prompt. The token is never written into this repo, a script or a
compose file.

## Secrets

`.env` and `.env.proxy` live only on the server. They are not part of any image (both
`.dockerignore` files exclude them, and CI builds from a clean checkout that never has them), and a
deploy never reads, copies or changes them.
