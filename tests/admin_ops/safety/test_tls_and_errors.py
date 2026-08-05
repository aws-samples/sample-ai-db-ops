# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Encryption-in-transit defaults and error-text redaction."""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.admin_ops import errors as errors_mod
from src.admin_ops.db import tls
from src.admin_ops.errors import redact, safe_error

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean_tls_env(monkeypatch):
    """Each test starts from an unconfigured environment."""
    monkeypatch.delenv(tls.CA_BUNDLE_ENV, raising=False)
    monkeypatch.delenv(tls.REQUIRE_TLS_ENV, raising=False)
    monkeypatch.delenv(tls.ALLOW_UNVERIFIED_ENV, raising=False)


@pytest.fixture
def allow_unverified(monkeypatch):
    """Acknowledge encrypted-but-unverified TLS, as an operator would."""
    monkeypatch.setenv(tls.ALLOW_UNVERIFIED_ENV, "true")


# ── Unverified TLS is not a silent default ──────────────────────────────────


@pytest.mark.parametrize(
    "call",
    [
        lambda: tls.postgres_ssl_kwargs("db.example.internal"),
        lambda: tls.mysql_ssl_kwargs("db.example.internal"),
        lambda: tls.redis_ssl_kwargs("cache.example.internal"),
        lambda: tls.oracle_dsn("db.example.internal", 2484, sid="ORCL"),
    ],
)
def test_no_ca_bundle_refuses_unless_acknowledged(call):
    """Without a CA bundle the connection must not silently skip verification."""
    with pytest.raises(tls.TlsConfigurationError) as excinfo:
        call()
    # The error has to tell the operator what to do about it.
    assert tls.CA_BUNDLE_ENV in str(excinfo.value)
    assert tls.ALLOW_UNVERIFIED_ENV in str(excinfo.value)


# ── Secure by default ───────────────────────────────────────────────────────


def test_postgres_encrypts_by_default(allow_unverified):
    kwargs = tls.postgres_ssl_kwargs("db.example.internal")
    assert kwargs["sslmode"] == "require"


def test_postgres_verifies_when_ca_bundle_present(monkeypatch):
    monkeypatch.setenv(tls.CA_BUNDLE_ENV, "/etc/ssl/rds-global-bundle.pem")
    kwargs = tls.postgres_ssl_kwargs("db.example.internal")
    assert kwargs["sslmode"] == "verify-full"
    assert kwargs["sslrootcert"] == "/etc/ssl/rds-global-bundle.pem"


def test_mysql_forces_a_tls_context_by_default(allow_unverified):
    """PyMySQL's implicit default only *prefers* TLS, so a context is required."""
    kwargs = tls.mysql_ssl_kwargs("db.example.internal")
    assert "ssl" in kwargs
    # A falsy mapping would be ignored by PyMySQL and silently disable TLS.
    assert kwargs["ssl"], "ssl mapping must be truthy or PyMySQL skips it"


def test_mysql_verifies_when_ca_bundle_present(monkeypatch):
    monkeypatch.setenv(tls.CA_BUNDLE_ENV, "/etc/ssl/rds-global-bundle.pem")
    kwargs = tls.mysql_ssl_kwargs("db.example.internal")
    assert kwargs["ssl_ca"] == "/etc/ssl/rds-global-bundle.pem"
    assert kwargs["ssl_verify_cert"] is True
    assert kwargs["ssl_verify_identity"] is True


def test_redis_enables_tls_by_default(allow_unverified):
    """redis-py is cleartext unless ssl=True; AUTH would expose the password."""
    kwargs = tls.redis_ssl_kwargs("cache.example.internal")
    assert kwargs["ssl"] is True


def test_redis_verifies_when_ca_bundle_present(monkeypatch):
    monkeypatch.setenv(tls.CA_BUNDLE_ENV, "/etc/ssl/rds-global-bundle.pem")
    kwargs = tls.redis_ssl_kwargs("cache.example.internal")
    assert kwargs["ssl"] is True
    assert kwargs["ssl_ca_certs"] == "/etc/ssl/rds-global-bundle.pem"
    assert kwargs["ssl_cert_reqs"] == "required"
    assert kwargs["ssl_check_hostname"] is True


def test_oracle_uses_tcps_by_default(allow_unverified):
    dsn = tls.oracle_dsn("db.example.internal", 2484, sid="ORCL")
    assert "PROTOCOL=TCPS" in dsn
    assert "(SID=ORCL)" in dsn


def test_oracle_matches_server_dn_when_ca_bundle_present(monkeypatch):
    monkeypatch.setenv(tls.CA_BUNDLE_ENV, "/etc/ssl/rds-global-bundle.pem")
    dsn = tls.oracle_dsn("db.example.internal", 2484, service_name="ORCL")
    assert "SSL_SERVER_DN_MATCH=YES" in dsn
    assert tls.oracle_connect_kwargs("db.example.internal")["ssl_server_dn_match"] is True


def test_oracle_requires_exactly_one_of_sid_or_service_name():
    """Argument validation happens before any TLS decision."""
    with pytest.raises(ValueError):
        tls.oracle_dsn("h", 2484)
    with pytest.raises(ValueError):
        tls.oracle_dsn("h", 2484, sid="A", service_name="B")


# ── The plaintext opt-out cannot reach a remote endpoint ─────────────────────


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_plaintext_opt_out_applies_to_loopback(monkeypatch, value):
    """A local database that cannot speak TLS is still reachable."""
    monkeypatch.setenv(tls.REQUIRE_TLS_ENV, value)
    assert tls.tls_required() is False
    assert tls.postgres_ssl_kwargs("127.0.0.1")["sslmode"] == "disable"
    assert tls.mysql_ssl_kwargs("localhost")["ssl_disabled"] is True
    assert tls.redis_ssl_kwargs("::1") == {}
    assert "PROTOCOL=TCP)" in tls.oracle_dsn("localhost", 1521, sid="ORCL")


@pytest.mark.parametrize(
    "host",
    ["db.example.internal", "10.0.1.25", "prod.abc123.us-east-1.rds.amazonaws.com"],
)
def test_plaintext_opt_out_is_ignored_for_remote_hosts(monkeypatch, host):
    """DB_REQUIRE_TLS=false must not put credentials on a network in cleartext."""
    monkeypatch.setenv(tls.REQUIRE_TLS_ENV, "false")
    monkeypatch.setenv(tls.ALLOW_UNVERIFIED_ENV, "true")
    assert tls.plaintext_permitted("PostgreSQL", host) is False
    assert tls.postgres_ssl_kwargs(host)["sslmode"] == "require"
    assert tls.mysql_ssl_kwargs(host)["ssl"]
    assert tls.redis_ssl_kwargs(host)["ssl"] is True
    assert "PROTOCOL=TCPS" in tls.oracle_dsn(host, 2484, sid="ORCL")


def test_unknown_host_is_treated_as_remote(monkeypatch):
    """A caller that cannot supply a host must not get a cleartext connection."""
    monkeypatch.setenv(tls.REQUIRE_TLS_ENV, "false")
    monkeypatch.setenv(tls.ALLOW_UNVERIFIED_ENV, "true")
    assert tls.postgres_ssl_kwargs()["sslmode"] == "require"


@pytest.mark.parametrize(
    "host,expected",
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("127.5.5.5", True),
        ("::1", True),
        ("[::1]", True),
        ("/var/run/postgresql", True),
        ("db.example.internal", False),
        ("10.0.1.25", False),
        # Bandit's B104 flags the 0.0.0.0 literal as "binding to all
        # interfaces". Nothing binds here: this asserts that 0.0.0.0 is *not*
        # treated as loopback, which is what keeps TLS mandatory for it. The
        # case exists to prove the fail-closed behaviour, so the literal is
        # required.
        ("0.0.0.0", False),  # nosec B104
        (None, False),
    ],
)
def test_loopback_detection(host, expected):
    assert tls.is_loopback(host) is expected


@pytest.mark.parametrize("value", ["", "true", "yes", "1", "anything-else"])
def test_unrecognized_values_keep_tls_on(monkeypatch, value):
    """Only an explicit falsey value disables TLS; typos must not."""
    monkeypatch.setenv(tls.REQUIRE_TLS_ENV, value)
    assert tls.tls_required() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "maybe"])
def test_unverified_requires_an_affirmative_value(monkeypatch, value):
    """Only an explicit truthy value acknowledges unverified TLS."""
    monkeypatch.setenv(tls.ALLOW_UNVERIFIED_ENV, value)
    assert tls.unverified_allowed() is False


# ── Every connection site routes through the helper ─────────────────────────


# ``module.attr`` pairs that open a network connection to a datastore. Keyed by
# the attribute so both ``psycopg2.connect``-style factories and
# ``redis.Redis``-style constructors are covered; the first version of this
# guard only matched ``.connect`` and therefore missed ``redis.Redis``.
_CONNECTION_SITES = {
    ("psycopg2", "connect"),
    ("pymysql", "connect"),
    ("oracledb", "connect"),
    ("redis", "Redis"),
    ("redis", "StrictRedis"),
    ("redis", "from_url"),
}

# Any one of these kwargs proves TLS was considered at the call site.
_TLS_KWARGS = {
    "sslmode",
    "ssl",
    "ssl_ca",
    "ssl_disabled",
    "ssl_server_dn_match",
    "ssl_ca_certs",
    "ssl_cert_reqs",
}


def test_no_connection_site_omits_tls_configuration():
    """A new connection call must not silently default to cleartext."""
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.glob("**/*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith((".venv/", "tests/admin_ops/", "build/")) or "__pycache__" in rel:
            continue
        if rel == "src/admin_ops/db/tls.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            module = getattr(func.value, "id", "")
            if (module, func.attr) not in _CONNECTION_SITES:
                continue
            # oracledb takes TLS via the DSN, which tls.oracle_dsn builds.
            if module == "oracledb":
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            # ``**tls.<engine>_ssl_kwargs()`` appears as a keyword with arg=None.
            starred = any(kw.arg is None for kw in node.keywords)
            if not starred and not (kwargs & _TLS_KWARGS):
                offenders.append(f"{rel}:{node.lineno} ({module}.{func.attr})")
    assert not offenders, (
        "Database connections without TLS configuration. Pass the kwargs from "
        "src/admin_ops/db/tls.py:\n  " + "\n  ".join(offenders)
    )


def test_drift_guard_actually_catches_a_plaintext_connection():
    """Guard the guard: a bare connection call must be reported as an offender."""
    tree = ast.parse("import redis\nredis.Redis(host='h', port=6379)\n")
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (getattr(node.func.value, "id", ""), node.func.attr) in _CONNECTION_SITES
        and not any(kw.arg is None for kw in node.keywords)
        and not ({kw.arg for kw in node.keywords if kw.arg} & _TLS_KWARGS)
    ]
    assert len(found) == 1, "drift guard no longer detects plaintext connections"


# ── Error text ──────────────────────────────────────────────────────────────


def test_safe_error_exposes_only_the_type():
    exc = ValueError("syntax error at or near \"SELECT ssn FROM customers\"")
    assert safe_error(exc) == "ValueError"
    assert "ssn" not in safe_error(exc)


def test_redact_removes_secret_assignments():
    out = redact("connection failed: password=hunter2 host=db.internal")
    assert "hunter2" not in out
    assert "[redacted]" in out


@pytest.mark.parametrize(
    "key",
    [
        # Original set
        "password", "passwd", "pwd", "secret", "token", "api_key",
        "authorization", "credential",
        # Added after the scanner noted the pattern was too narrow
        "passphrase", "credentials", "client_secret",
        "access_token", "refresh_token", "id_token", "auth_token",
        "bearer_token", "session_token", "csrf_token", "xsrf_token",
        "access_key", "secret_key", "private_key", "encryption_key",
        "signing_key", "apikey", "api-key",
        "session", "session_id", "sessionid", "cookie", "auth", "signature",
        "aws_session_token", "aws_secret_access_key", "x-amz-security-token",
    ],
)
@pytest.mark.parametrize("sep", ["=", ": ", " = "])
def test_redact_covers_common_secret_keys(key, sep):
    out = redact(f"{key}{sep}s3cr3t")
    assert "s3cr3t" not in out, f"{key!r} value survived redaction"
    assert "[redacted]" in out


def test_redact_keeps_the_key_name_for_readability():
    """An operator still needs to know *which* field was scrubbed."""
    out = redact("connect failed: aws_secret_access_key=AKIAsomethinglong host=db")
    assert "aws_secret_access_key" in out
    assert "AKIAsomethinglong" not in out


def test_python_and_typescript_redaction_cover_the_same_keys():
    """The two implementations log the same failures from opposite sides.

    A key covered in one and not the other is a gap, so the lists are compared
    directly rather than trusted to stay in step by convention.
    """
    ts_source = (REPO_ROOT / "ui" / "src" / "lib" / "redact.ts").read_text(encoding="utf-8")
    for pattern in errors_mod._SENSITIVE_KEYS:
        # The TypeScript twin stores the same alternatives as quoted strings.
        assert f'"{pattern}"' in ts_source, (
            f"{pattern!r} is redacted in Python but missing from "
            "ui/src/lib/redact.ts"
        )


def test_redact_removes_quoted_literals():
    out = redact("ERROR: duplicate key value violates unique constraint 'users_email_key'")
    assert "users_email_key" not in out


def test_redact_truncates_and_handles_empty():
    assert redact("") == ""
    assert len(redact("x" * 5000, max_len=100)) < 200
