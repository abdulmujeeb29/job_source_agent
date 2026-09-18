"""Generic rendered-DOM observations; no company or ATS-specific selectors."""

LINKS_JS = """elements => elements
  .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden')
  .filter(e => /^https?:/.test(e.href))
  .slice(0,500)
  .map(e => {
    let context = '';
    let parent = e.parentElement;
    // A bounded card/row with only this destination can associate a title with
    // generic labels such as See role. Never use the whole page or a mixed list.
    for (let depth=0; parent && depth<5; depth++, parent=parent.parentElement) {
      if (['BODY','MAIN','HTML','NAV','HEADER','FOOTER'].includes(parent.tagName)) break;
      const text = (parent.innerText || '').trim();
      const urls = new Set(Array.from(parent.querySelectorAll('a[href]'))
        .filter(a => a.getClientRects().length && /^https?:/.test(a.href)).map(a => a.href));
      if (text.length > 1200 || urls.size > 1) break;
      if (urls.size === 1 && urls.has(e.href) && text !== (e.innerText || '').trim()) context = text;
    }
    return {text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0,500),
            url:e.href, context};
  })"""

# Anchors present in the DOM but not currently laid out (collapsed menu/accordion,
# off-screen slider). Restricted to cross-host destinations, which is where hidden
# careers/ATS handoffs live (e.g. jobs.ashbyhq.com, *.personio.de) — not the many
# same-origin megamenu/footer links. Generic: no company- or ATS-specific selectors.
HIDDEN_LINKS_JS = """() => Array.from(document.querySelectorAll('a[href]'))
  .filter(e => /^https?:/.test(e.href) && e.getClientRects().length === 0)
  .filter(e => { try { return new URL(e.href).hostname !== location.hostname; } catch (err) { return false; } })
  .slice(0,60)
  .map(e => ({text:(e.innerText || e.getAttribute('aria-label') || '').trim().slice(0,200), url:e.href}))"""

IDENTITY_JS = """() => Array.from(document.querySelectorAll('img[alt], svg title, a[aria-label]'))
  .filter(e => (e.getClientRects().length || e.parentElement?.getClientRects().length)
    && getComputedStyle(e).visibility !== 'hidden')
  .map(e => e.getAttribute('alt') || e.getAttribute('aria-label') || e.textContent)
  .filter(Boolean).slice(0,50).join('\\n').slice(0,3000)"""
