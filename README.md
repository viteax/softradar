# СофтРадар – закупки ПО и КП

Адрес: https://softradar.iptvik.ru

Стек: `python-web`. Проект создан [project-kit](https://github.com/viteax/project-kit), живет на сервере
`185.198.152.76` в `/opt/softradar`.

## Запустить у себя

```bash
uv run python -m app   # http://127.0.0.1:8080, тесты: uv run pytest
```

Или как на сервере, в контейнере: `docker compose up --build`.

## Как выкладывается

push в `main` → CI (`.github/workflows/ci.yml`): линтер и тесты, образ, проверка запуска → образ в
`ghcr.io/viteax/softradar`, коммит в ветку `deploy` → сервер раз в 2 минуты забирает ее и поднимает контейнер
(`deploy/deploy.sh`). Сбой деплоя – сообщение во ВК.

```bash
ssh 185.198.152.76 journalctl -u softradar-deploy -n 30        # как прошел деплой
ssh 185.198.152.76 "cd /opt/softradar && docker compose logs --tail 50"   # логи приложения
ssh -t 185.198.152.76 nano /opt/softradar/.env                  # секреты (образец – .env.example)
```
