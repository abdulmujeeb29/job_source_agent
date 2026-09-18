import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from app.browser import BrowserSession
from app.schemas import Decision, DiscoveryError


class FixtureSite(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}/role")
            self.end_headers()
            return
        pages = {
            "/": '<h1>Example Inc</h1><a href="/careers" target="_blank">Careers</a>',
            "/careers": '<h1>Example Inc careers</h1><p>Build things with us.</p><iframe src="/jobs"></iframe>',
            "/jobs": '<h1>Example Inc open positions</h1><a href="/role">Software Engineer</a>',
            "/role": '<h1>Software Engineer</h1><p>' + 'Join Example Inc to build useful software. ' * 20 + '</p>',
            "/role-with-ats": '<h1>Software Engineer</h1><p>' + 'Join Example Inc. ' * 20 +
                              '</p><a href="https://jobs.ashbyhq.com/example/role-123">Apply Now</a>',
            "/dynamic": '<h1>Example Inc</h1><button onclick="this.remove()">Reject all cookies</button>'
                        '<button onclick="document.querySelector(\'nav\').hidden=false">Company menu</button>'
                        '<nav hidden><a href="/jobs">Open roles</a></nav>',
            "/button-board": '<h1>Example Inc open positions</h1><button onclick="location.href=\'/role\'">Software Engineer</button>',
            "/hidden-board": '<h1>Example Inc</h1><p>Welcome.</p>'
                             '<div style="display:none"><a href="https://jobs.ashbyhq.com/example">Join us now</a></div>',
            "/cards": '<title>Example Inc careers</title><main><h1>Open positions</h1>'
                      '<article><h2>Software Engineer</h2><a href="/role">See role</a></article>'
                      '<article><h2>Data Analyst</h2><a href="/analyst">See role</a></article></main>',
            "/mixed": '<main><div><h2>Software Engineer</h2><a href="/role">See role</a>'
                      '<h2>Data Analyst</h2><a href="/analyst">See role</a></div></main>',
            "/search": '<form action="/cards"><input type="search" name="q" aria-label="Search companies"><button>Search</button></form>',
            "/delayed": '<body><p>Loading</p><script>setTimeout(()=>document.body.innerHTML="<h1>Software Engineer</h1><p>'
                        + 'Join Example Inc. ' * 20 + '</p>",350)</script></body>',
        }
        path = self.path.split("?")[0]
        self.send_response(200 if path in pages else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(pages.get(path, "Not found").encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()


def action(kind, target):
    return Decision(action=kind, target=target, value="", reason="Fixture navigation", page_kind="other",
                    company_matches=False, company_evidence="", collection_evidence="", listings=[])


@pytest.mark.browser
async def test_shared_browser_new_tab_frame_and_detail(settings, site):
    session = BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site)
    async with session as browser:
        await browser.open(f"http://127.0.0.1:{site}/")
        observation = await browser.observe()
        ref = re.search(r'link "Careers" \[ref=(e\d+)', observation.snapshot)[1]
        await browser.act(action("click", "@" + ref), observation)
        observation = await browser.observe()
        assert observation.url.endswith("/careers")
        assert f"http://127.0.0.1:{site}/jobs" in observation.frames
        assert any(link.text == "Software Engineer" for link in observation.links)
        detail = await browser.check_detail(f"http://127.0.0.1:{site}/role")
        assert detail["status"] == 200
        assert "Software Engineer" in detail["text"]
        assert (await browser.observe()).url.endswith("/careers")
        with pytest.raises(DiscoveryError, match="not present"):
            await browser.act(action("open", "https://invented.example"), observation)
        with pytest.raises(DiscoveryError, match="unknown element"):
            await browser.act(action("click", "@e99999"), observation)
    assert session.process.returncode is not None
    assert not session.proxy.tasks


@pytest.mark.browser
async def test_dynamic_menu_and_delayed_detail(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/dynamic")
        observation = await browser.observe()
        assert not any(link.text == "Open roles" for link in observation.links)
        ref = re.search(r'button "Company menu" \[ref=(e\d+)', observation.snapshot)[1]
        await browser.act(action("click", "@" + ref), observation)
        observation = await browser.observe()
        assert any(link.text == "Open roles" for link in observation.links)
        detail = await browser.check_detail(f"http://127.0.0.1:{site}/delayed", "Software Engineer")
        assert "Software Engineer" in detail["text"]


@pytest.mark.browser
async def test_two_browser_sessions_do_not_share_cookies(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as first:
        async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as second:
            await first.context.add_cookies([{"name": "private_session", "value": "first", "url": f"http://127.0.0.1:{site}"}])
            assert not await second.context.cookies()
            assert first.port != second.port


@pytest.mark.browser
async def test_redirect_cannot_bypass_network_guard(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        try:
            await browser.open(f"http://127.0.0.1:{site}/redirect-private")
        except DiscoveryError:
            pass
        observation = await browser.observe()
        assert "Join Example Inc" not in observation.text
        assert browser.proxy.blocked >= 1


@pytest.mark.browser
async def test_button_only_role_records_actual_destination_on_return(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/button-board")
        observation = await browser.observe()
        assert observation.links == []
        ref = re.search(r'button "Software Engineer" \[ref=(e\d+)', observation.snapshot)[1]
        await browser.act(action("click", "@" + ref), observation)
        detail = await browser.observe()
        assert detail.url.endswith("/role")
        await browser.act(action("back", ""), detail)
        collection = await browser.observe()
        assert collection.url.endswith("/button-board")
        assert any(link.url.endswith("/role") and link.text == "Software Engineer"
                   and link.provenance == "observed_click_navigation" for link in collection.links)


@pytest.mark.browser
async def test_generic_labels_have_bounded_single_job_context(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/cards")
        observation = await browser.observe()
        engineer = next(link for link in observation.links if link.url.endswith("/role"))
        assert engineer.text == "See role"
        assert "Software Engineer" in engineer.context
        assert "Data Analyst" not in engineer.context
        assert "Example Inc careers" in observation.identity_text
        await browser.open(f"http://127.0.0.1:{site}/mixed")
        observation = await browser.observe()
        assert all(not link.context for link in observation.links)


@pytest.mark.browser
async def test_menu_click_does_not_pollute_back_history(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/dynamic")
        observation = await browser.observe()
        ref = re.search(r'button "Company menu" \[ref=(e\d+)', observation.snapshot)[1]
        await browser.act(action("click", "@" + ref), observation)
        assert browser.history == []
        observation = await browser.observe()
        await browser.act(action("open", f"http://127.0.0.1:{site}/jobs"), observation)
        assert browser.history == [f"http://127.0.0.1:{site}/dynamic"]


async def test_http_upgrade_keeps_hostname_and_records_both_attempts(settings):
    session = BrowserSession(settings, "unit")
    calls = []
    async def command(*args):
        calls.append(args)
        if args[1].startswith("https:"):
            raise DiscoveryError("browser_action_failed", "fixture HTTPS failure")
    session.command = command
    await session.open("http://example.com/path?q=1")
    assert calls == [("open", "https://example.com/path?q=1"), ("open", "http://example.com/path?q=1")]
    assert len(session.navigation_attempts) == 2


async def test_https_input_falls_back_to_http_when_https_fails(settings):
    session = BrowserSession(settings, "unit")
    calls = []
    async def command(*args):
        calls.append(args)
        if args[1].startswith("https:"):
            raise DiscoveryError("browser_action_failed", "fixture HTTPS failure")
    session.command = command
    await session.open("https://example.com/path")
    assert calls == [("open", "https://example.com/path"), ("open", "http://example.com/path")]


@pytest.mark.browser
async def test_hidden_cross_host_board_link_is_surfaced(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/hidden-board")
        observation = await browser.observe()
        hidden = [link for link in observation.links if link.provenance == "hidden_dom"]
        assert any(link.url == "https://jobs.ashbyhq.com/example" for link in hidden)


def test_prefer_https_upgrades_external_but_leaves_loopback():
    from app.urls import prefer_https
    assert prefer_https("http://futrue.com/karriere/") == "https://futrue.com/karriere/"
    assert prefer_https("https://jobs.ashbyhq.com/x") == "https://jobs.ashbyhq.com/x"
    # Test fixtures and localhost must not be rewritten.
    assert prefer_https("http://127.0.0.1:8123/jobs") == "http://127.0.0.1:8123/jobs"
    assert prefer_https("http://localhost:8000/") == "http://localhost:8000/"


@pytest.mark.browser
async def test_search_fill_is_limited_to_observed_search_controls(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/search")
        observation = await browser.observe()
        button = re.search(r'button "Search" \[ref=(e\d+)', observation.snapshot)[1]
        query = action("fill", "@" + button)
        query.value = "Example Inc"
        with pytest.raises(DiscoveryError, match="Only observed search fields"):
            await browser.act(query, observation)
        ref = re.search(r'searchbox "Search companies" \[ref=(e\d+)', observation.snapshot)[1]
        query.target = "@" + ref
        await browser.act(query, observation)
        assert "q=Example" in (await browser.observe()).url


@pytest.mark.browser
async def test_detail_inspection_retains_application_handoff_links(settings, site):
    async with BrowserSession(settings, "test-" + uuid4().hex[:8], fixture_port=site) as browser:
        await browser.open(f"http://127.0.0.1:{site}/jobs")
        detail = await browser.check_detail(f"http://127.0.0.1:{site}/role-with-ats", "Software Engineer")
        assert any(link["text"] == "Apply Now" and link["url"] == "https://jobs.ashbyhq.com/example/role-123"
                   for link in detail["links"])
        assert (await browser.observe()).url.endswith("/jobs")
