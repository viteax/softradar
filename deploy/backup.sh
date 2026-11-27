#!/usr/bin/env bash
# Копия баз SQLite из тома softradar_data раз в сутки (таймер softradar-backup.timer), хранятся 14 последних.
# sqlite3.backup() копирует базу целиком, даже пока приложение в нее пишет (WAL), quick_check ловит битую копию.
# Лог: journalctl -u softradar-backup. Восстановить: docker compose stop, положить копию на место базы в томе.
# Вне сервера: если есть /etc/softradar/rclone.conf с remote «offsite» – копии уходят туда (как у competency).
set -Eeuo pipefail
cd "$(dirname "$0")/.."
. deploy/notify.sh

NAME=softradar
DIR=/var/backups/$NAME
KEEP=14
REMOTE_KEEP=90d
trap 'notify "❌ $NAME: копия базы не сделана. journalctl -u $NAME-backup"' ERR

vol=$(docker volume inspect -f '{{.Mountpoint}}' "${NAME}_data")
umask 077
mkdir -p "$DIR"
found=0
while IFS= read -r -d '' db; do
    found=1
    base=$(basename "$db")
    out="$DIR/${base%.*}-$(date +%F).${base##*.}"
    python3 - "$db" "$out" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
assert dst.execute("PRAGMA quick_check").fetchone()[0] == "ok", "копия битая"
EOF
    ls -1t "$DIR/${base%.*}"-*."${base##*.}" | tail -n +$((KEEP + 1)) | xargs -r rm --
    echo "копия $out, $(du -h "$out" | cut -f1)"
done < <(find "$vol" -maxdepth 3 -type f \( -name '*.sqlite3' -o -name '*.sqlite' -o -name '*.db' \) -print0)
[ "$found" = 1 ] || echo "баз в томе пока нет – копировать нечего"

[ -f "/etc/$NAME/rclone.conf" ] || exit 0
rclone() {
    docker run --rm -v "$DIR:/backups:ro" -v "/etc/$NAME:/config/rclone:ro" rclone/rclone:1.71.0 "$@"
}
rclone copy /backups offsite:
rclone delete offsite: --min-age "$REMOTE_KEEP"
echo "в облаке: $(rclone lsf offsite: | wc -l) копий"
