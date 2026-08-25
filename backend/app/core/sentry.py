import logging

from app.core.config import settings

log = logging.getLogger(__name__)


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            release=settings.app_version,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        log.info("sentry initialised")
    except Exception as exc:
        log.warning("sentry init failed: %s", exc)
