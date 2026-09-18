import asyncio
import json
import os
import re
import shutil
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.config import Settings
from app.egress import EgressProxy
from app.inspection import HIDDEN_LINKS_JS, IDENTITY_JS, LINKS_JS
from app.schemas import Decision, DiscoveryError, Link, Observation
from app.urls import prefer_https, web_url

_SOCKET_DIR_LOGGED = False


def _writable_browser_dir() -> Path | None:
    """A directory agent-browser and Chromium can write to, with a short path (a Unix
    socket path cannot exceed ~103 bytes). Under a read-only container root filesystem
    the default $HOME/.agent-browser is not writable, so prefer an explicit override,
    then the data volume (proven writable by the app), then the temp filesystem."""
    candidates = []
    if os.environ.get("AGENT_BROWSER_SOCKET_DIR"):
        candidates.append(Path(os.environ["AGENT_BROWSER_SOCKET_DIR"]))
    if os.environ.get("DATA_DIR"):
        candidates.append(Path(os.environ["DATA_DIR"]) / "ab")
    candidates.append(Path(tempfile.gettempdir()) / "ab")
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".wtest"
            probe.write_text("x")
            probe.unlink()
            return cand
        except OSError:
            continue
    return None


def subprocess_env() -> dict:
    global _SOCKET_DIR_LOGGED
    # Do not pass the application's API keys to Chromium or agent-browser. HOME is kept
    # as-is so the local OS keychain/browser profile still resolve during development.
    env = {k: v for k, v in os.environ.items()
           if k in {"PATH", "HOME", "TMPDIR", "TEMP", "LANG", "SYSTEMROOT"}}
    if not env.get("HOME"):
        env["HOME"] = tempfile.gettempdir()
    socket_dir = _writable_browser_dir()
    if socket_dir is not None:
        env["AGENT_BROWSER_SOCKET_DIR"] = str(socket_dir)
        cache = socket_dir / "cache"
        try:
            cache.mkdir(exist_ok=True)
            env["XDG_CACHE_HOME"] = str(cache)
        except OSError:
            pass
    if not _SOCKET_DIR_LOGGED:
        _SOCKET_DIR_LOGGED = True
        print(f"[browser] agent-browser socket dir: {socket_dir or 'DEFAULT (~/.agent-browser)'}",
              flush=True)
    if os.environ.get("AGENT_BROWSER_DEBUG"):
        env["AGENT_BROWSER_DEBUG"] = os.environ["AGENT_BROWSER_DEBUG"]
    return env


class BrowserSession:
    def __init__(self, settings: Settings, run_id: str, fixture_port: int | None = None):
        self.settings, self.run_id = settings, run_id
        self.fixture_port = fixture_port
        self.process = self.playwright = self.browser = self.proxy = None
        self.profile = None
        self.started_agent = False
        self.history: list[str] = []
        self.click_links: dict[str, list[Link]] = {}
        self.visited_urls: list[str] = []
        self.navigation_attempts: list[dict] = []

    async def __aenter__(self):
        try:
            self.playwright = await async_playwright().start()
            self.executable = self.settings.chromium_executable
            if not self.executable:
                candidates = [self.playwright.chromium.executable_path,
                              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                              "/usr/bin/chromium"]
                self.executable = next((p for p in candidates if Path(p).is_file()), "")
            if not self.executable:
                raise DiscoveryError("browser_error", "Chromium missing. Run uv run playwright install chromium.")
            if not shutil.which(self.settings.agent_browser_binary):
                raise DiscoveryError("browser_error", "agent-browser is not installed or not on PATH.")
            await self._launch()
            return self
        except BaseException:
            await self.close()
            raise

    async def _launch(self):
        # The egress proxy (SSRF defense) can be disabled for a trusted deployment;
        # it is the suspect for a CDP reset on some native-Linux container runtimes.
        proxy_disabled = os.environ.get("DISABLE_EGRESS_PROXY") == "1"
        self.proxy = None if proxy_disabled else await EgressProxy(self.fixture_port).start()
        self.profile = tempfile.TemporaryDirectory(prefix="jobsource-")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        args = [self.executable, "--headless=new", f"--remote-debugging-port={self.port}",
                "--remote-debugging-address=127.0.0.1",
                # Chrome 111+ resets a DevTools WebSocket whose Origin is not allowed
                # ("Connection reset without closing handshake"); the port is bound to
                # loopback only, so allow the local CDP clients to connect.
                "--remote-allow-origins=*", f"--user-data-dir={self.profile.name}",
                "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
                "--disable-component-update", "--disable-quic", "--disable-extensions",
                # Containers give /dev/shm only ~64 MB, which makes headless Chromium
                # hang or crash rendering heavy pages; write shared memory to /tmp instead.
                "--disable-dev-shm-usage", "--disable-gpu",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--window-size=1440,1000"]
        if self.proxy is not None:
            args += [f"--proxy-server=http://127.0.0.1:{self.proxy.port}",
                     "--proxy-bypass-list=<-loopback>"]
        args.append("about:blank")
        if self.settings.chromium_no_sandbox:
            args.insert(1, "--no-sandbox")
        self.process = await asyncio.create_subprocess_exec(
            *args, env=subprocess_env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(60):
                try:
                    r = await client.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
                    if r.is_success:
                        break
                except httpx.HTTPError:
                    pass
                if self.process.returncode is not None:
                    raise DiscoveryError("browser_error", "Chromium exited during startup; check sandbox and runtime dependencies.")
                await asyncio.sleep(0.2)
            else:
                raise DiscoveryError("browser_error", "Chromium CDP startup timed out.")
        self.browser = await self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.context = self.browser.contexts[0]
        self.context.set_default_timeout(10000)
        await self._warm_up()

    async def _warm_up(self):
        # On native Linux the first agent-browser command against a COLD daemon hangs while
        # it establishes the CDP connection; the daemon then stays alive and finishes
        # connecting in the background, so the same session answers instantly once warm
        # (proven: a killed first call, then a second call on the same session, succeeds).
        # Poll the SAME session with short deadlines until it responds. A fresh session each
        # time would only ever spawn new cold daemons, so reusing this session is the fix.
        deadline = asyncio.get_event_loop().time() + 75
        last_error = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                await self.command("get", "url", timeout=8)
                return
            except (DiscoveryError, TimeoutError) as exc:
                last_error = exc
                await asyncio.sleep(2)
        raise last_error or DiscoveryError("browser_error", "agent-browser did not warm up.")

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self.started_agent:
            try:
                await self.command("close", timeout=5)
            except Exception:
                pass
            self.started_agent = False
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            await self.playwright.stop()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.proxy:
            await self.proxy.close()
        self._cleanup_profile()

    def _cleanup_profile(self):
        # Chromium may still hold files open as its temp profile is removed, which raises
        # OSError(39, 'Directory not empty'). That is a cleanup race, not a run failure, so
        # never let it surface: fall back to a best-effort recursive delete.
        if self.profile:
            try:
                self.profile.cleanup()
            except OSError:
                shutil.rmtree(self.profile.name, ignore_errors=True)
            self.profile = None

    async def command(self, *args, timeout=30):
        # stdout carries the JSON result; stderr is inherited so agent-browser's own
        # diagnostics stream live to the container logs, even when a command hangs.
        process = await asyncio.create_subprocess_exec(
            self.settings.agent_browser_binary, "--session", f"jobsource-{self.run_id}",
            "--cdp", str(self.port), "--json", *args,
            env=subprocess_env(), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=None,
        )
        self.started_agent = True

        async def terminate():
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            # A hung agent-browser command must not surface as the run deadline.
            await terminate()
            raise DiscoveryError("browser_error",
                                 f"agent-browser '{args[0] if args else 'command'}' did not respond "
                                 f"within {timeout}s.") from None
        except BaseException:
            await terminate()
            raise
        try:
            data = json.loads(stdout)
        except ValueError:
            raise DiscoveryError("browser_error", "agent-browser returned invalid command output.") from None
        if not data.get("success", process.returncode == 0):
            # Browser errors can include page text; bound it and never execute it.
            raise DiscoveryError("browser_action_failed", str(data.get("error", "Browser command failed"))[:450])
        return data.get("data", data)

    async def current_page(self):
        # The two CDP clients can observe a redirect at slightly different times.
        for _ in range(4):
            result = await self.command("get", "url")
            url = result.get("url", "") if isinstance(result, dict) else str(result)
            pages = [p for p in self.context.pages if not p.is_closed()]
            for page in reversed(pages):
                if page.url == url:
                    return page
            await asyncio.sleep(0.15)
        raise DiscoveryError("browser_error", "Could not synchronize agent-browser and Playwright active page.")

    def allowed_navigation(self, url: str):
        if self.fixture_port and url.startswith(f"http://127.0.0.1:{self.fixture_port}/"):
            return url
        return web_url(url)

    async def open(self, url):
        url = self.allowed_navigation(url)
        parsed = urlsplit(url)
        variants = [url]
        if parsed.scheme in ("http", "https") and not self.fixture_port:
            # Scheme fallback only: try https first, then http. Never invent a
            # hostname or an ATS tenant.
            https = urlunsplit(parsed._replace(scheme="https"))
            http = urlunsplit(parsed._replace(scheme="http"))
            variants = [https] + ([http] if http != https else [])
        last_error = None
        for candidate in variants:
            try:
                await self.command("open", candidate)
                self.navigation_attempts.append({"requested_url": url, "attempt_url": candidate, "ok": True})
                return
            except (DiscoveryError, TimeoutError) as exc:
                last_error = exc
                # Some sites keep media/network requests alive after the usable page
                # renders. Accept readiness only on the requested host with real text.
                if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
                    try:
                        page = await self.current_page()
                        text = await page.locator("body").inner_text(timeout=2000)
                        if urlsplit(page.url).hostname == urlsplit(candidate).hostname and len(text.strip()) > 100:
                            self.navigation_attempts.append({"requested_url": url, "attempt_url": candidate,
                                                             "ok": True, "recovery": "rendered_after_load_timeout"})
                            return
                    except (DiscoveryError, PlaywrightError, TimeoutError):
                        pass
                self.navigation_attempts.append({"requested_url": url, "attempt_url": candidate,
                                                 "ok": False, "reason": str(exc)[:450]})
        if isinstance(last_error, DiscoveryError):
            raise last_error
        raise DiscoveryError("browser_action_failed", "Navigation exceeded its time limit.")

    async def observe(self) -> Observation:
        page = await self.current_page()
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        # Give genuinely blank/loading SPA shells a short content-based wait.
        try:
            await page.wait_for_function("""() => document.body &&
                (document.body.innerText.trim().length > 40 || document.querySelectorAll('a[href]').length > 0)""",
                                         timeout=5000)
        except PlaywrightError:
            pass
        texts, links, frames = [], [], []
        identity = [await page.title()]
        for frame in page.frames[:12]:
            try:
                text = await frame.locator("body").inner_text(timeout=4000)
                texts.append(text[:18000])
                extracted = await frame.locator("a[href]").evaluate_all(LINKS_JS)
                for link in extracted:
                    # Present external http links as https so a usable board is not
                    # dismissed as malformed; open() still falls back to http.
                    link["url"] = prefer_https(link["url"])
                    links.append(Link(**link, frame_url=frame.url))
                identity.append(await frame.evaluate(IDENTITY_JS))
                if frame != page.main_frame and frame.url.startswith(("http:", "https:")):
                    frames.append(frame.url)
            except Exception:
                continue
        links.extend(self.click_links.get(page.url, []))
        # Cross-host anchors present in the DOM but hidden behind a collapsed menu or
        # accordion (zero layout box). These are commonly the real careers/ATS boards.
        try:
            hidden = await page.evaluate(HIDDEN_LINKS_JS)
        except PlaywrightError:
            hidden = []
        seen = {link.url for link in links}
        for entry in hidden[:40]:
            url = prefer_https(entry.get("url", ""))
            if url in seen:
                continue
            seen.add(url)
            links.append(Link(text=entry.get("text", ""), url=url, provenance="hidden_dom"))
        if page.url not in self.visited_urls:
            self.visited_urls.append(page.url)
        snapshot_data = await self.command("snapshot", "-i", "-u")
        snapshot = snapshot_data.get("snapshot", "") if isinstance(snapshot_data, dict) else str(snapshot_data)
        return Observation(url=page.url, title=await page.title(), text="\n\n".join(texts)[:28000],
                           snapshot=snapshot[:26000], links=links[:600], frames=frames,
                           identity_text="\n".join(identity)[:4000], visited_urls=self.visited_urls[-30:],
                           scroll_y=round(await page.evaluate("window.scrollY")))

    async def act(self, decision: Decision, observation: Observation):
        action, target = decision.action, decision.target
        previous_pages = list(self.context.pages)
        clicked_text = ""
        if action == "open":
            if target not in {link.url for link in observation.links} | set(observation.frames) | set(self.visited_urls):
                raise DiscoveryError("invalid_action", "Model proposed a URL not present in the current observation.")
            await self.open(target)
        elif action == "click":
            # Snapshot forms may contain either @eN or [ref=eN].
            ref = target.removeprefix("@")
            if not re.fullmatch(r"e\d+", ref) or not re.search(rf"(?:@|ref=){ref}\b", observation.snapshot):
                raise DiscoveryError("invalid_action", "Model proposed a stale or unknown element reference.")
            reference_line = next((line for line in observation.snapshot.splitlines()
                                   if re.search(rf"(?:@|ref=){ref}\b", line)), "")
            destination = re.search(r"url=([^\]]+)", reference_line)
            if destination:
                self.allowed_navigation(destination[1])
            if re.search(r"submit|delete|purchase|send application|sign in|log ?in", reference_line, re.I):
                raise DiscoveryError("invalid_action", "This control is outside read-only careers discovery.")
            try:
                content = await self.command("get", "text", "@" + ref)
                clicked_text = str(content.get("text", ""))[:500] if isinstance(content, dict) else str(content)[:500]
            except DiscoveryError:
                pass
            await self.command("click", "@" + ref)
        elif action == "scroll":
            if target not in {"up", "down"}:
                raise DiscoveryError("invalid_action", "Scroll direction must be up or down.")
            await self.command("scroll", target, "700")
        elif action == "fill":
            ref = target.removeprefix("@")
            if not re.fullmatch(r"e\d+", ref):
                raise DiscoveryError("invalid_action", "Invalid search-field reference.")
            line = next((line for line in observation.snapshot.splitlines()
                         if re.search(rf"(?:@|ref=){ref}\b", line)), "")
            if not ("searchbox" in line or ("textbox" in line and re.search(r"search|filter|keyword", line, re.I))):
                raise DiscoveryError("invalid_action", "Only observed search fields can be filled.")
            if not decision.value.strip() or len(decision.value) > 120:
                raise DiscoveryError("invalid_action", "Invalid search query.")
            await self.command("fill", "@" + ref, decision.value)
            await self.command("press", "Enter")
        elif action == "back":
            if not self.history:
                raise DiscoveryError("invalid_action", "No prior navigation is available.")
            await self.open(self.history.pop())
        elif action == "wait":
            await asyncio.sleep(1)
        else:
            raise DiscoveryError("invalid_action", "Unsupported navigation action.")
        await asyncio.sleep(0.4)
        new_pages = [p for p in self.context.pages if p not in previous_pages and not p.is_closed()]
        if new_pages:
            # Read agent-browser's stable tab IDs rather than assuming numeric indices.
            tabs = await self.command("tab")
            entries = tabs.get("tabs", []) if isinstance(tabs, dict) else []
            target_url = new_pages[-1].url
            chosen = next((t for t in entries if t.get("url") == target_url), None)
            if chosen:
                tab_id = chosen.get("tabId", chosen.get("id", chosen.get("index")))
                await self.command("tab", str(tab_id))
        if action in {"click", "open"}:
            destination = (await self.current_page()).url
            if destination != observation.url and destination.startswith(("http://", "https://")):
                if not self.history or self.history[-1] != observation.url:
                    self.history.append(observation.url)
                if action == "click" and clicked_text:
                    self.click_links.setdefault(observation.url, []).append(Link(
                        text=clicked_text, url=destination, frame_url=observation.url,
                        provenance="observed_click_navigation",
                    ))

    async def screenshot(self, path: Path, focus_text: str = ""):
        page = await self.current_page()
        if focus_text:
            try:
                await page.get_by_text(re.compile(re.escape(focus_text), re.I)).first.scroll_into_view_if_needed(timeout=2000)
            except PlaywrightError:
                pass
        await page.screenshot(path=str(path), full_page=False, timeout=10000)

    async def check_detail(self, url: str, expected_title: str = "") -> dict:
        """Read-only Playwright check in a disposable tab; original page stays intact."""
        page = await self.context.new_page()
        try:
            response = await page.goto(self.allowed_navigation(url), wait_until="domcontentloaded", timeout=20000)
            if expected_title:
                await page.get_by_text(re.compile(re.escape(expected_title), re.I)).first.wait_for(state="visible", timeout=10000)
            text = await page.locator("body").inner_text(timeout=7000)
            links = await page.locator("a[href]").evaluate_all(LINKS_JS)
            return {"url": page.url, "status": response.status if response else None,
                    "text": text[:18000], "title": await page.title(), "links": links,
                    "frames": [frame.url for frame in page.frames if frame != page.main_frame
                               and frame.url.startswith(("https://", "http://"))]}
        except PlaywrightError:
            raise DiscoveryError("verification_failed", "The sampled role could not be rendered within the browser time limit.") from None
        finally:
            await page.close()
