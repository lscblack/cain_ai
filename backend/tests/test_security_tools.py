"""Security tooling: validators, adapters, safe executor, redaction, registry."""
from __future__ import annotations

import shutil

import pytest

from app.security import adapters, registry
from app.security import validate as V
from app.security.executor import run_argv
from app.security.redact import redact


# ───────────────────────── validators ───────────────────────────────── #
def test_domain_ok_and_bad():
    assert V.domain("Example.COM") == "example.com"
    for bad in ["", "no_underscores_tld", "-leading.com", "a b.com", "x.com; rm -rf /"]:
        with pytest.raises(V.ArgError):
            V.domain(bad)


def test_flag_injection_rejected():
    with pytest.raises(V.ArgError):
        V.host_or_ip("-oN/tmp/x")
    with pytest.raises(V.ArgError):
        V.hostname("a\nb")


def test_port_spec_ok_and_bad():
    assert V.port_spec("22,80,443,8000-8100") == "22,80,443,8000-8100"
    with pytest.raises(V.ArgError):
        V.port_spec("22,99999")
    with pytest.raises(V.ArgError):
        V.port_spec("22;80")


def test_package_name():
    assert V.package_name("whatweb") == "whatweb"
    for bad in ["WhatWeb", "evil; rm", "../etc", ""]:
        with pytest.raises(V.ArgError):
            V.package_name(bad)


def test_url_rejects_private():
    with pytest.raises(V.ArgError):
        V.url("http://127.0.0.1/")
    with pytest.raises(V.ArgError):
        V.url("ftp://example.com")


# ───────────────────────── adapters ─────────────────────────────────── #
def test_dig_argv():
    argv = adapters.dig_records("/usr/bin/dig", {"domain": "example.com", "type": "mx"})
    assert argv[0] == "/usr/bin/dig"
    assert argv[-2:] == ["example.com", "MX"]


def test_nmap_argv_connect_scan_no_root():
    argv = adapters.nmap_service_scan("/usr/bin/nmap", {"target": "scanme.nmap.org", "ports": "22,80"})
    assert "-sT" in argv and "-Pn" in argv  # connect scan, no root
    assert "-sS" not in argv                # never a raw SYN scan (needs root)
    assert argv[-1] == "scanme.nmap.org"
    assert "22,80" in argv


def test_curl_headers_argv_rejects_private():
    with pytest.raises(V.ArgError):
        adapters.curl_headers("/usr/bin/curl", {"url": "http://169.254.169.254/"})


# ───────────────────────── executor ─────────────────────────────────── #
async def test_run_argv_success():
    true_bin = shutil.which("true") or "/bin/true"
    res = await run_argv([true_bin])
    assert res.status == "ok" and res.exit_code == 0


async def test_run_argv_timeout_kills():
    sleep_bin = shutil.which("sleep") or "/bin/sleep"
    res = await run_argv([sleep_bin, "10"], timeout=1)
    assert res.status == "timeout"


async def test_run_argv_sanitized_env_hides_secrets():
    # `env` should not see DB_PASSWORD etc. — we pass only PATH/LANG/LC_ALL.
    env_bin = shutil.which("env")
    if not env_bin:
        pytest.skip("env not available")
    res = await run_argv([env_bin])
    assert "DB_PASSWORD" not in res.stdout
    assert "APP_SECRET_KEY" not in res.stdout


def test_redaction():
    assert "«redacted»" in redact("Authorization: Bearer abc.def.ghi")
    assert "«redacted»" in redact("api_key = sk-ABCDEFGHIJKLMNOPQRSTUVWX")
    assert redact("nothing secret here") == "nothing secret here"


# ───────────────────────── registry / discovery ─────────────────────── #
async def test_registry_discovers_real_host():
    names = {t.name for t, _ in registry.all_operations()}
    assert {"dig", "whois", "curl", "openssl", "nmap"} <= names
    dig = registry.get_tool("dig")
    disc = await registry.discover(dig)
    # dig is installed on this host; version string should be captured.
    assert disc.installed is True and disc.path
    assert disc.version  # e.g. "DiG 9.x"


async def test_builtin_osv_tool_is_available_without_binary():
    osv = registry.get_tool("osv")
    disc = await registry.discover(osv)
    assert disc.installed is True and disc.path == "(builtin)"
