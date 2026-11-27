# Сообщение админам во ВК от имени сообщества, для deploy.sh и backup.sh (подключается через «.»).
# VK_TOKEN и VK_ADMIN_IDS – из .env проекта, если их там нет – из /opt/oformlyator/.env (как у мониторинга).
# Нет нигде – просто печатаем в лог.
notify() {
    echo "$*"
    local token ids f
    for f in .env /opt/oformlyator/.env; do
        token=$(grep -E '^VK_TOKEN=' "$f" 2>/dev/null | cut -d= -f2- || true)
        ids=$(grep -E '^VK_ADMIN_IDS=' "$f" 2>/dev/null | cut -d= -f2- | tr -d ' ' || true)
        [ -n "$token" ] && [ -n "$ids" ] && break
    done
    [ -n "$token" ] && [ -n "$ids" ] || return 0
    curl -s -m 20 https://api.vk.com/method/messages.send \
        --data-urlencode "peer_ids=$ids" \
        --data-urlencode "message=$*" \
        --data-urlencode "random_id=$RANDOM$RANDOM" \
        --data-urlencode "access_token=$token" \
        --data-urlencode "v=5.199" >/dev/null || true
}
