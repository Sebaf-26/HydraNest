# HydraNest: built for linux/amd64 and linux/arm64. netmuxd ships prebuilt
# Linux binaries for x86_64 and aarch64 only (no armv7), one pinned digest each.
ARG NETMUXD_TAG=v0.4.3
ARG NETMUXD_SHA256_AMD64=85b6598284fc639f2a282584461d05e2090b79bdf3ec949d2a5e5d3dc655dde4
ARG NETMUXD_SHA256_ARM64=a89d587b094184b41431bc343da6dfa890391ccc7d4b3d6bce02b524f3191ae6

# The UI and the pure-Go daemon build on the runner's own arch; only the
# runtime stage runs under emulation.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./

# ARG after npm ci: a version bump must not invalidate the install layer.
ARG VERSION=dev
RUN VITE_APP_VERSION=$VERSION npm run build

FROM --platform=$BUILDPLATFORM golang:1.27-trixie AS build
# .git is dockerignored; the release version comes in as an ARG.
ARG VERSION=dev
ARG TARGETOS TARGETARCH
ENV GOOS=$TARGETOS GOARCH=$TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
COPY --from=web /web/dist ./web/dist

RUN make build COMPONENTS= VERSION=${VERSION} GOTAGS=timetzdata DAEMON_BINARY=/out/airvault

FROM debian:trixie-slim AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="HydraNest iPhone" \
      org.opencontainers.image.description="HydraNest iPhone backups (USB, Wi-Fi and Tailscale), a modified AirVault" \
      org.opencontainers.image.source="https://github.com/Sebaf-26/HydraNest" \
      org.opencontainers.image.licenses="GPL-3.0" \
      org.opencontainers.image.version="$VERSION"

# usbmuxd: USB transport; netmuxd: Wi-Fi on top; util-linux: setpriv for PUID/PGID
RUN apt-get update && apt-get install -y --no-install-recommends usbmuxd ca-certificates curl util-linux \
    && rm -rf /var/lib/apt/lists/*

ARG NETMUXD_TAG
ARG NETMUXD_SHA256_AMD64
ARG NETMUXD_SHA256_ARM64
ARG TARGETARCH
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) arch=x86_64;  sha="$NETMUXD_SHA256_AMD64" ;; \
      arm64) arch=aarch64; sha="$NETMUXD_SHA256_ARM64" ;; \
      *) echo "no netmuxd release for $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/netmuxd.tar.gz \
      "https://github.com/jkcoxson/netmuxd/releases/download/$NETMUXD_TAG/netmuxd-$arch-unknown-linux-gnu.tar.gz"; \
    echo "$sha  /tmp/netmuxd.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/netmuxd.tar.gz -C /usr/local/bin netmuxd; \
    rm /tmp/netmuxd.tar.gz
COPY --from=build /out/airvault /usr/local/bin/airvault
COPY --chmod=0755 scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY LICENSE /licenses/

EXPOSE 8080
ENV AIRVAULT_BIND_HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["airvault", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
