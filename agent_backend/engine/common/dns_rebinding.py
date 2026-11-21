"""
Connection-Level DNS Rebinding & SSRF Protection Engine.

Protects against Time-Of-Check to Time-Of-Use (TOCTOU) DNS rebinding attacks
by validating the resolved IP address immediately at socket connection time
before any TCP handshake or HTTP payload transmission occurs.

Integrates with Python `requests` and `urllib3` via custom HTTPAdapter:
- Preserves full TLS SNI certificate verification
- Preserves standard HTTP Host headers
- Disallows connection to loopback, private, link-local, and cloud metadata IPs
- Enforces strict cloud metadata blocking under all configurations
"""

import os
import socket
import ipaddress
from typing import Optional, Tuple
import urllib3
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.util.connection import allowed_gai_family, _set_socket_options, _DEFAULT_TIMEOUT
from urllib3.exceptions import LocationParseError, NewConnectionError
from requests.adapters import HTTPAdapter

try:
    from engine.common.ssrf_protection import is_blocked_ip
except ImportError:
    try:
        from common.ssrf_protection import is_blocked_ip
    except ImportError:
        from agent_backend.engine.common.ssrf_protection import is_blocked_ip


def safe_create_connection(
    address: Tuple[str, int],
    timeout: float = _DEFAULT_TIMEOUT,
    source_address: Optional[Tuple[str, int]] = None,
    socket_options: Optional[list] = None,
    allow_local: bool = False,
) -> socket.socket:
    """
    Connect to address (host, port) while verifying that the destination IP
    is not in a blocked range at connection time.

    Mitigates DNS Rebinding TOCTOU:
    Resolves the hostname, inspects the actual candidate IP before calling sock.connect(),
    and raises ValueError if the IP belongs to a forbidden range.
    """
    host, port = address
    if host.startswith("["):
        host = host.strip("[]")

    err = None
    family = allowed_gai_family()

    try:
        host.encode("idna")
    except UnicodeError:
        raise LocationParseError(f"'{host}', label empty or too long") from None

    try:
        records = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise OSError(f"Failed to resolve host '{host}': {e}") from e

    if not records:
        raise OSError(f"getaddrinfo returned an empty address list for '{host}'")

    for res in records:
        af, socktype, proto, canonname, sa = res
        ip_str = sa[0]

        # 1. Connection-time IP verification
        try:
            ip_addr = ipaddress.ip_address(ip_str)
            blocked, reason = is_blocked_ip(ip_addr, allow_local=allow_local)
            if blocked:
                raise ValueError(
                    f"SSRF / DNS Rebinding protection: Target '{host}' resolved "
                    f"at connection time to blocked IP ({ip_str}). {reason}"
                )
        except ValueError as val_err:
            if "SSRF / DNS Rebinding protection" in str(val_err):
                raise
            # If ipaddress fails to parse for some unexpected reason, abort safely
            raise ValueError(f"SSRF protection: Invalid IP address resolved: {ip_str}")

        # 2. Establish connection to verified IP
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            _set_socket_options(sock, socket_options)

            if timeout is not _DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)

            sock.connect(sa)
            return sock

        except OSError as conn_err:
            err = conn_err
            if sock is not None:
                sock.close()

    if err is not None:
        raise err
    raise OSError("Failed to connect to any resolved address.")


class SafeHTTPConnection(HTTPConnection):
    """
    HTTPConnection subclass enforcing connection-level IP verification.
    """
    allow_local: bool = False

    def _new_conn(self) -> socket.socket:
        return safe_create_connection(
            (self._dns_host, self.port),
            self.timeout,
            source_address=self.source_address,
            socket_options=self.socket_options,
            allow_local=getattr(self, "allow_local", False),
        )


class SafeHTTPSConnection(HTTPSConnection):
    """
    HTTPSConnection subclass enforcing connection-level IP verification.
    Preserves TLS SNI hostname matching and certificate verification.
    """
    allow_local: bool = False

    def _new_conn(self) -> socket.socket:
        return safe_create_connection(
            (self._dns_host, self.port),
            self.timeout,
            source_address=self.source_address,
            socket_options=self.socket_options,
            allow_local=getattr(self, "allow_local", False),
        )


class SafeHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = SafeHTTPConnection


class SafeHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = SafeHTTPSConnection


class SafePoolManager(urllib3.PoolManager):
    """
    PoolManager that routes HTTP and HTTPS connections through DNS rebinding safe connection classes.
    """
    def __init__(self, *args, allow_local: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_local = allow_local
        self.pool_classes_by_scheme = {
            "http": SafeHTTPConnectionPool,
            "https": SafeHTTPSConnectionPool,
        }

    def _new_pool(self, scheme, host, port, request_context=None):
        pool = super()._new_pool(scheme, host, port, request_context=request_context)
        # Propagate allow_local to the pool's ConnectionCls
        if hasattr(pool, "ConnectionCls"):
            pool.ConnectionCls.allow_local = self.allow_local
        return pool


class DNSRebindingSafeAdapter(HTTPAdapter):
    """
    A requests.adapters.HTTPAdapter that enforces socket connection-level IP verification
    to prevent DNS rebinding attacks while preserving normal TLS verification.
    """

    def __init__(self, *args, allow_local: Optional[bool] = None, **kwargs):
        if allow_local is None:
            self.allow_local = os.getenv("ALLOW_LOCAL_TARGETS", "false").lower() in ("true", "1", "yes")
        else:
            self.allow_local = allow_local
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = SafePoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            allow_local=self.allow_local,
            **pool_kwargs
        )
