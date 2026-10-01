from app.intelligence.username.check import check_username, is_valid_username


def test_username_validation():
    assert is_valid_username("john_doe")
    assert is_valid_username("osint-99")
    assert not is_valid_username("a")  # too short
    assert not is_valid_username("has space")
    assert not is_valid_username("@weird!")


async def test_check_classifies_statuses():
    # map specific URLs to statuses
    status_map = {}

    async def fetch(url):
        if "github.com" in url:
            return 200
        if "gitlab.com" in url:
            return 404
        if "reddit.com" in url:
            return 403
        return None  # unreachable

    hits = await check_username("someuser", fetch)
    by_platform = {h.platform: h for h in hits}
    assert by_platform["github"].status == "found"
    assert by_platform["gitlab"].status == "not_found"
    assert by_platform["reddit"].status == "unknown"
    # a platform returning None -> error
    assert any(h.status == "error" for h in hits)
    _ = status_map


async def test_check_subset_of_platforms():
    async def fetch(url):
        return 200

    hits = await check_username("x", fetch, platform_keys=["github", "medium"])
    assert len(hits) == 2
    assert {h.platform for h in hits} == {"github", "medium"}


async def test_check_handles_fetcher_exception():
    async def fetch(url):
        raise RuntimeError("boom")

    hits = await check_username("x", fetch, platform_keys=["github"])
    assert hits[0].status == "error"
