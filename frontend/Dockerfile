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
RUN chown -R node:node /app

# Development server, used only by docker-compose.dev.yml (target: dev). It listens on 8080, the port the web service
# publishes, and proxies /api to VITE_API_TARGET, which the override sets.
FROM deps AS dev
COPY --chown=node:node . .
USER node
EXPOSE 8080
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "8080", "--strictPort"]

# 2. Build dist/ and serve it with `vite preview`, which serves the static files and proxies
# /api exactly as the dev server does (server-sent events included).
# ponytail: vite preview, not a web server; move to nginx (with proxy_buffering off for the
# run events stream) when the app is hosted for more than one coordinator on one machine.
FROM deps AS runner
COPY --chown=node:node . .
USER node
RUN npm run build
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"]
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000", "--strictPort"]
