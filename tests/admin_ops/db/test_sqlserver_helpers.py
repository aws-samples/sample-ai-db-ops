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

"""SQL Server helpers: identifier quoting, KILL building, and TLS policy.

The property under test is the same one the other engines assert: nothing a
caller supplies can escape its position in the statement.
"""

from __future__ import annotations

import pytest

from src.admin_ops.db.identifiers import UnsafeIdentifierError, quote_mssql
from src.admin_ops.db.statements import mssql_kill
from src.admin_ops.db.tls import TlsConfigurationError, mssql_connect_kwargs

# Payloads that would break out of a bracket-quoted identifier if they were
# interpolated without validation.
INJECTION_PAYLOADS = [
    "Orders]; DROP TABLE Orders --",
    "Orders]",
    "[Orders]",
    "Orders; SELECT 1",
    "Orders'--",
    "dbo.Orders",
    "Orders WITH (NOLOCK)",
    "Orders\nGO",
    "",
    " ",
]


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
def test_quote_mssql_rejects_anything_that_could_escape_the_brackets(payload):
    with pytest.raises(UnsafeIdentifierError):
        quote_mssql(payload, kind="table")


def test_quote_mssql_brackets_a_valid_identifier():
    assert quote_mssql("Orders", kind="table") == "[Orders]"


def test_quote_mssql_preserves_case():
    """SQL Server is case-sensitive under a case-sensitive collation.

    Unlike quote_oracle, which upper-cases, the SQL Server form must round-trip
    the name exactly or it will not match the catalog on such an instance.
    """
    assert quote_mssql("OrderId", kind="column") == "[OrderId]"


def test_mssql_kill_renders_only_digits():
    assert mssql_kill(51) == "KILL 51"
    assert mssql_kill("51") == "KILL 51"


@pytest.mark.parametrize(
    "bad",
    ["51; DROP TABLE Orders", "0", "-1", "abc", None, True, 2**63, ""],
)
def test_mssql_kill_rejects_non_positive_or_non_integer_session_ids(bad):
    with pytest.raises((UnsafeIdentifierError, ValueError, TypeError)):
        mssql_kill(bad)


def test_mssql_tls_refuses_remote_host_without_acknowledgement(monkeypatch):
    """pymssql cannot verify a certificate, so the risk must be acknowledged."""
    monkeypatch.delenv("DB_TLS_ALLOW_UNVERIFIED", raising=False)
    monkeypatch.delenv("DB_SSL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("DB_REQUIRE_TLS", raising=False)
    with pytest.raises(TlsConfigurationError):
        mssql_connect_kwargs("10.0.1.107")


def test_mssql_tls_allows_remote_host_once_acknowledged(monkeypatch):
    monkeypatch.setenv("DB_TLS_ALLOW_UNVERIFIED", "true")
    monkeypatch.delenv("DB_SSL_CA_BUNDLE", raising=False)
    assert mssql_connect_kwargs("10.0.1.107") == {}


def test_mssql_tls_does_not_claim_a_ca_bundle_was_applied(monkeypatch, caplog):
    """A configured CA bundle cannot be honoured through pymssql.

    Silently ignoring it would leave an operator believing the connection is
    verified, so the helper must warn and still require the acknowledgement.
    """
    monkeypatch.setenv("DB_SSL_CA_BUNDLE", "/tmp/not-used-by-pymssql.pem")
    monkeypatch.setenv("DB_TLS_ALLOW_UNVERIFIED", "true")
    with caplog.at_level("WARNING"):
        assert mssql_connect_kwargs("10.0.1.107") == {}
    assert any("cannot apply a CA bundle" in r.message for r in caplog.records)


def test_mssql_tls_plaintext_opt_out_is_restricted_to_loopback(monkeypatch):
    """Disabling TLS must not silently apply to a remote host."""
    monkeypatch.setenv("DB_REQUIRE_TLS", "false")
    monkeypatch.delenv("DB_SSL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("DB_TLS_ALLOW_UNVERIFIED", raising=False)
    # Loopback: the opt-out applies.
    assert mssql_connect_kwargs("127.0.0.1") == {}
    # Remote: the opt-out is ignored and encryption stays required, so the
    # missing acknowledgement still raises.
    with pytest.raises(TlsConfigurationError):
        mssql_connect_kwargs("10.0.1.107")
