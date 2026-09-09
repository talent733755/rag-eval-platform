FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

RUN corepack enable

# Install the locked workspace dependencies before copying application source.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN corepack pnpm install --frozen-lockfile

COPY apps/web ./apps/web

WORKDIR /app/apps/web

EXPOSE 3000

CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3000"]
