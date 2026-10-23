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

"""Encryption-in-transit settings for database connections.

Every database connection in this project routes its TLS configuration through
this module, so the posture is defined once and is auditable in one place.

Posture
-------

Two independent properties, each fail-closed:

**Encryption** is mandatory for any remote endpoint. ``DB_REQUIRE_TLS=false``
exists only so the sample can talk to a local database that does not speak TLS
at all, and it is honoured *only* when the host is loopback. Pointed at a real
endpoint it is ignored and the connection is still encrypted, because an
environment variable should not be able to put credentials on the wire in
cleartext.

**Verification** requires a CA bundle. Set ``DB_SSL_CA_BUNDLE`` and the server
certificate and hostname are both checked. With no bundle the connection can
only be encrypted-but-unverified, which is vulnerable to an active
man-in-the-middle, so that mode is not a silent default: it must be
acknowledged with ``DB_TLS_ALLOW_UNVERIFIED=true``. Otherwise these helpers
raise :class:`TlsConfigurationError` and tell the operator which variable to
set.

Why verification is not simply the default: Amazon RDS and Aurora present
certificates issued by the Amazon RDS certificate authorities, which are not in
the operating system trust store. Defaulting to full verification without a
bundle would therefore fail to connect against the exact endpoints this sample
targets. Requiring an explicit acknowledgement instead keeps the secure path as
the default expectation while making the weaker path a deliberate, greppable
choice rather than an invisible one.

Environment variables
---------------------

``DB_SSL_CA_BUNDLE``
    Path to a CA bundle. For Amazon RDS and Aurora, download ``global-bundle.pem``
    from https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem. When
    set, the server certificate **and** hostname are verified.

``DB_TLS_ALLOW_UNVERIFIED``
    Defaults to ``false``. Set to ``true`` to permit encrypted-but-unverified
    connections when no CA bundle is available. Encryption still applies; only
    peer authentication is skipped.

``DB_REQUIRE_TLS``
    Defaults to ``true``. Setting it to ``false`` permits an unencrypted
    connection **to a loopback host only**. Ignored for any other host.

Note on Oracle
--------------

Oracle does not negotiate TLS on the standard TCP listener: encrypted traffic
uses a separate TCPS endpoint (port 2484 on Amazon RDS). :func:`oracle_dsn`
therefore builds a TCPS descriptor, and the secret must point at the TLS
listener port. That is a deployment prerequisite, not something the client can
negotiate.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any

LOG = logging.getLogger(__name__)

CA_BUNDLE_ENV = "DB_SSL_CA_BUNDLE"
REQUIRE_TLS_ENV = "DB_REQUIRE_TLS"
ALLOW_UNVERIFIED_ENV = "DB_TLS_ALLOW_UNVERIFIED"

_FALSEY = {"0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain", ""}


class TlsConfigurationError(RuntimeError):
    """Raised when a connection cannot be made safely with the current settings."""


def ca_bundle() -> str | None:
    """Return the configured CA bundle path, or ``None`` when unset."""
    value = (os.environ.get(CA_BUNDLE_ENV) or "").strip()
    return value or None


def tls_required() -> bool:
    """Return whether the operator has asked for TLS. Defaults to ``True``.

    This reflects the request only. Use :func:`plaintext_permitted` to decide
    whether an unencrypted connection is actually allowed, since the opt-out is
    restricted to loopback hosts.
    """
    value = (os.environ.get(REQUIRE_TLS_ENV) or "true").strip().lower()
    return value not in _FALSEY


def unverified_allowed() -> bool:
    """Return whether encrypted-but-unverified TLS has been acknowledged."""
    value = (os.environ.get(ALLOW_UNVERIFIED_ENV) or "false").strip().lower()
    return value in _TRUTHY


def is_loopback(host: str | None) -> bool:
    """Return whether ``host`` refers to the local machine.

    A Unix-socket directory (a path, as psycopg2 accepts) counts as local. An
    unknown or unset host does **not**, so callers that cannot supply a host are
    treated as remote and keep encryption.
    """
    if host is None:
        return False
    candidate = host.strip().strip("[]").lower()
    if candidate.startswith("/"):
        # Unix domain socket directory: never traverses a network.
        return True
    if candidate in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def plaintext_permitted(engine: str, host: str | None) -> bool:
    """Return whether an unencrypted connection to ``host`` is allowed.

    Only true when the operator disabled TLS *and* the target is loopback.
    """
    if tls_required():
        return False
    if is_loopback(host):
        LOG.warning(
            "%s connection to local host %r is NOT encrypted because %s is "
            "disabled. This is permitted only for a loopback address.",
            engine,
            host,
            REQUIRE_TLS_ENV,
        )
        return True
    LOG.error(
        "%s: ignoring %s=false because host %r is not a loopback address. "
        "Encryption stays enabled; disabling it would put credentials and query "
        "data on the network in cleartext.",
        engine,
        REQUIRE_TLS_ENV,
        host,
    )
    return False


def _unverified_or_raise(engine: str) -> None:
    """Permit unverified TLS only when explicitly acknowledged."""
    if unverified_allowed():
        LOG.warning(
            "%s connection is encrypted but the server certificate is NOT "
            "verified, because %s is set and no CA bundle is configured. This "
            "does not protect against an active man-in-the-middle.",
            engine,
            ALLOW_UNVERIFIED_ENV,
        )
        return
    raise TlsConfigurationError(
        f"{engine}: refusing to connect without certificate verification. "
        f"Set {CA_BUNDLE_ENV} to a CA bundle (for Amazon RDS and Aurora, "
        f"https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem), or "
        f"set {ALLOW_UNVERIFIED_ENV}=true to accept an encrypted but "
        f"unverified connection."
    )


def mssql_connect_kwargs(host: str | None = None) -> dict[str, Any]:
    """Return ``pymssql.connect`` keyword arguments for encryption in transit.

    What TDS actually guarantees
    ---------------------------

    The TDS protocol always encrypts the login packet, so the password does not
    cross the network in cleartext even on an otherwise unencrypted session.
    Whether the *rest* of the session is encrypted is decided by the server:
    it is only guaranteed when SQL Server has ``ForceEncryption`` enabled.

    What this driver cannot do
    --------------------------

    ``pymssql`` wraps FreeTDS, which takes its TLS settings from
    ``freetds.conf`` rather than from ``connect()`` keywords, and it exposes no
    per-connection CA bundle option. There is therefore no way to request
    verified TLS from Python here, which is why a configured CA bundle cannot
    be honoured and is reported as unverified rather than silently ignored.

    Consequently a remote SQL Server connection is treated as encrypted but
    unverified, and requires the same explicit operator acknowledgement as the
    other engines. Set ``ForceEncryption`` on the server and a trusted
    certificate to make the session encryption guaranteed rather than
    negotiated.

    Args:
        host: The target host, used to decide whether a plaintext opt-out
            applies. Omit only when the host is unknown; the connection is then
            treated as remote and stays encrypted.

    Raises:
        TlsConfigurationError: Unverified TLS has not been acknowledged.
    """
    if plaintext_permitted("SQL Server", host):
        return {}
    # A CA bundle cannot be applied through pymssql, so having one configured
    # does not upgrade this connection to verified. Say so rather than letting
    # the operator believe the bundle took effect.
    if ca_bundle():
        LOG.warning(
            "SQL Server: %s is set but pymssql cannot apply a CA bundle, so "
            "the certificate is still NOT verified. Configure FreeTDS directly "
            "if verified TLS is required.",
            CA_BUNDLE_ENV,
        )
    _unverified_or_raise("SQL Server")
    return {}


def postgres_ssl_kwargs(host: str | None = None) -> dict[str, Any]:
    """Return ``psycopg2.connect`` keyword arguments for encryption in transit.

    Args:
        host: The target host, used to decide whether a plaintext opt-out
            applies. Omit only when the host is unknown; the connection is then
            treated as remote and stays encrypted.

    Raises:
        TlsConfigurationError: No CA bundle and unverified TLS not acknowledged.
    """
    if plaintext_permitted("PostgreSQL", host):
        return {"sslmode": "disable"}
    bundle = ca_bundle()
    if bundle:
        return {"sslmode": "verify-full", "sslrootcert": bundle}
    _unverified_or_raise("PostgreSQL")
    return {"sslmode": "require"}


def mysql_ssl_kwargs(host: str | None = None) -> dict[str, Any]:
    """Return ``pymysql.connect`` keyword arguments for encryption in transit.

    PyMySQL's implicit default is *PREFERRED*: it attempts TLS but silently
    falls back to cleartext if the server declines, so encryption is not
    actually guaranteed. These kwargs make it explicit instead.

    Args:
        host: The target host. See :func:`postgres_ssl_kwargs`.

    Raises:
        TlsConfigurationError: No CA bundle and unverified TLS not acknowledged.
    """
    if plaintext_permitted("MySQL", host):
        return {"ssl_disabled": True}
    bundle = ca_bundle()
    if bundle:
        return {
            "ssl_ca": bundle,
            "ssl_verify_cert": True,
            "ssl_verify_identity": True,
        }
    _unverified_or_raise("MySQL")
    # A truthy mapping forces an SSL context. Without a CA, PyMySQL builds a
    # context with verify_mode=CERT_NONE, so traffic is encrypted but the peer
    # is unauthenticated.
    return {"ssl": {"ssl": True}}


def redis_ssl_kwargs(host: str | None = None) -> dict[str, Any]:
    """Return ``redis.Redis`` keyword arguments for encryption in transit.

    redis-py speaks cleartext unless ``ssl=True`` is passed. That matters more
    here than for the SQL engines: Redis authenticates with an ``AUTH`` command
    carrying the password as a plain argument, so an unencrypted connection puts
    the credential on the wire, not just the query data.

    Requires ElastiCache in-transit encryption to be enabled on the cluster.

    Args:
        host: The target host. See :func:`postgres_ssl_kwargs`.

    Raises:
        TlsConfigurationError: No CA bundle and unverified TLS not acknowledged.
    """
    if plaintext_permitted("Redis", host):
        return {}
    bundle = ca_bundle()
    if bundle:
        return {
            "ssl": True,
            "ssl_ca_certs": bundle,
            "ssl_cert_reqs": "required",
            "ssl_check_hostname": True,
        }
    _unverified_or_raise("Redis")
    return {"ssl": True, "ssl_cert_reqs": "none", "ssl_check_hostname": False}


def oracle_dsn(
    host: str,
    port: int,
    *,
    sid: str | None = None,
    service_name: str | None = None,
) -> str:
    """Build an Oracle connect descriptor, using TCPS when TLS applies.

    Args:
        host: Database host.
        port: Listener port. For TLS on Amazon RDS this is the TCPS listener
            (2484), not the default 1521.
        sid: Oracle SID, when connecting by SID.
        service_name: Oracle service name, when connecting by service.

    Returns:
        A connect descriptor string suitable for ``oracledb.connect(dsn=...)``.

    Raises:
        TlsConfigurationError: No CA bundle and unverified TLS not acknowledged.
    """
    if sid and service_name:
        raise ValueError("Provide either sid or service_name, not both.")
    if not sid and not service_name:
        raise ValueError("One of sid or service_name is required.")

    connect_data = f"(SID={sid})" if sid else f"(SERVICE_NAME={service_name})"

    if plaintext_permitted("Oracle", host):
        protocol = "TCP"
        security = ""
    else:
        protocol = "TCPS"
        if ca_bundle():
            security = "(SECURITY=(SSL_SERVER_DN_MATCH=YES))"
        else:
            _unverified_or_raise("Oracle")
            security = "(SECURITY=(SSL_SERVER_DN_MATCH=NO))"

    return (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL={protocol})(HOST={host})(PORT={port}))"
        f"(CONNECT_DATA={connect_data}){security})"
    )


def oracle_connect_kwargs(host: str | None = None) -> dict[str, Any]:
    """Return ``oracledb.connect`` keyword arguments that complement the DSN.

    Args:
        host: The target host. See :func:`postgres_ssl_kwargs`.
    """
    if plaintext_permitted("Oracle", host):
        return {}
    bundle = ca_bundle()
    if bundle:
        # oracledb reads the trust store from the wallet location when set.
        return {
            "ssl_server_dn_match": True,
            "wallet_location": os.path.dirname(bundle),
        }
    return {"ssl_server_dn_match": False}
