"""Точка входа: python -m app. Порт – из PORT (по умолчанию 8080)."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        "app.web:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        # снаружи – edge-caddy в частной сети: адрес клиента берем из X-Forwarded-For
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,  # журнал посещений ведет edge-caddy
        log_config=None,  # не перетирать basicConfig: логи конвейера и агента видны в docker logs
    )


if __name__ == "__main__":
    main()
