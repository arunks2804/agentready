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
    background: rgba(17,24,39,.92); color: #fff; padding: 12px 24px; border-radius: 12px; font: 600 24px Inter, -apple-system, sans-serif;
    max-width: 1450px; text-align: center; box-shadow: 0 8px 30px rgba(0,0,0,.35); }
  #demo-chip { pointer-events: none; position: fixed; right: 24px; bottom: 30px; z-index: 99995; background: #1c5cab; color: #fff;
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


class Scene:
    """Audio starts on enter; exit waits until narration has finished, plus a short pause."""

    def __init__(self, demo: "Demo", text: str, caption: str | None = None, pad: float = 0.3):
        self.demo, self.text, self.caption, self.pad = demo, text, caption, pad

    def __enter__(self):
        path, self.dur = self.demo.narrator.synth(self.text)
        if self.caption is not None:
            self.demo.caption(self.caption)
        self.started = self.demo.narrator.start(path)
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            remaining = self.dur + self.pad - (time.monotonic() - self.started)
            if remaining > 0:
                self.demo.page.wait_for_timeout(int(remaining * 1000))
        return False


class Demo:
    def __init__(self, page: Page, narrator: Narrator):
        self.page, self.narrator = page, narrator

    def install(self) -> None:
        self.page.evaluate(OVERLAY_JS)

    def caption(self, text: str | None) -> None:
        self.page.evaluate("""t => { let el = document.getElementById('demo-caption');
            if (!t) { el && el.remove(); return; }
            if (!el) { el = document.createElement('div'); el.id = 'demo-caption'; document.body.appendChild(el); }
            el.textContent = t; }""", text)

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
        self.unzoom(fast=True)
        with Scene(self, f"Part {num}. {title}.", pad=0.4):
            self.slide(f'<div class="chapter-num">{num}</div><h2>{title}</h2><p class="lead">{subtitle}</p>')
        self.slide(None)
        self.chip(f"{num} · {title}")

    def fix_and_reassess(self, fix_id: str) -> None:
        self.click(f'[data-fix="{fix_id}"]', settle=450)
        self.page.wait_for_selector(f'[data-fix="{fix_id}"]:disabled')
        self.page.evaluate("() => scrollTo(0, 0)")
        runs = self.page.locator("details table tbody tr").count()
        self.click("#assess", settle=450)
        self.page.wait_for_function("n => document.querySelectorAll('details table tbody tr').length > n", arg=runs)
        self.page.evaluate("() => scrollTo(0, 0)")
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
        page.set_default_timeout(20_000)
        page.goto(BASE)
        page.wait_for_selector("h1")
        d = Demo(page, narrator)
        d.install()
        narrator.t0 = time.monotonic()

        # ================================================================== opening
        d.slide('<div class="kicker">Product demo</div><h1>AgentReady</h1>'
                '<p class="lead">A first-day test for your codebase: can an AI coding assistant actually get its work done here?</p>')
        with Scene(d, "This is AgentReady. Think of it as a first-day test for your codebase: "
                      "can an AI coding assistant actually get its work done here?", pad=0.6):
            pass
        d.slide('<div class="kicker">Why it matters</div><h2>Capable assistants still get stuck</h2>'
                '<ul><li>Companies now give <b>AI coding assistants</b> real engineering work</li>'
                '<li>Imagine a skilled new starter with <b>no building pass, no floor plan and no instructions</b></li>'
                '<li>When they fail, the fault is <b>not always theirs</b></li></ul>')
        with Scene(d, "Companies now give AI coding assistants real engineering work. But imagine a skilled new starter who arrives "
                      "with no building pass, no floor plan and no instructions. If they fail, the fault may not be theirs. "
                      "AI assistants often fail for the same reason.", pad=0.5):
            pass
        d.slide('<div class="kicker">How it works</div><h2>Try the job, find the obstacle, prove the fix</h2>'
                '<div class="loop"><span class="step">Assess</span><span class="arrow">→</span><span class="step">Try a real task</span>'
                '<span class="arrow">→</span><span class="step">Find the blocker</span><span class="arrow">→</span><span class="step">Assign the owner</span>'
                '<span class="arrow">→</span><span class="step">Fix</span><span class="arrow">→</span><span class="step">Try again</span></div>')
        with Scene(d, "AgentReady checks a service, then tries a real task. It finds the first thing that stops the work, and assigns it to "
                      "the team that owns that service. After the fix, it tries the same task again. Only a successful retry counts.", pad=0.5):
            pass
        d.slide('<div class="kicker">Before we start</div><h2>What is real and what is not</h2>'
                '<ul><li>The three services are <b>fictional</b>, and two are deliberately flawed</li>'
                '<li>Tasks are run by a <b>scripted test, not an AI</b>. The test results are real</li>'
                '<li>The fixes are <b>simulated team changes</b>, and agent logs marked Simulated are examples</li></ul>'
                '<div class="note">No real AI assistant has been tested yet. This demo shows how the method works, not how much real assistants improve.</div>')
        with Scene(d, "First, a clear disclosure. These three services are fictional, and two are deliberately flawed. Tasks are run by a scripted test, "
                      "not an AI, though the test results are real. So this shows how the method works, not how much real assistants improve.", pad=0.5):
            pass
        d.slide(None)

        # ================================================================== 1. where we start
        d.chapter(1, "Where we start", "Can the work get done today?")
        base = d.overview()
        expect(base["done"] == 1 and base["total"] == 3, "baseline should be 1 of 3")
        with Scene(d, f"The headline is not a score. It is how much work gets finished. Right now, {words(base['done'])} of {words(base['total'])} tasks complete.",
                   f"{base['done']} of {base['total']} tasks complete, measured by actually running them"):
            d.zoom(page.locator(".hero .card").first, 1.3)
        cells = page.locator("section.card").first.locator("tbody tr").nth(0).locator("td")
        billing_score = int(cells.nth(4).inner_text())
        with Scene(d, f"Look at billing service. Its readiness score is {billing_score} out of a hundred, which sounds healthy. Yet its task is blocked.",
                   f"billing-service: score {billing_score}, task blocked"):
            d.zoom(page.locator("section.card tbody tr").first, 1.35)

        # ================================================================== 2. real blocker
        d.chapter(2, "Finding the real blocker", "What actually stopped the work?")
        with Scene(d, "Here is a real task: fix a billing error that leaves charges one cent short. AgentReady walks through it step by step.",
                   "Ticket BILL-2141: follow the task step by step"):
            d.go("#/service/billing-service", "billing-service")
            d.zoom(".steps", 1.15)
        with Scene(d, "It finds the service, the code, and the test command. It then runs the tests, and they stop. "
                      "The tests need a tax settings file, and nobody wrote down how to set it up.",
                   "The tests stop at one undocumented setting"):
            d.zoom(".steps li.blocked", 1.35)
        target = "Environment variables are usable"
        with Scene(d, "That becomes a finding, marked as a blocker because it really stopped the work. It shows the evidence, and it goes to the team that owns the service.",
                   "A blocker, with evidence, assigned to team-billing"):
            d.zoom(d.finding(target), 1.2)

        # ================================================================== 3. score is not proof
        d.chapter(3, "A higher score is not proof", "Two fixes that look like progress")
        before = d.score()
        with Scene(d, "The team starts with something easy: writing an architecture document. Then AgentReady retries the task.",
                   "Fix one: add an architecture document"):
            d.unzoom(fast=True)
            page.locator('[data-fix="1-architecture-doc"]').scroll_into_view_if_needed()
            d.fix_and_reassess("1-architecture-doc")
        first = d.score()
        expect(first > before and d.task() == "Blocked", "first fix should raise the score and stay blocked")
        with Scene(d, f"The score goes up, from {before} to {first}. But the task is still blocked. The document looks like progress, yet the assistant is no better off.",
                   f"Score {before} → {first}. Task still blocked"):
            d.zoom(".callout", 1.3)
        with Scene(d, "Next, the team documents the setting's name, but not a working value. The checklist is now satisfied.",
                   "Fix two: document the setting’s name only"):
            d.unzoom(fast=True)
            page.locator('[data-fix="2-env-name-only"]').scroll_into_view_if_needed()
            d.fix_and_reassess("2-env-name-only")
        second = d.score()
        status = d.finding_status(target)
        expect(d.task() == "Blocked" and status == "Reopened", "second fix should reopen the finding")
        with Scene(d, f"The score reaches {second}, and the task still fails. So AgentReady reopens the finding. A ticket can't be closed on paper: only a real retry can close it.",
                   f"Score {second}. Task still blocked. Finding reopened"):
            d.zoom(d.finding(target), 1.2)

        # ================================================================== 4. the fix that works
        d.chapter(4, "The fix that works", "One practical change")
        with Scene(d, "Now the team supplies a working sample settings file, so anyone can run the tests.",
                   "Fix three: ship a working sample configuration"):
            d.unzoom(fast=True)
            page.locator('[data-fix="3-env-working-config"]').scroll_into_view_if_needed()
            d.fix_and_reassess("3-env-working-config")
        third = d.score()
        expect(d.task() == "Completed", "working config should complete the task")
        with Scene(d, f"The score doesn't move: it stays at {third}. But the task now completes. The change that mattered most didn't change the score at all.",
                   f"Score unchanged at {third}. Task completed"):
            d.zoom(page.locator(".card", has_text="Latest task").first, 1.05)
        with Scene(d, "The history makes the point. The line of scores climbs while the task stays blocked, in red. Only the final run, in green, finishes the work.",
                   "The score rose while the task stayed blocked"):
            d.zoom(".chart", 1.3)

        # ================================================================== 5. leadership view
        d.chapter(5, "The leadership view", "Solve a problem once, across teams")
        with Scene(d, "Service owners see their own work. Platform leaders see the patterns, so a problem shared by many teams can be solved once.",
                   "Recurring blockers across all services"):
            d.go("#/platform", "Platform insights")
            d.zoom(page.locator("section.card").first, 1.05)
        with Scene(d, "The heat map shows each service across eight areas of readiness, from finding the code to understanding the ticket.",
                   "Eight readiness dimensions, per service"):
            d.zoom(".heat", 1.2)
        with Scene(d, "AgentReady can also read logs from failed assistant runs and suggest a likely cause. The logs here are simulated examples, so they are labelled, and they never count towards the results.",
                   "Simulated logs are labelled and kept out of the results"):
            d.go("#/traces", "Agent traces")
            d.zoom(".callout", 1.3)

        # ================================================================== 6. layers
        d.chapter(6, "Blockers in layers", "Each fix reveals the next one")
        d.unzoom(fast=True)
        d.go("#/", "Can agents finish work")
        with Scene(d, "Notifications service has a much lower score, and a different problem: the assistant can't even find it.",
                   "notifications-service: blocked at the first step"):
            d.go("#/service/notifications-service", "notifications-service")
            d.zoom(".steps", 1.3)
        with Scene(d, "Registering the service gets the task further, and exposes the next blocker: no description of how the service's interface works.",
                   "Fix one lets the task reach the next blocker"):
            d.unzoom(fast=True)
            page.locator('[data-fix="1-catalog-entry"]').scroll_into_view_if_needed()
            d.fix_and_reassess("1-catalog-entry")
            d.zoom(".steps li.blocked", 1.35)
        with Scene(d, "Publishing that description reveals the third blocker: nobody wrote down how to run the tests.",
                   "Fix two reveals the third blocker"):
            d.unzoom(fast=True)
            page.locator('[data-fix="2-openapi"]').scroll_into_view_if_needed()
            d.fix_and_reassess("2-openapi")
            d.zoom(".steps li.blocked", 1.35)
        with Scene(d, "One more line of instructions, and the task runs.", "Fix three: document the test command"):
            d.unzoom(fast=True)
            page.locator('[data-fix="3-test-command"]').scroll_into_view_if_needed()
            d.fix_and_reassess("3-test-command")
        low = d.score()
        expect(d.task() == "Completed", "notifications should complete")
        with Scene(d, f"The task completes at a score of just {low}, while billing was blocked at {second}. In these samples, the score told us very little about whether the work would get done.",
                   f"Completed at {low}. Billing was blocked at {second}"):
            d.zoom(page.locator(".card", has_text="Latest task").first, 1.05)
        d.unzoom()
        d.chip(None)
        d.caption(None)
        d.go("#/", "Can agents finish work")
        final = d.overview()
        expect(final["done"] == 3, "all three tasks should complete")

        # ================================================================== close
        d.slide('<div class="kicker">In summary</div><h2>Make services ready for AI assistants, and prove the fixes work</h2>'
                '<table class="tbl"><tr><th></th><th>Start</th><th>After the fixes</th></tr>'
                f'<tr><td>Tasks completed</td><td>{base["done"]} of {base["total"]}</td><td><b>{final["done"]} of {final["total"]}</b></td></tr>'
                f'<tr><td>Average readiness score</td><td>{base["score"]}</td><td><b>{final["score"]}</b></td></tr></table>'
                '<div class="note">Fictional sample services and a scripted test, not a real AI assistant. Testing with real assistants is the next step. '
                'Voiceover is AI-generated (Piper, en-GB). All app footage is a live recording.</div>')
        with Scene(d, f"In summary: tasks completed went from {words(base['done'])} of {words(base['total'])} to {words(final['done'])} of {words(final['total'])}, "
                      "on these sample services. The next step is to test this with real AI assistants. "
                      "AgentReady: don't just ask whether the AI is ready for the work. Ask whether the work is ready for the AI.", pad=1.2):
            pass
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
