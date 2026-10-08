# Changelog

HydraNest è un fork di [momenbasel/timenest](https://github.com/momenbasel/timenest)
(server Time Machine su Samba + Avahi + Web UI) con le correzioni emerse
installandolo su Proxmox + Portainer.

## v0.1.0 — 2026-10-08

Correzioni di Samba e della gestione utenti (vedi guida di troubleshooting
TimeNest su Proxmox/Portainer).

### Samba
- **smbd non partiva**: `--log-stdout` non esiste più da Samba 4.15 (Debian
  bookworm ha la 4.17). L'entrypoint ora usa `--debug-stdout` o
  `--log-stdout` in base a quello che supporta lo smbd installato.
- **Share non caricate (`NT_STATUS_BAD_NETWORK_NAME`)**: Samba non espande i
  wildcard in `include = /etc/timenest/shares.d/*.conf`. Il nuovo
  `sync-shares.sh` genera `/etc/samba/timenest-shares.conf` con un `include`
  esplicito per ogni `<utente>.conf`; viene eseguito all'avvio e a ogni
  creazione/modifica/cancellazione utente, seguito da un reload di smbd.
- **Utenti persi dopo un redeploy**: gli account POSIX vivevano solo nel
  filesystem effimero del container. All'avvio vengono ricreati per ogni
  utente presente in `shares.d` o nel passdb, con UID/GID presi dal
  proprietario di `/backup/<utente>` così i backup esistenti restano leggibili.
- **Template che sparivano**: i template ora stanno in `/usr/share/timenest`,
  quindi montare un volume su `/etc/timenest` non li nasconde più. Il compose
  monta solo `shares.d`.
- Con `SMB_INTERFACES` vuoto non viene più scritto `interfaces = lo`.
- Healthcheck del container samba basato su `pidof smbd` (lo
  `smbclient -L -N` anonimo veniva rifiutato da `restrict anonymous = 2`).

### Web UI
- **"Configured users: 0"**: nuova variabile `SHARES_PATH` (default
  `/config/shares.d`); il compose monta nello stesso path la directory
  `shares.d` scritta dal container samba.
- Nuovo pulsante **Edit** per utente: modifica quota e reset password
  (nuovo script `set-quota.sh`).

### Deploy
- `docker-compose.portainer.yml` con immagini precompilate e variabili
  `BACKUP_PATH` / `DATA_PATH`; nessun entrypoint patchato da montare.
- `DATA_PATH` (default `./data`) anche nel `docker-compose.yml`.
- Immagini pubblicate come `ghcr.io/sebaf-26/hydranest-{samba,avahi,web}`.
- Il workflow `release` (pkg macOS firmato su runner self-hosted upstream)
  non parte più sui tag; aggiunto test di integrazione Samba in CI.
