# The web app (Vue 3 + Vite). Build context: frontend/.
# Node 22 is the version the app is developed on.
#
# The browser only ever talks to this container: nginx serves the built app and proxies /api to the review API
# (nginx.conf), so the API needs no CORS entry.

# 1. Dependencies, exactly as the lockfile pins them.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
# Vite writes its bundled config and its cache under node_modules, as the user it runs as.
RUN chown node:node /app /app/node_modules

# Development server, used only by docker-compose.dev.yml (target: dev). It listens on 8080, the port the web service
# publishes, and proxies /api to VITE_API_TARGET, which the override sets.
FROM deps AS dev
COPY . .
USER node
EXPOSE 8080
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]

# 2. Build dist/ (npm run build type-checks first).
FROM deps AS build
COPY . .
RUN npm run build

# 3. Serve it: nginx as a non-root user on 8080 (the unprivileged image), with nginx.conf's SPA fallback and /api proxy.
FROM nginxinc/nginx-unprivileged:1.28.0-alpine AS web
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=10s \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"]
