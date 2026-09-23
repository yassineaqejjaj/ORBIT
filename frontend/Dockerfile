# syntax=docker/dockerfile:1.7
# ORBIT web (Next.js 15, standalone output)
#
# The same-origin proxy (/api/* and /mcp/* -> FastAPI) is declared with Next.js rewrites,
# which are evaluated at BUILD time. The backend URL is therefore a build argument:
#   docker build --build-arg ORBIT_API_URL=http://api:8000 -t orbit-web ./frontend
# It defaults to http://api:8000 (docker compose service name). To point the UI at another
# backend, rebuild the image with a different ORBIT_API_URL.

ARG NODE_IMAGE=node:22-alpine

# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
RUN apk add --no-cache libc6-compat
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS builder
WORKDIR /app
ARG ORBIT_API_URL=http://api:8000
ENV ORBIT_API_URL=${ORBIT_API_URL} \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS runner
WORKDIR /app
ARG ORBIT_API_URL=http://api:8000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    ORBIT_API_URL=${ORBIT_API_URL}

RUN addgroup -S -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD wget -qO- "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
