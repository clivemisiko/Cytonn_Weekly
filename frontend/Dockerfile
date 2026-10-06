# The web app (Next.js). Build context: frontend/.
# Node 22 is the version the app is developed on.

# 1. Dependencies, exactly as the lockfile pins them.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Development server, used only by docker-compose.dev.yml (target: dev).
FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN mkdir -p .next && chown -R node:node /app/.next && chown node:node /app
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"]
CMD ["npx", "next", "dev", "--hostname", "0.0.0.0", "--port", "3000"]

# 2. Build. NEXT_PUBLIC_API_URL is fixed into the browser code here, so it must be the
# address the BROWSER can reach the API at, not the compose service name.
FROM deps AS build
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build

# 3. Runtime: the standalone server only (output: "standalone" in next.config.ts).
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD ["node", "-e", "require('http').get('http://127.0.0.1:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"]
CMD ["node", "server.js"]
