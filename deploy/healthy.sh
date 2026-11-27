#!/usr/bin/env bash
# Ждет, пока контейнер поднимется: с HEALTHCHECK – до healthy, без него – работает 10 секунд без перезапусков.
# Использование: deploy/healthy.sh <контейнер> [секунд, по умолчанию 60]. Нужен CI (smoke) и deploy.sh.
set -uo pipefail
name=$1
limit=${2:-60}
for ((i = 0; i < limit; i += 2)); do
    st=$(docker inspect -f '{{.State.Status}} {{.RestartCount}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null) ||
        { echo "контейнера $name нет"; exit 1; }
    case "$st" in
        "running 0 healthy") echo "$name: healthy"; exit 0 ;;
        "running 0 none") [ "$i" -ge 10 ] && { echo "$name: работает"; exit 0; } ;;
        "running 0 starting") ;;
        *) echo "$name: $st"; docker logs --tail 30 "$name" 2>&1; exit 1 ;;
    esac
    sleep 2
done
echo "$name: не поднялся за $limit с ($st)"
docker logs --tail 30 "$name" 2>&1
exit 1
