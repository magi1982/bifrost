"""GUI self-check against the demo server: overflow, horizontal scroll, JS errors, clickable buttons.

python tools/gui_check.py [base_url] [out_dir]
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="bifrost-gui-"))
OUT.mkdir(parents=True, exist_ok=True)
TABS = ["status", "people", "house", "recog", "dev", "balance", "setup"]

OVERFLOW_JS = """() => {
  const bad = [];
  for (const el of document.querySelectorAll('main *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('svg')) continue;
    if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 2 && el.clientWidth < 120) {
      bad.push('squeezed ' + (el.className || el.tagName) + ': ' + (el.textContent || '').trim().slice(0, 40)); continue; }
    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll' || cs.textOverflow === 'ellipsis') continue;
    if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && !['INPUT','SELECT','TEXTAREA'].includes(el.tagName)) {
      const p = el.parentElement && getComputedStyle(el.parentElement);
      if (p && (p.overflowX === 'auto' || p.textOverflow === 'ellipsis')) continue;
      bad.push((el.className || el.tagName) + ': ' + (el.textContent || '').trim().slice(0, 40));
    }
  }
  for (const g of document.querySelectorAll('main .grow')) if (g.clientWidth > 0 && g.clientWidth < 140) bad.push('narrow column: ' + (g.textContent || '').trim().slice(0, 30));
  return {bad: bad.slice(0, 12), page: document.documentElement.scrollWidth - window.innerWidth};
}"""


ENGLISH_JS = r"""() => {
  const words = 'the|is|are|and|with|not|of|for|from|only|never|when|while|Home|Away|Asleep|Leaving|Arriving|Used|Saved'
    + '|Search|Last|Activity|entries|Entities|Learning|Patterns|Shadow|Guest|confidence|Why';
  const rx = new RegExp('\\b(' + words + ')\\b');
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    const p = n.parentElement;
    if (!p || p.closest('script,style,.tech,.eid,code') || getComputedStyle(p).display === 'none') continue;
    const t = n.nodeValue.trim().replace(/Home[- ]Assistant/g, '');
    if (t.length < 3 || /^[a-z_]+\.[a-z0-9_]+/.test(t)) continue;
    if (rx.test(t)) out.push(t.slice(0, 80));
  }
  return out;
}"""


def run() -> int:
    problems = []
    with sync_playwright() as p:
        chrome = os.environ.get("BIFROST_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
        b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        for scheme, w, h in (("light", 1200, 900), ("dark", 1200, 900), ("light", 390, 844), ("dark", 390, 844)):
            ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, locale="de-CH")
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            pg.on("dialog", lambda d: d.dismiss())
            pg.goto(BASE)
            pg.wait_for_timeout(800)
            for tab in TABS:
                pg.click(f'#tabs button[data-v="{tab}"]')
                pg.wait_for_timeout(500)
                res = pg.evaluate(OVERFLOW_JS)
                tag = f"{tab}-{scheme}-{w}"
                if res["bad"] or res["page"] > 2:
                    problems.append({"where": tag, **res})
                pg.screenshot(path=str(OUT / f"{tag}.png"), full_page=True)
            # buttons: click every visible, non-destructive button on the interactive tabs
            for tab in ("recog", "people", "dev", "status", "house"):
                pg.click(f'#tabs button[data-v="{tab}"]')
                pg.wait_for_timeout(400)
                n = pg.evaluate("() => document.querySelectorAll('main button:not([data-pdel]):not([data-exdel]):not([data-ans]):not([data-wrong])').length")
                for i in range(min(n, 25)):
                    btns = pg.query_selector_all("main button:not([data-pdel]):not([data-exdel]):not([data-ans]):not([data-wrong])")
                    if i >= len(btns) or not btns[i].is_visible():
                        continue
                    try:
                        btns[i].click(timeout=1500)
                        pg.wait_for_timeout(150)
                    except Exception as e:  # noqa: BLE001
                        problems.append({"where": f"click {tab}#{i}-{scheme}-{w}", "error": str(e)[:120]})
                    if pg.evaluate("() => document.querySelector('#tabs button.active')?.dataset.v") != tab:
                        pg.click(f'#tabs button[data-v="{tab}"]')
                        pg.wait_for_timeout(300)
            if scheme == "light" and w > 600:
                leftovers = []
                for tab in TABS:
                    pg.click(f'#tabs button[data-v="{tab}"]')
                    pg.wait_for_timeout(500)
                    leftovers += [f"{tab}: {x}" for x in pg.evaluate(ENGLISH_JS)]
                if leftovers:
                    problems.append({"where": "english-in-german", "texts": sorted(set(leftovers))[:60]})
            if errs:
                problems.append({"where": f"js-{scheme}-{w}", "errors": errs[:5]})
            ctx.close()
        b.close()
    print(json.dumps(problems, indent=1, ensure_ascii=False))
    return len(problems)


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
