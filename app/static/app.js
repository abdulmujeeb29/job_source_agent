const $ = id => document.getElementById(id);
const terminal = new Set(['succeeded','failed','no_openings','cancelled','interrupted']);
let active = null, timer = null, lastEventCount = -1;
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function link(url, label) {
  try { if (!['http:', 'https:'].includes(new URL(url, location.origin).protocol)) return escape(label); }
  catch { return escape(label); }
  return `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label || url)}</a>`;
}
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed. Check the URL and try again.');
  return body;
}
function render(run) {
  $('run').hidden = false;
  $('status').textContent = run.status === 'running' ? run.stage : run.status.replaceAll('_',' ');
  $('status').className = `badge ${run.status}`;
  $('cancel').hidden = terminal.has(run.status);
  $('submit').disabled = !terminal.has(run.status);
  $('download').href = `/api/runs/${run.run_id}`;
  let html = `<h3>${escape(run.company_name || (run.status === 'queued' ? 'Waiting for the browser…' : 'Finding the company…'))}</h3>`;
  for (const [label, url] of [['Final jobs page',run.jobs_url],['Company site',run.company_website],['Careers entry page',run.careers_url],['LinkedIn job',run.normalized_input_url]]) {
    if (url) html += `<div class="result-row"><span>${label}</span>${link(url)}</div>`;
  }
  if (run.jobs_url && run.careers_url && run.jobs_url !== run.careers_url) html += '<p>The careers entry page leads to the final jobs page shown above.</p>';
  if (run.failure_reason) html += `<p class="notice">${escape(run.failure_reason)}<br><code>${escape(run.failure_code)}</code></p>`;
  if (run.ats_resolution?.status === 'unverified') html += `<p class="notice">Company-hosted listings verified; the upstream ATS board was not verified. ${escape(run.ats_resolution.reason)}</p>`;
  if (run.status === 'no_openings') html += '<p>The company board explicitly reports no open roles. This is not counted as a verified-listings success.</p>';
  if (run.jobs_url) html += `<p>${link(run.jobs_url, run.status === 'succeeded' ? 'Open verified jobs board ↗' : 'Open company board ↗')}</p>`;
  for (const item of run.verification.listings || []) html += `<div class="listing">↳ ${link(item.url,item.title)}</div>`;
  if (run.verification.collection_evidence) html += `<p>“${escape(run.verification.collection_evidence)}”</p>`;
  if (run.duration_ms) html += `<p class="meta">${(run.duration_ms/1000).toFixed(1)}s · ${run.model_usage.requests || 0} model requests · ${run.attempt_counts.steps || 0} steps</p>`;
  $('result').innerHTML = html;
  if (lastEventCount !== run.navigation_events.length) {
    const open = new Set([...$('timeline').querySelectorAll('details[open]')].map(el => el.dataset.event));
    $('timeline').innerHTML = run.navigation_events.map(event => `<li><p class="event-title">${escape(event.message)}</p><div class="meta">${escape(new Date(event.at).toLocaleTimeString())} · ${escape(event.stage)}${event.url ? ' · '+link(event.url) : ''}</div>${event.screenshot ? `<details data-event="${event.id}" ${open.has(String(event.id)) ? 'open' : ''}><summary>View browser evidence</summary><img loading="lazy" src="${escape(event.screenshot)}" alt="Browser screenshot for step ${event.step}"></details>` : ''}</li>`).join('');
    lastEventCount = run.navigation_events.length;
  }
}
async function poll() {
  if (!active) return;
  try {
    const run = await api(`/api/runs/${active}`);
    render(run);
    if (!terminal.has(run.status)) timer = setTimeout(poll, 1500);
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; timer = setTimeout(poll, 5000); }
}
$('search').addEventListener('submit', async event => {
  event.preventDefault(); $('error').hidden = true; $('submit').disabled = true;
  clearTimeout(timer);
  try {
    const run = await api('/api/runs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('url').value})});
    active = run.run_id; lastEventCount = -1; history.replaceState(null,'',`?run=${active}`);
    render(run); poll();
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; $('submit').disabled = false; }
});
$('cancel').addEventListener('click', async () => {
  try { await api(`/api/runs/${active}/cancel`, {method:'POST'}); }
  catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
});
active = new URLSearchParams(location.search).get('run');
if (active && /^[a-f0-9]{32}$/.test(active)) poll();
api('/api/config').then(config => {
  if (!config.configured) { $('error').textContent = `Setup required: ${config.missing.join(', ')}`; $('error').hidden = false; }
}).catch(() => {});
