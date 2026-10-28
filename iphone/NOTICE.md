# HydraNest iPhone: modified AirVault

This directory is [AirVault](https://github.com/wizier/airvault) by wizier,
imported on 2026-10-28 from commit `aa0514f` as a `git subtree`, and
**modified** for HydraNest. It stays under the GNU General Public License
v3.0 or later ([LICENSE](LICENSE)); the rest of the HydraNest repository is
MIT.

## Changes from upstream

Since 2026-10-28:

- **Remote address per iPhone.** Each device page has a "Remote access
  (Tailscale)" card for a Tailscale IP or MagicDNS name. On start, every
  minute and right after a change, the daemon resolves it and sends netmuxd
  an `AddDevice` (UDID + IP) unless the phone is already on the network, so
  backups also run away from home. The addresses are kept in
  `hydranest-remote.json` in the config directory; the database schema is
  upstream's. New files: `internal/ios/netmuxd.go`,
  `internal/engine/remote.go`, `internal/service/remote.go`,
  `internal/handler/remote.go`, `web/src/lib/api/remote.ts`,
  `web/src/lib/components/RemoteAccessCard.svelte` (with tests); small
  hooks in `cmd/airvault/main.go`, `internal/handler/handler.go`,
  `internal/service/service.go`, `internal/ios/iostest/`.
- **HydraNest branding.** Name, logo (`web/public/hydranest-logo.svg`),
  navy and cyan palette in `web/src/app.css`, dark theme by default,
  user-facing text, backup download names (`HydraNest-<name>-<date>.tar`),
  image labels. Internal names (Go module path, `AIRVAULT_*` variables,
  theme and storage keys) are unchanged, so existing settings and data keep
  working.
- **amd64 and arm64 image.** The Dockerfile fetches netmuxd for the target
  architecture (pinned digests) and cross-compiles the daemon.

Files with HydraNest changes carry a `HydraNest:` comment where it helps.

## Taking upstream updates

From the repository root:

```bash
git subtree pull --prefix=iphone https://github.com/wizier/airvault main --squash
```
