"""mDNS advertisement so iOS shell can discover Arbor Core on the local network."""
import logging
import os

logger = logging.getLogger(__name__)
_zeroconf = None
_info = None


def advertise():
    try:
        from zeroconf import ServiceInfo, Zeroconf
        import socket

        global _zeroconf, _info
        port = int(os.getenv("PORT", "8090"))
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        _info = ServiceInfo(
            "_nervus._tcp.local.",
            f"nervus2-arbor._nervus._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties={"version": "2.0.0"},
        )
        _zeroconf = Zeroconf()
        _zeroconf.register_service(_info)
        logger.info("mDNS advertised: nervus2-arbor @ %s:%d", local_ip, port)
    except Exception as exc:
        logger.warning("mDNS advertisement failed (non-fatal): %s", exc)


def stop():
    global _zeroconf, _info
    if _zeroconf and _info:
        try:
            _zeroconf.unregister_service(_info)
            _zeroconf.close()
        except Exception:
            pass
