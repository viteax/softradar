#!/usr/bin/env bash
# Автодеплой: забирает ветку deploy (CI кладет туда только коммиты, прошедшие тесты и сборку образа)
# и поднимает контейнер на образе этого коммита из ghcr.io. Сервер ничего не собирает.
# Запускает таймер softradar-deploy.timer раз в 2 минуты. Лог: journalctl -u softradar-deploy
set -euo pipefail

NAME=softradar
IMAGE=ghcr.io/viteax/$NAME

# Весь скрипт – в функции: bash читает ее целиком до запуска, поэтому git merge,
# который обновит этот же файл, не собьет выполнение на середине.
main() {
    cd "$(dirname "$0")/.."
    . deploy/notify.sh

    exec 9>"/tmp/$NAME-deploy.lock"
    if ! flock -n 9; then
        echo "предыдущий деплой еще идет"
        exit 0
    fi

    if ! git fetch --quiet origin deploy 2>/dev/null; then
        echo "ветки deploy пока нет – CI на main еще ни разу не прошел"
        exit 0
    fi
    local running want msg
    running=$(sed -n 's/^IMAGE_TAG=sha-//p' .env 2>/dev/null || true)
    want=$(git rev-parse origin/deploy)
    # сверяем с запущенным образом, а не с HEAD: упавший деплой повторится на следующем круге
    [ "$running" = "$want" ] && exit 0

    git merge --ff-only --quiet origin/deploy
    msg=$(git log -1 --format='%h %s')
    echo "деплою $msg"
    export IMAGE_TAG="sha-$want"
    touch .env
    # --no-build: нет образа – ошибка, а не тихая сборка на общем сервере
    if ! timeout 10m docker pull -q "$IMAGE:$IMAGE_TAG" >/dev/null || ! timeout 5m docker compose up -d --no-build; then
        notify "❌ $NAME: деплой $msg не удался (образ или compose). journalctl -u $NAME-deploy"
        exit 1
    fi
    # ручной docker compose up -d на сервере возьмет тот же образ
    sed -i '/^IMAGE_TAG=/d' .env && echo "IMAGE_TAG=$IMAGE_TAG" >> .env

    # проверка сайта в мониторинге (VictoriaMetrics читает /opt/monitoring/targets сама, без перезапуска)
    if [ -f deploy/monitoring.json ] && [ -d /opt/monitoring/targets ]; then
        cmp -s deploy/monitoring.json "/opt/monitoring/targets/$NAME.json" ||
            install -m 644 deploy/monitoring.json "/opt/monitoring/targets/$NAME.json"
    fi

    # старые образы не копим (для отката скачается снова)
    docker images "$IMAGE" --format '{{.Repository}}:{{.Tag}}' | grep -vxF "$IMAGE:$IMAGE_TAG" |
        xargs -r docker rmi >/dev/null 2>&1 || true

    # up -d успешен, даже если приложение падает при старте и перезапускается по кругу
    if ! bash deploy/healthy.sh "$NAME" 90; then
        notify "❌ $NAME: после деплоя $msg контейнер не поднялся. docker compose -f /opt/$NAME/docker-compose.yml logs --tail 50"
        exit 1
    fi
    echo "готово"
}

main "$@"; exit
