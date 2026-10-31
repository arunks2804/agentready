"""Record the narrated AgentReady product demo (Playwright + Chromium, 1920x1080, British Piper voiceover).

Same method as the AgentHill demo: opening slides, then chapters narrated over real clicks in the running
app. Numbers spoken and captioned are read from the page at recording time. The app runs on its own port
with a temporary data folder, so it never touches a running copy.

    python scripts/record_demo.py              # -> docs/demo/agentready-demo.mp4
    python scripts/record_demo.py --no-video   # end-to-end UI test only (no audio)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo"
AUDIO = ROOT / "var" / "demo_audio"
PORT = 8019
BASE = f"http://127.0.0.1:{PORT}"

OVERLAY_JS = r"""
(() => {
  if (document.getElementById('demo-style')) return;
  const st = document.createElement('style'); st.id = 'demo-style';
  st.textContent = `
  html { overflow-x: hidden; }
  .page-head + .callout { display: none; }
  main, .top { zoom: 1.3; }
  .top { position: relative; z-index: 5; }
  #demo-cursor { position: fixed; z-index: 100000; left: 960px; top: 540px; width: 30px; height: 30px; pointer-events: none;
    transition: left .75s cubic-bezier(.4,.0,.2,1), top .75s cubic-bezier(.4,.0,.2,1); filter: drop-shadow(0 2px 3px rgba(0,0,0,.45)); }
  #demo-cursor.click::after { content: ''; position: absolute; left: -16px; top: -16px; width: 34px; height: 34px; border-radius: 50%;
    border: 3px solid #2a78d6; animation: ring .5s ease-out forwards; }
  @keyframes ring { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.6); opacity: 0 } }
  #demo-slide { position: fixed; inset: 0; z-index: 99990; display: flex; align-items: center; justify-content: center;
    background: radial-gradient(1200px 700px at 20% 10%, #123a6b 0%, #14161a 55%, #0c0d10 100%); color: #f8fafc;
    font-family: Inter, -apple-system, 'Segoe UI', sans-serif; opacity: 0; transition: opacity .6s ease; pointer-events: none; }
  #demo-slide.show { opacity: 1; }
  #demo-slide .inner { width: 1500px; }
  #demo-slide .kicker { color: #8dbdf3; font-size: 26px; letter-spacing: .14em; text-transform: uppercase; font-weight: 600; margin-bottom: 18px; }
  #demo-slide h1 { font-size: 76px; line-height: 1.08; margin: 0 0 26px; letter-spacing: -.02em; font-weight: 800; }
  #demo-slide h2 { font-size: 52px; line-height: 1.15; margin: 0 0 34px; font-weight: 750; }
  #demo-slide p.lead { font-size: 32px; color: #cbd5e1; line-height: 1.45; margin: 0; max-width: 1300px; }
  #demo-slide ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 20px; }
  #demo-slide li { font-size: 31px; color: #e2e8f0; line-height: 1.35; padding-left: 46px; position: relative; }
  #demo-slide li::before { content: ''; position: absolute; left: 0; top: 13px; width: 18px; height: 18px; border-radius: 5px; background: #3987e5; }
  #demo-slide li b { color: #fff; }
  #demo-slide .loop { display: flex; gap: 14px; margin-top: 40px; align-items: center; flex-wrap: wrap; }
  #demo-slide .loop span.step { background: rgba(57,135,229,.18); border: 1px solid rgba(141,189,243,.5); color: #e3effc; padding: 16px 24px;
    border-radius: 14px; font-size: 28px; font-weight: 650; }
  #demo-slide .loop span.arrow { color: #3987e5; font-size: 30px; }
  #demo-slide .note { margin-top: 44px; font-size: 26px; color: #fcd34d; border-left: 4px solid #f59e0b; padding-left: 18px; line-height: 1.4; }
  #demo-slide .chapter-num { font-size: 150px; font-weight: 800; color: #3987e5; line-height: 1; margin-bottom: 10px; }
  #demo-slide .tbl { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 29px; }
  #demo-slide .tbl th { text-align: left; color: #8dbdf3; font-size: 21px; text-transform: uppercase; letter-spacing: .08em; padding: 10px 16px; border-bottom: 1px solid rgba(141,189,243,.35); }
  #demo-slide .tbl td { padding: 14px 16px; border-bottom: 1px solid rgba(148,163,184,.18); color: #e2e8f0; }
  #demo-slide .tbl td:last-child b { color: #6ee7b7; }
  #demo-caption { pointer-events: none; position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 99995;
    background: rgba(17,24,39,.94); color: #fff; padding: 14px 28px; border-radius: 12px; font: 600 29px/1.3 Inter, -apple-system, sans-serif;
    max-width: 1500px; text-align: center; box-shadow: 0 8px 30px rgba(0,0,0,.35); }
  #demo-chip { pointer-events: none; position: fixed; right: 24px; top: 20px; z-index: 99995; background: #1c5cab; color: #fff;
    padding: 8px 16px; border-radius: 999px; font: 700 17px Inter, -apple-system, sans-serif; }
  main { transition: transform .85s cubic-bezier(.4,0,.2,1); will-change: transform; }
  `;
  document.head.appendChild(st);
  const c = document.createElement('div'); c.id = 'demo-cursor';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M3 2 L3 20 L8 15.5 L11.5 22.5 L14.5 21 L11 14 L18 14 Z" fill="#fff" stroke="#111827" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  const s = document.createElement('div'); s.id = 'demo-slide'; s.innerHTML = '<div class="inner"></div>';
  document.body.appendChild(s);
})()
"""


class Narrator:
    """Synthesises narration with Piper and tracks when each segment starts relative to the video."""

    def __init__(self, voice: str, enabled: bool, speed: float):
        self.enabled = enabled
        self.segments: list[tuple[float, Path]] = []
        self.t0 = time.monotonic()
        self.n = 0
        self.transcript: list[str] = []
        AUDIO.mkdir(parents=True, exist_ok=True)
        if enabled:
            from piper import PiperVoice, SynthesisConfig
            self.voice = PiperVoice.load(str(ROOT / "var" / "voices" / f"{voice}.onnx"))
            self.cfg = SynthesisConfig(length_scale=speed, noise_scale=0.6, noise_w_scale=0.75)
            for f in AUDIO.glob("seg_*.wav"):
                f.unlink()

    def synth(self, text: str) -> tuple[Path | None, float]:
        self.transcript.append(text)
        (AUDIO / "transcript.txt").write_text("\n\n".join(f"[{i:02d}] {t}" for i, t in enumerate(self.transcript, 1)) + "\n")
        if not self.enabled:
            return None, min(1.0, 0.02 * len(text))
        self.n += 1
        path = AUDIO / f"seg_{self.n:02d}.wav"
        with wave.open(str(path), "wb") as w:
            self.voice.synthesize_wav(text, w, syn_config=self.cfg)
        with wave.open(str(path), "rb") as r:
            return path, r.getnframes() / r.getframerate()

    def start(self, path: Path | None) -> float:
        now = time.monotonic()
        if path is not None:
            self.segments.append((now - self.t0, path))
        return now


BANNED_WORDS = ("different", "readiness gap", "rule-based", "probe", "finding")


def caption_chunks(text: str) -> list[str]:
    """One sentence at a time, split at commas when a sentence is too long for one caption."""
    chunks = []
    for sentence in re.findall(r"[^.?!:]+[.?!:]*", text):
        sentence = sentence.strip()
        while len(sentence) > 90 and ", " in sentence[30:]:
            cut = sentence.rfind(", ", 30, 90)
            cut = cut if cut > 0 else sentence.find(", ", 30)
            chunks.append(sentence[:cut + 1])
            sentence = sentence[cut + 2:]
        if sentence:
            chunks.append(sentence)
    return chunks


class Scene:
    """Audio and full captions start on enter. Move to the right screen before entering."""

    def __init__(self, demo: "Demo", text: str, pad: float = 0.3):
        self.demo, self.text, self.pad = demo, text, pad
        lowered = text.lower()
        for word in BANNED_WORDS:
            if word in lowered:
                raise ValueError(f"Narration uses '{word}': {text}")

    def __enter__(self):
        path, self.dur = self.demo.narrator.synth(self.text)
        self.demo.schedule_captions(self.text, self.dur)
        self.started = self.demo.narrator.start(path)
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            remaining = self.dur + self.pad - (time.monotonic() - self.started)
            if remaining > 0:
                self.demo.page.wait_for_timeout(int(remaining * 1000))
            self.demo.caption(None)
        return False


class Demo:
    def __init__(self, page: Page, narrator: Narrator):
        self.page, self.narrator = page, narrator

    def install(self) -> None:
        self.page.evaluate(OVERLAY_JS)

    def caption(self, text: str | None) -> None:
        self.page.evaluate("""t => { (window.__cues || []).forEach(clearTimeout); let el = document.getElementById('demo-caption');
            if (!t) { el && el.remove(); return; }
            if (!el) { el = document.createElement('div'); el.id = 'demo-caption'; document.body.appendChild(el); }
            el.textContent = t; }""", text)

    def schedule_captions(self, text: str, duration: float) -> None:
        chunks = caption_chunks(text)
        total = sum(len(c) for c in chunks)
        at, cues = 0.0, []
        for chunk in chunks:
            cues.append([chunk, int(at * 1000)])
            at += duration * len(chunk) / total
        self.page.evaluate("""cues => { (window.__cues || []).forEach(clearTimeout);
            const show = t => { let el = document.getElementById('demo-caption');
                if (!el) { el = document.createElement('div'); el.id = 'demo-caption'; document.body.appendChild(el); }
                el.textContent = t; };
            window.__cues = cues.map(([t, ms]) => setTimeout(() => show(t), ms)); }""", cues)

    def chip(self, text: str | None) -> None:
        self.page.evaluate("""t => { let el = document.getElementById('demo-chip');
            if (!t) { el && el.remove(); return; }
            if (!el) { el = document.createElement('div'); el.id = 'demo-chip'; document.body.appendChild(el); }
            el.textContent = t; }""", text)

    def slide(self, html: str | None) -> None:
        if html is None:
            self.page.evaluate("() => document.getElementById('demo-slide').classList.remove('show')")
            self.page.wait_for_timeout(650)
            return
        self.page.evaluate("""h => { const s = document.getElementById('demo-slide'); s.querySelector('.inner').innerHTML = h;
            s.classList.add('show'); }""", html)
        self.page.wait_for_timeout(650)

    def _move(self, x: float, y: float) -> None:
        self.page.evaluate("([x, y]) => { const c = document.getElementById('demo-cursor'); c.style.left = x + 'px'; c.style.top = y + 'px'; }", [x, y])

    def point(self, target: Locator | str, settle: int = 650) -> Locator:
        loc = self.page.locator(target).first if isinstance(target, str) else target
        loc.scroll_into_view_if_needed()
        self.page.wait_for_timeout(250)
        box = loc.bounding_box()
        if box:
            self._move(box["x"] + min(box["width"] * 0.5, 60), box["y"] + box["height"] * 0.55)
        self.page.wait_for_timeout(settle)
        return loc

    def click(self, target: Locator | str, settle: int = 650) -> None:
        loc = self.point(target, settle)
        self.page.evaluate("() => { const c = document.getElementById('demo-cursor'); c.classList.remove('click'); void c.offsetWidth; c.classList.add('click'); }")
        loc.click()
        self.page.wait_for_timeout(350)

    def zoom(self, target: Locator | str, scale: float = 1.4) -> None:
        loc = self.page.locator(target).first if isinstance(target, str) else target
        self.unzoom(fast=True)
        loc.evaluate("el => el.scrollIntoView({block: 'center'})")
        self.page.wait_for_timeout(300)
        box = loc.bounding_box()
        if not box:
            return
        self._move(box["x"] + min(box["width"] * 0.5, 80), box["y"] + min(box["height"] * 0.5, 40))
        self.page.wait_for_timeout(600)
        self.page.evaluate("""([x, y, s]) => { const m = document.querySelector('main'); const b = m.getBoundingClientRect();
            const z = parseFloat(getComputedStyle(m).zoom) || 1;
            m.style.transformOrigin = ((x - b.left) / z) + 'px ' + ((y - b.top) / z) + 'px'; m.style.transform = 'scale(' + s + ')'; }""",
                           [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, scale])
        self.page.wait_for_timeout(950)

    def unzoom(self, fast: bool = False) -> None:
        was = self.page.evaluate("() => { const m = document.querySelector('main'); const z = m.style.transform && m.style.transform !== 'none'; m.style.transform = 'none'; return z; }")
        if was:
            self.page.wait_for_timeout(300 if fast else 900)

    def go(self, hash_: str, heading: str) -> None:
        """Move between pages through the app's own links."""
        self.unzoom(fast=True)
        link = self.page.locator(f'a[href="{hash_}"]').first
        self.click(link, settle=400)
        self.page.wait_for_selector(f"h1:has-text('{heading}')")
        self.page.evaluate("() => scrollTo(0, 0)")
        self.page.wait_for_timeout(350)

    def chapter(self, num: int, title: str, subtitle: str) -> None:
        self.caption(None)
        self.chip(None)
        self.unzoom(fast=True)
        with Scene(self, f"Part {num}. {title}.", pad=0.4):
            self.slide(f'<div class="chapter-num">{num}</div><h2>{title}</h2><p class="lead">{subtitle}</p>')
        self.slide(None)
        self.chip(f"{num} · {title}")

    def fix_panel(self, fix_id: str) -> None:
        """Bring the recommended fix on screen before the narration starts."""
        self.unzoom(fast=True)
        self.page.locator(f'[data-fix="{fix_id}"]').evaluate("el => el.scrollIntoView({block: 'center'})")
        self.page.wait_for_timeout(500)

    def fix_and_reassess(self, fix_id: str) -> None:
        self.fix_and_reassess_apply(fix_id)
        self.reassess()

    def fix_and_reassess_apply(self, fix_id: str) -> None:
        self.click(f'[data-fix="{fix_id}"]', settle=450)
        self.page.wait_for_selector(f'[data-fix="{fix_id}"]:disabled')

    def reassess(self) -> None:
        self.page.locator("#assess").evaluate("el => el.scrollIntoView({block: 'center'})")
        self.page.wait_for_timeout(300)
        runs = self.page.locator("details table tbody tr").count()
        self.click("#assess", settle=450)
        self.page.wait_for_function("n => document.querySelectorAll('details table tbody tr').length > n", arg=runs)
        self.page.wait_for_timeout(300)

    def score(self) -> int:
        return int(re.search(r"Score (\d+)", self.page.locator(".page-head .sub").inner_text()).group(1))

    def task(self) -> str:
        return self.page.locator(".card .status").first.inner_text().strip()

    def finding(self, title: str) -> Locator:
        return self.page.locator(".finding", has_text=title).first

    def finding_status(self, title: str) -> str:
        return self.finding(title).locator(".finding-head .chip").inner_text().strip()

    def overview(self) -> dict:
        text = self.page.locator(".hero .card").first.inner_text()
        done, total = re.search(r"(\d+) of (\d+) tasks", text).groups()
        rate = self.page.locator(".bignum").inner_text().strip()
        score = self.page.locator(".hero .card").nth(1).locator(".tile-num").inner_text().strip()
        return {"done": int(done), "total": int(total), "rate": rate, "score": score}


NUM = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def words(n) -> str:
    n = int(n)
    return NUM[n] if 0 <= n < len(NUM) else str(n)


def expect(condition: bool, message: str) -> None:
    """Stop the recording rather than narrate a story the app did not produce."""
    if not condition:
        raise RuntimeError(f"Demo story did not hold: {message}")


def run(args) -> Path | None:
    narrator = Narrator(args.voice, enabled=not (args.no_video or args.silent), speed=args.speed)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        options: dict = {"viewport": {"width": 1920, "height": 1080}, "color_scheme": "light"}
        if not args.no_video:
            options |= {"record_video_dir": str(AUDIO / "video"), "record_video_size": {"width": 1920, "height": 1080}}
        ctx = browser.new_context(**options)
        page = ctx.new_page()
        narrator.t0 = time.monotonic()  # the screen recording starts with the page
        page.set_default_timeout(20_000)
        page.goto(BASE)
        page.wait_for_selector("h1")
        d = Demo(page, narrator)
        d.install()

        # ================================================================== opening
        d.slide('<div class="kicker">Product demo</div><h1>AgentReady</h1>'
                '<p class="lead">Can an AI coding assistant get its work done here? Find what stops it, get it fixed, and prove the fix worked.</p>')
        with Scene(d, "This is AgentReady. It finds what stops an AI coding assistant from finishing its work, "
                      "sends the problem to the team that owns the code, and tries the work again to prove the fix worked.", pad=0.6):
            pass
        d.slide('<div class="kicker">Why it matters</div><h2>Skilled assistants still get stuck</h2>'
                '<ul><li>Companies now give <b>real engineering work</b> to AI coding assistants</li>'
                '<li>Think of a skilled new starter with <b>no building pass and no instructions</b></li>'
                '<li>If they get stuck, the fault <b>may not be theirs</b></li></ul>')
        with Scene(d, "Companies now give real engineering work to AI coding assistants. But think of a skilled new starter with no building pass and no instructions. "
                      "If they get stuck, the fault may not be theirs. AI coding assistants get stuck for the same reason.", pad=0.5):
            pass
        d.slide('<div class="kicker">How it works</div><h2>Five simple steps</h2>'
                '<div class="loop"><span class="step">Try the task</span><span class="arrow">→</span><span class="step">Find what stopped it</span>'
                '<span class="arrow">→</span><span class="step">Tell the owning team</span><span class="arrow">→</span><span class="step">Team fixes it</span>'
                '<span class="arrow">→</span><span class="step">Try again</span></div>')
        with Scene(d, "It works in five steps. Try the task. Find what stopped it. Tell the team that owns the code. The team fixes it. Then try the task again.", pad=0.5):
            pass
        d.slide('<div class="kicker">Before we start</div><h2>About this demo</h2>'
                '<ul><li>The three services are <b>made up</b>, and two have problems added on purpose</li>'
                '<li>A <b>script</b> does the work here, not an AI</li>'
                '<li>A button stands in for the <b>team\'s fix</b></li></ul>'
                '<div class="note">This shows how the method works. It does not show how much real AI assistants improve.</div>')
        with Scene(d, "A quick note about this demo. The three services are made up, and two have problems added on purpose. A script does the work here, not an AI, "
                      "and a button stands in for the team's fix. So this shows how the method works. It does not show how much real AI assistants improve.", pad=0.5):
            pass
        d.slide(None)

        # ================================================================== 1. where we start
        d.chapter(1, "Where we start", "Three services, three tasks")
        base = d.overview()
        expect(base["done"] == 1 and base["total"] == 3, "baseline should be 1 of 3")
        d.zoom(page.locator(".hero .card").first, 1.3)
        with Scene(d, f"We have three services, and each has one task to finish. Right now, {words(base['done'])} of the {words(base['total'])} tasks finishes."):
            pass
        billing_score = int(page.locator("section.card").first.locator("tbody tr").nth(0).locator("td").nth(4).inner_text())
        d.zoom(page.locator("section.card tbody tr").first, 1.35)
        with Scene(d, f"Billing service is blocked, even with a score of {billing_score} out of a hundred. Let's find out what stopped it."):
            pass

        # ================================================================== 2. what stopped the task
        d.chapter(2, "What stopped the task", "One missing file")
        d.go("#/service/billing-service", "billing-service")
        d.zoom(page.locator(".card", has_text="Latest task").locator("p.muted").first, 1.6)
        with Scene(d, "Here is the task: fix a bug that makes some bills one cent too low."):
            pass
        d.zoom(".steps", 1.15)
        with Scene(d, "The script goes through the task step by step. It finds the service, finds the code, and makes the fix. Then it runs the tests, to check the fix worked."):
            pass
        d.zoom(".steps li.blocked", 1.35)
        with Scene(d, "This is where it stops. The tests need a file of tax rates, and nothing says where that file is. "
                      "The error on screen is the computer saying that a setting is missing. Without it, nobody can run the tests, whether a person or an AI."):
            pass
        target = "Required settings work"
        d.zoom(d.finding(target), 1.2)
        with Scene(d, "AgentReady records this as a blocker. It shows the evidence and gives one recommended fix: add a working sample settings file. It sends this to the billing team."):
            pass

        # ================================================================== 3. the team fixes it
        d.chapter(3, "The team fixes it", "One recommended fix, then try again")
        fix = "3-env-working-config"
        d.fix_panel(fix)
        with Scene(d, "The billing team does exactly what was recommended. They add the working sample settings file."):
            d.fix_and_reassess_apply(fix)
        with Scene(d, "Now AgentReady tries the same task again."):
            d.reassess()
        expect(d.task() == "Completed", "the recommended fix should complete the task")
        d.zoom(page.locator(".card", has_text="Latest task").first, 1.05)
        with Scene(d, "This time, every step passes and the task finishes. The blocker is closed because the retry proved it, not because someone said so."):
            pass

        # ================================================================== 4. a view for each team
        d.chapter(4, "A view for each team", "Who sees what")
        d.go("#/remediation", "Remediation")
        d.zoom(page.locator("section.card").first, 1.1)
        with Scene(d, "Each team sees its own list of work, with the most serious problems first."):
            pass
        d.go("#/platform", "Platform insights")
        d.zoom(page.locator("section.card").first, 1.05)
        with Scene(d, "The team that runs the AI assistants sees which problems come up most, so a shared problem can be fixed once."):
            pass

        # ================================================================== 5. three blockers
        d.chapter(5, "A service with three blockers", "One fix at a time")
        d.go("#/", "Can agents finish work")
        d.go("#/service/notifications-service", "notifications-service")
        d.zoom(".steps", 1.3)
        with Scene(d, "Notifications service is blocked at the very first step. It isn't in the service catalog, so it can't be found."):
            pass
        rounds = [
            ("1-catalog-entry", "The team adds the service to the catalog, and AgentReady tries again.",
             "The task gets further. Now it stops because there is no API contract, which describes how other systems talk to this service."),
            ("2-openapi", "The team publishes the API contract, and AgentReady tries again.",
             "The task gets further again. Now it stops because nobody wrote down how to run the tests."),
        ]
        for fix_id, action, outcome in rounds:
            d.fix_panel(fix_id)
            with Scene(d, action):
                d.fix_and_reassess(fix_id)
            d.zoom(".steps li.blocked", 1.35)
            with Scene(d, outcome):
                pass
        d.fix_panel("3-test-command")
        with Scene(d, "The team documents the test command, and AgentReady tries again."):
            d.fix_and_reassess("3-test-command")
        low = d.score()
        expect(d.task() == "Completed", "notifications should complete")
        d.zoom(page.locator(".card", has_text="Latest task").first, 1.05)
        with Scene(d, f"The task finishes. Its score is only {low}, yet billing was blocked at {billing_score}. A score alone can't tell you whether the work will get done. Only trying the task can."):
            pass

        # ================================================================== 6. scripts and AI
        d.chapter(6, "Scripts first, AI where it counts", "Keeping cost down")
        d.go("#/automation", "Scripts first")
        counts = page.locator("#counts .tile-num")
        assessments, task_runs, ai_calls = [counts.nth(i).inner_text().strip() for i in range(3)]
        expect(ai_calls == "0", "this prototype makes no AI calls")
        d.zoom("#counts", 1.25)
        with Scene(d, f"Scripts did everything you just saw: {words(assessments)} assessments and {words(task_runs)} task runs, with no AI used at all."):
            pass
        d.zoom("#script-jobs", 1.2)
        with Scene(d, "Scripts handle the facts. Does a file exist? Do the tests pass? They are fast and cheap, so they can run on every change."):
            pass
        d.zoom("#ai-jobs", 1.2)
        with Scene(d, "AI is for what a script can't do, such as trying a real task with no known answer. These AI roles are planned, and not built yet."):
            pass
        d.zoom("#cost-note", 1.25)
        with Scene(d, "That keeps cost down. Scripts check everything, and AI runs only on a small sample of tasks. The saving hasn't been measured yet, because no real AI assistant has been run."):
            pass
        d.unzoom()
        d.chip(None)
        d.go("#/", "Can agents finish work")
        final = d.overview()
        expect(final["done"] == 3, "all three tasks should complete")

        # ================================================================== close
        d.slide('<div class="kicker">In summary</div><h2>Find what stops the work, fix it, and prove it</h2>'
                '<table class="tbl"><tr><th></th><th>Start</th><th>After the fixes</th></tr>'
                f'<tr><td>Tasks finished</td><td>{base["done"]} of {base["total"]}</td><td><b>{final["done"]} of {final["total"]}</b></td></tr></table>'
                '<div class="note">Made-up sample services and a script, not a real AI assistant. Testing with real AI assistants is the next step. '
                'Voiceover is AI-generated (Piper, en-GB). All app footage is a live recording.</div>')
        with Scene(d, f"In summary: tasks finished went from {words(base['done'])} of {words(base['total'])} to {words(final['done'])} of {words(final['total'])} on these sample services. "
                      "The next step is to test this with real AI assistants. "
                      "AgentReady: don't just ask whether the AI is ready for the work. Ask whether the work is ready for the AI.", pad=1.2):
            pass
        (AUDIO / "timings.txt").write_text("\n".join(f"{offset:.2f} {path}" for offset, path in narrator.segments) + "\n")
        raw = page.video.path() if not args.no_video else None
        ctx.close()
        browser.close()
    if args.no_video:
        return None
    return mux(Path(raw), narrator.segments, OUT / "agentready-demo.mp4")


def mux(video: Path, segments: list[tuple[float, Path]], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video)]
    for _, path in segments:
        cmd += ["-i", str(path)]
    filters, labels = [], []
    for i, (offset, _) in enumerate(segments, start=1):
        ms = max(0, int(offset * 1000))
        filters.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    cmd += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    shutil.rmtree(video.parent, ignore_errors=True)
    return out


def start_server():
    env = {**os.environ, "AGENTREADY_VAR": tempfile.mkdtemp(prefix="agentready-demo-")}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                              cwd=ROOT, env=env)
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/api/dimensions", timeout=1)
            return server
        except OSError:
            time.sleep(0.2)
    server.terminate()
    raise RuntimeError("App did not start")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-video", action="store_true", help="run the flow as an end-to-end UI test only")
    ap.add_argument("--silent", action="store_true", help="record video without narration")
    ap.add_argument("--voice", default="en_GB-cori-high")
    ap.add_argument("--speed", type=float, default=0.95, help="Piper length_scale (>1 is slower)")
    a = ap.parse_args()
    started = time.time()
    app_server = start_server()
    try:
        result = run(a)
    finally:
        app_server.terminate()
    print(f"Demo finished in {time.time() - started:.0f}s" + (f"; video: {result}" if result else ""))
