"""Model-written findings are checked against the real tool output."""
from app.security.orchestrator import _ground_finding

CALLS = [{
    "operation": "http.headers", "params": {"url": "https://example.com/"},
    "result": {"ok": True, "stdout": "HTTP/2 200\nserver: nginx\nx-frame-options: DENY\nx-content-type-options: nosniff\n"},
}]


def test_missing_header_is_verified_and_asset_fixed():
    f = _ground_finding({"title": "Missing Security Headers", "severity": "medium",
                         "confidence": "suspected", "status": "suspected", "asset": "http.headers",
                         "evidence": ["No HSTS header detected"]}, CALLS)
    assert f["asset"] == "example.com" and f["tool"] == "http.headers"
    assert f["status"] == "verified" and f["confidence"] == "confirmed"
    assert any("strict-transport-security" in e for e in f["evidence"])


def test_false_claim_is_marked_contradicted():
    f = _ground_finding({"title": "Missing X-Frame-Options", "severity": "medium",
                         "asset": "example.com", "evidence": ["X-Frame-Options not set"]}, CALLS)
    assert f["status"] == "suspected" and "IS present" in f["limitations"]
    assert "false positive" in f["validation"]


def test_unrelated_findings_are_untouched():
    f = _ground_finding({"title": "Old TLS version", "asset": "example.com", "status": "suspected"}, CALLS)
    assert f["status"] == "suspected" and f["asset"] == "example.com"
