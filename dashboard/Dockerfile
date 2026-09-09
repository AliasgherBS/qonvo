# syntax=docker/dockerfile:1

# ---- deps ---------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- build ---------------------------------------------------------------
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundle by `next build`, so
# they have to be present HERE. Setting them on the container at runtime does
# nothing — the value is already compiled in. This is the single most expensive
# gotcha in this project (see CLAUDE.md, "Deploy gotchas"), and the compose
# `dashboard` service used to get it wrong.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false
# Not a NEXT_PUBLIC_* value, but baked all the same: next.config.ts uses it as a
# rewrite destination, and Next serialises rewrites into routes-manifest.json.
# The default is the compose service name, because that is what this image runs
# next to. The host-process build (run-dashboard.sh) picks up .env.local
# instead, where localhost is the correct answer.
ARG INTERNAL_API_URL=http://api:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=$NEXT_PUBLIC_GOOGLE_AUTH_ENABLED \
    INTERNAL_API_URL=$INTERNAL_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

# Fail loudly rather than baking a default. Unset, `lib/api.ts` falls back to
# http://localhost:8000 and `lib/site.ts` to http://localhost:3002 — an image
# that builds cleanly, starts cleanly, and sends every browser call to the
# user's own machine. Same reasoning as the required `pacing` argument on the
# send gateway: a silent default is worse than a failed build.
RUN set -e; \
    for v in NEXT_PUBLIC_API_URL NEXT_PUBLIC_SITE_URL; do \
      eval "val=\$$v"; \
      [ -n "$val" ] || { echo "ERROR: build-arg $v is required"; exit 1; }; \
    done

RUN npm run build

# ---- runtime ---------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
  && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
