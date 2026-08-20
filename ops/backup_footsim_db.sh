#!/usr/bin/env bash
#
# PostgreSQL-Backup fuer FootSim.
#
# Bewusst simpel (SC-Freiburg): pg_dump im Custom-Format, lokale
# Rotation, restriktive Rechte. Kein Backup-Framework, kein Agent.
#
# Aufruf als root auf dem VPS:
#     /root/footsim/ops/backup_footsim_db.sh
#
# Als systemd-Timer (empfohlen, taeglich):
#     /etc/systemd/system/footsim-backup.service
#     /etc/systemd/system/footsim-backup.timer
#   siehe ops/DEPLOYMENT.md
#
# WICHTIGE GRENZE
# ---------------
# Dieses Skript schreibt auf DENSELBEN Server. Gegen Ausfall oder
# Verlust des VPS schuetzt das NICHT. Ein Off-Site-Ziel ist bewusst
# nicht erfunden - es muss mit echten Zugangsdaten ergaenzt werden
# (siehe ops/DEPLOYMENT.md, Abschnitt "Off-Site").

set -euo pipefail

DB_NAME="${FOOTSIM_DB_NAME:-footsim_db}"
BACKUP_DIR="${FOOTSIM_BACKUP_DIR:-/var/backups/footsim}"
KEEP_DAYS="${FOOTSIM_BACKUP_KEEP_DAYS:-14}"

timestamp="$(date -u +%Y%m%d-%H%M%S)"
target="${BACKUP_DIR}/${DB_NAME}-${timestamp}.dump"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

# Peer-Authentifizierung als postgres: es werden KEINE Zugangsdaten
# gelesen, uebergeben oder geloggt. pg_dump schreibt nach stdout, die
# Umleitung erfolgt als root - so bleibt die Datei root-only, ohne dass
# der postgres-Benutzer Schreibrechte im Backupverzeichnis braucht.
if ! sudo -u postgres pg_dump -Fc -d "$DB_NAME" > "$target"; then
    echo "BACKUP FEHLGESCHLAGEN: pg_dump beendete sich mit Fehler" >&2
    rm -f "$target"
    exit 1
fi

chmod 600 "$target"

# Integritaetspruefung: ein Dump, der sich nicht lesen laesst, ist kein
# Backup. Lieber hier laut scheitern als beim Restore im Ernstfall.
if ! pg_restore --list "$target" > /dev/null 2>&1; then
    echo "BACKUP FEHLGESCHLAGEN: pg_restore --list konnte $target nicht lesen" >&2
    rm -f "$target"
    exit 1
fi

size_bytes="$(stat -c %s "$target")"
if [ "$size_bytes" -lt 1024 ]; then
    echo "BACKUP FEHLGESCHLAGEN: $target ist verdaechtig klein (${size_bytes} Bytes)" >&2
    rm -f "$target"
    exit 1
fi

echo "$target" > "${BACKUP_DIR}/.latest"
echo "Backup OK: $target (${size_bytes} Bytes)"

# Rotation - nur Dateien mit dem eigenen Namensmuster.
deleted="$(find "$BACKUP_DIR" -maxdepth 1 -type f \
    -name "${DB_NAME}-*.dump" -mtime "+${KEEP_DAYS}" -print -delete | wc -l)"
echo "Rotation: ${deleted} Backup(s) aelter als ${KEEP_DAYS} Tage entfernt"

remaining="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DB_NAME}-*.dump" | wc -l)"
echo "Vorhandene Backups: ${remaining}"
