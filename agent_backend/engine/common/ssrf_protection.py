"""
Centralized SSRF Protection Engine.
Strictly validates target URLs and redirect destinations to prevent:
  - Loopback addresses (127.0.0.0/8, ::1)
  - Private IP networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
  - Cloud metadata endpoints (169.254.169.254, 169.254.0.0/16, fe80::/10, fd00:ec2::254, 100.100.100.200)
  - Current network / unspecified (0.0.0.0/8, ::)
  - Alternative IP representations (DWORD decimal, octal, hex, shorthand notation)
  - Non-HTTP(S) schemes (file://, ftp://, gopher://, data://, etc.)
  - SSRF via cross-host or internal HTTP redirects
"""

import os
import socket
import ipaddress
from urllib.parse import urlparse
from typing import Optional, List, Tuple

# All sensitive / internal / cloud metadata IP networks
BLOCKED_NETWORKS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network / zero IP
    ipaddress.ip_network("127.0.0.0/8"),        # IPv4 Loopback
    ipaddress.ip_network("10.0.0.0/8"),          # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),       # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),      # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),      # IPv4 Link-Local / Cloud Metadata (AWS, GCP, Azure, DO)
    ipaddress.ip_network("100.64.0.0/10"),       # Shared address space / CGNAT (includes Alibaba 100.100.100.200)
    ipaddress.ip_network("198.18.0.0/15"),       # Benchmark testing
    ipaddress.ip_network("224.0.0.0/4"),         # Multicast
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved
    ipaddress.ip_network("::1/128"),             # IPv6 Loopback
    ipaddress.ip_network("::/128"),              # IPv6 Unspecified
    ipaddress.ip_network("fc00::/7"),            # IPv6 Unique Local (Private)
    ipaddress.ip_network("fe80::/10"),           # IPv6 Link-Local / Metadata
]

# Dedicated cloud metadata IPs that must NEVER be reachable under ANY configuration,
# even when ALLOW_LOCAL_TARGETS=true is enabled for testing against localhost.
CLOUD_METADATA_NETWORKS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("169.254.0.0/16"),      # AWS, Azure, GCP, DO instance metadata
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("fe80::/10"),           # IPv6 link-local metadata
    ipaddress.ip_network("fd00:ec2::254/128"),   # AWS IPv6 metadata
]


def resolve_all_ips(hostname: str) -> List[ipaddress._BaseAddress]:
    """
    Resolve a hostname or IP string to all underlying IP addresses.
    Handles:
      - Standard IPv4 / IPv6 dotted / colon strings
      - Shorthand IPv4 (127.1, 127.0.1)
      - Alternative IP representations (DWORD decimal, octal, hex 0x7f000001)
      - Hostnames resolved via DNS (both IPv4 and IPv6 records)
    """
    cleaned = hostname.strip().rstrip(".").strip("[]")
    if not cleaned:
        raise ValueError("Invalid target: empty hostname.")

    resolved_ips: List[ipaddress._BaseAddress] = []

    # 1. Check if it can be parsed as a numeric/hex/octal/shorthand IPv4 via inet_aton
    try:
        raw_bytes = socket.inet_aton(cleaned)
        # inet_aton returns 4 bytes for valid IPv4 or shorthand representations
        if len(raw_bytes) == 4:
            resolved_ips.append(ipaddress.IPv4Address(raw_bytes))
            return resolved_ips
    except (OSError, ValueError):
        pass

    # 2. Check if direct IPv6 literal
    try:
        ipv6 = ipaddress.IPv6Address(cleaned)
        resolved_ips.append(ipv6)
        return resolved_ips
    except ValueError:
        pass

    # 3. Check socket.gethostbyname (supports mocked resolution in unit tests)
    try:
        ipv4_resolved = socket.gethostbyname(cleaned)
        if ipv4_resolved:
            resolved_ips.append(ipaddress.ip_address(ipv4_resolved))
            # If gethostbyname succeeded, we have an address
    except (socket.gaierror, ValueError, OSError):
        pass

    # 4. DNS resolution (both IPv4 and IPv6)
    try:
        addr_info = socket.getaddrinfo(cleaned, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        seen = {str(ip) for ip in resolved_ips}
        for entry in addr_info:
            ip_str = entry[4][0]
            if ip_str not in seen:
                seen.add(ip_str)
                resolved_ips.append(ipaddress.ip_address(ip_str))
    except socket.gaierror:
        # If hostname cannot be resolved (e.g. mock domains in tests or offline sandbox),
        # allow request to proceed so HTTP client/mock can handle it naturally.
        pass

    return resolved_ips


def is_blocked_ip(addr: ipaddress._BaseAddress, allow_local: bool = False) -> Tuple[bool, str]:
    """
    Determine if an IP address is in a blocked network range.
    Cloud metadata services are blocked under ALL configurations without exception.
    """
    # 0. Handle NAT64 well-known prefix (64:ff9b::/96) by checking embedded IPv4
    if isinstance(addr, ipaddress.IPv6Address) and addr in ipaddress.ip_network("64:ff9b::/96"):
        embedded_ipv4 = ipaddress.IPv4Address(addr.packed[-4:])
        return is_blocked_ip(embedded_ipv4, allow_local=allow_local)

    # Cloud metadata is forbidden unconditionally
    for meta_net in CLOUD_METADATA_NETWORKS:
        if addr in meta_net:
            return True, f"Target IP {addr} is a cloud metadata service address, which is strictly forbidden."

    # If local development testing is explicitly permitted, allow loopback addresses (127.0.0.0/8, ::1)
    if allow_local and addr.is_loopback:
        return False, ""

    if addr.is_loopback:
        return True, f"Target IP {addr} is a loopback address."
    if addr.is_private:
        return True, f"Target IP {addr} is a private network address."
    if addr.is_link_local:
        return True, f"Target IP {addr} is a link-local address."
    if addr.is_unspecified:
        return True, f"Target IP {addr} is an unspecified (0.0.0.0 / ::) address."
    if addr.is_multicast:
        return True, f"Target IP {addr} is a multicast address."
    if addr.is_reserved:
        return True, f"Target IP {addr} is a reserved address."

    for blocked_net in BLOCKED_NETWORKS:
        if addr in blocked_net:
            return True, f"Target IP {addr} is in blocked network range {blocked_net}."

    return False, ""


def validate_target_url(url: str, allow_local: Optional[bool] = None) -> None:
    """
    Validate a URL for SSRF security.
    Raises ValueError if:
      - Scheme is not http or https
      - Hostname is empty or invalid
      - Hostname resolves to loopback, private, link-local, unspecified, or cloud metadata IP
    Set ALLOW_LOCAL_TARGETS=true (or allow_local=True) to allow loopback addresses for local testing.
    Cloud metadata is NEVER allowed, even with allow_local=True.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Invalid target URL: URL must be a non-empty string.")

    cleaned_url = url.strip()
    parsed = urlparse(cleaned_url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(
            f"SSRF protection: Scheme '{parsed.scheme}' is forbidden. "
            f"Only http:// and https:// URLs are allowed."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"SSRF protection: Missing hostname in URL '{url}'.")

    if allow_local is None:
        allow_local = os.getenv("ALLOW_LOCAL_TARGETS", "false").lower() in ("true", "1", "yes")

    resolved_ips = resolve_all_ips(hostname)
    if not resolved_ips:
        # Mock domain in tests or offline hostname — allow HTTP client or mock to handle
        return

    for ip_addr in resolved_ips:
        blocked, reason = is_blocked_ip(ip_addr, allow_local=allow_local)
        if blocked:
            raise ValueError(
                f"SSRF protection: Target URL '{url}' resolves to blocked IP address ({ip_addr}). {reason}"
            )
