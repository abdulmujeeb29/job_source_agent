"""HTTP CONNECT proxy: resolve and pin public IPs before browser connections.

Chromium is launched with a mandatory proxy, implicit loopback bypass disabled,
QUIC disabled, and non-proxied WebRTC disabled. Deploy with network isolation too
when serving untrusted users; CDP itself remains loopback-only.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


async def public_addresses(host: str, port: int) -> list[str]:
    addresses = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Non-public destination blocked")
    return ips


async def connect_addresses(ips: list[str], port: int):
    """Try each already-validated IP; never re-resolve after the public-IP check."""
    last_error = None
    for ip in ips[:4]:
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=4)
        except (OSError, TimeoutError) as exc:
            last_error = exc
    raise OSError("All validated destination addresses failed to connect") from last_error


class EgressProxy:
    def __init__(self, fixture_port: int | None = None):
        # Only supplied directly by local integration tests, never from web input/config.
        self.fixture_port = fixture_port
        self.server = None
        self.tasks: set[asyncio.Task] = set()
        self.blocked = 0

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=65536)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        remote = None
        try:
            async with asyncio.timeout(20):
                header = await reader.readuntil(b"\r\n\r\n")
                method, target, _ = header.split(b"\r\n", 1)[0].decode("ascii").split(" ", 2)
                p = urlsplit("//" + target if method == "CONNECT" else target)
                host, port = p.hostname, p.port or (443 if method == "CONNECT" else 80)
                if not host or p.username or p.password:
                    raise ValueError("Invalid proxy target")
                fixture = host == "127.0.0.1" and port == self.fixture_port
                if not fixture and port not in {80, 443}:
                    raise ValueError("Non-standard destination port")
                ips = [host] if fixture else await public_addresses(host, port)
                upstream, remote = await connect_addresses(ips, port)
                if method == "CONNECT":
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                else:
                    if p.scheme != "http":
                        raise ValueError("Unsupported proxy scheme")
                    path = p.path or "/"
                    if p.query:
                        path += "?" + p.query
                    lines = header.split(b"\r\n")[1:-2]
                    lines = [line for line in lines if not line.lower().startswith(
                        (b"proxy-", b"connection:")
                    )]
                    remote.write(f"{method} {path} HTTP/1.1\r\n".encode() +
                                 b"\r\n".join(lines) + b"\r\nConnection: close\r\n\r\n")
                    await remote.drain()
                await writer.drain()

            async def pipe(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            pipes = [asyncio.create_task(pipe(reader, remote)),
                     asyncio.create_task(pipe(upstream, writer))]
            try:
                await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for item in pipes:
                    item.cancel()
                await asyncio.gather(*pipes, return_exceptions=True)
        except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            self.blocked += 1
            try:
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
            except OSError:
                pass
        finally:
            if remote:
                remote.close()
            writer.close()
            self.tasks.discard(task)
