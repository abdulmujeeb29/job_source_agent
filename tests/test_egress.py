import asyncio
import socket

import httpx
import pytest

from app.egress import EgressProxy, connect_addresses, public_addresses


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.1", "::1", "fd00::1", "0.0.0.0"])
async def test_private_dns_is_rejected(monkeypatch, ip):
    async def addresses(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", addresses)
    with pytest.raises(ValueError):
        await public_addresses("untrusted.example", 80)


async def test_mixed_public_private_dns_is_rejected(monkeypatch):
    async def addresses(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["1.1.1.1", "127.0.0.1"]]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", addresses)
    with pytest.raises(ValueError):
        await public_addresses("rebind.example", 443)


async def test_proxy_blocks_loopback():
    proxy = await EgressProxy().start()
    try:
        async with httpx.AsyncClient(proxy=f"http://127.0.0.1:{proxy.port}") as client:
            response = await client.get("http://127.0.0.1/")
            assert response.status_code == 403
            assert proxy.blocked == 1
    finally:
        await proxy.close()


async def test_connection_falls_back_only_to_prevalidated_addresses(monkeypatch):
    calls = []
    async def connect(ip, port):
        calls.append(ip)
        if len(calls) == 1:
            raise OSError("Unreachable first address")
        return "reader", "writer"
    monkeypatch.setattr(asyncio, "open_connection", connect)
    assert await connect_addresses(["1.1.1.1", "8.8.8.8"], 443) == ("reader", "writer")
    assert calls == ["1.1.1.1", "8.8.8.8"]
