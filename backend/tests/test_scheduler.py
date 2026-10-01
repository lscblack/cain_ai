from datetime import datetime, timedelta, timezone

from app.crawlers.scheduler import _due
from app.database.models.source import Source

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _src(**kw):
    base = dict(name="n", base_url="https://x/", domain="x", allowed_paths=[], excluded_paths=[])
    base.update(kw)
    return Source(**base)


def test_manual_never_due():
    assert _due(_src(schedule="manual"), NOW) is False


def test_never_crawled_is_due():
    assert _due(_src(schedule="daily", last_crawled_at=None), NOW) is True


def test_not_yet_due():
    recent = (NOW - timedelta(hours=1)).isoformat()
    assert _due(_src(schedule="daily", last_crawled_at=recent), NOW) is False


def test_elapsed_is_due():
    old = (NOW - timedelta(days=2)).isoformat()
    assert _due(_src(schedule="daily", last_crawled_at=old), NOW) is True


def test_crawling_not_due():
    assert _due(_src(schedule="hourly", status="crawling", last_crawled_at=None), NOW) is False
