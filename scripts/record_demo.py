"""Record the narrated AgentReady product demo (Playwright + Chromium, 1920x1080, British Piper voiceover).

One opening slide, then narration over real clicks in the running app, in Simulation mode. Agent steps use
prepared data and are labelled on screen. Script checks and file fixes are real, and the story stops
if the page does not show what the narration says. The app runs on its own port with a temporary data folder,
so it never touches a running copy.

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
  html { overflow-x: hidden; scroll-behavior: smooth; }
  body { padding-bottom: 130px; }
  main, .top { zoom: 1.3; }
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
  #demo-slide li { font-size: 29px; color: #e2e8f0; line-height: 1.35; padding-left: 46px; position: relative; }
  #demo-slide li::before { content: ''; position: absolute; left: 0; top: 13px; width: 18px; height: 18px; border-radius: 5px; background: #3987e5; }
  #demo-slide li b { color: #fff; }
  #demo-slide .note { margin-top: 44px; font-size: 26px; color: #fcd34d; border-left: 4px solid #f59e0b; padding-left: 18px; line-height: 1.4; }
  #demo-caption { pointer-events: none; position: fixed; left: 0; right: 0; bottom: 0; min-height: 104px; z-index: 99995;
    display: flex; align-items: center; justify-content: center; background: #111827; color: #fff; padding: 14px 120px;
    font: 600 31px/1.3 Inter, -apple-system, sans-serif; text-align: center; }
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


BANNED_WORDS = ("different", "one cent", "assistant", "makes the fix", "probe", "billing")
# Captions keep the exact text. These respellings are only for the voice.
SPOKEN = {"6 of 17": "six of seventeen", "9 of 17": "nine of seventeen"}


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
        spoken = self.text
        for written, said in SPOKEN.items():
            spoken = spoken.replace(written, said)
        path, self.dur = self.demo.narrator.synth(spoken)
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

    def slide(self, html: str | None) -> None:
        if html is None:
            self.page.evaluate("() => { document.getElementById('demo-slide').classList.remove('show'); document.getElementById('demo-cursor').style.display = ''; }")
            self.page.wait_for_timeout(650)
            return
        self.page.evaluate("""h => { const s = document.getElementById('demo-slide'); s.querySelector('.inner').innerHTML = h;
            s.classList.add('show'); document.getElementById('demo-cursor').style.display = 'none'; }""", html)
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

    def show(self, target: Locator | str) -> None:
        """Brings something to the middle of the area above the caption bar."""
        loc = self.page.locator(target).first if isinstance(target, str) else target
        loc.evaluate("el => { const b = el.getBoundingClientRect(); scrollBy(0, b.top - Math.max(130, (innerHeight - 110 - b.height) / 2)); }")
        self.page.wait_for_timeout(800)
        box = loc.bounding_box()
        if box:
            self._move(box["x"] + min(box["width"] * 0.5, 80), box["y"] + min(box["height"] * 0.5, 40))
        self.page.wait_for_timeout(400)

    def go(self, hash_: str, heading: str) -> None:
        """Move between pages through the app's own links."""
        self.click(self.page.locator(f'a[href="{hash_}"]').first, settle=300)
        self.page.wait_for_selector(f"h1:has-text('{heading}')")
        self.page.evaluate("() => scrollTo({top: 0, behavior: 'instant'})")
        self.page.wait_for_timeout(350)

    def finding(self, title: str) -> Locator:
        return self.page.locator(".finding", has_text=title).first

    def assert_text(self, text: str) -> None:
        self.page.wait_for_selector(f"text={text}")

    def fix(self, title: str) -> None:
        """Applies a prepared fix from its finding, which really writes files in the sample repository."""
        finding = self.finding(title)
        self.show(finding)
        self.click(finding.locator("[data-fix]"), settle=300)
        self.page.wait_for_function("t => ![...document.querySelectorAll('.finding')].some(f => f.innerText.includes(t) && f.querySelector('[data-fix]'))", arg=title)
        self.page.wait_for_timeout(300)

    def checks_passed(self) -> str:
        return self.page.locator(".stat").first.inner_text().strip()


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
                '<p class="lead">Check whether a service is ready for AI coding agents before work is assigned to them.</p>'
                '<div class="note">Local prototype with one sample service. Agent steps are simulated with prepared data. Script checks and file fixes are real.</div>')
        with Scene(d, "This is AgentReady. It checks whether a service is ready for AI coding agents before work is assigned to them. "
                      "This is a local prototype using one sample service, Notifications Service. In this demo, the agent steps are simulated with prepared data, "
                      "because the coding agent isn't reliable yet. The script checks and file fixes are real, and simulated steps are labelled on screen.", pad=0.5):
            pass
        d.slide(None)

        # ================================================================== find gaps
        d.point("#service-select", settle=500)
        d.click("#assess", settle=400)
        page.wait_for_selector(".stat")
        before = d.checks_passed()
        expect(before == "6 of 17", f"first assessment should pass 6 of 17, got {before}")
        d.show(page.locator(".card", has_text="Readiness checks").first)
        with Scene(d, "We assess the service. Scripts check the facts: 6 of 17 pass."):
            pass
        page.wait_for_selector(".running", state="detached", timeout=30_000)
        d.go("#/findings", "Findings")
        api = d.finding("API contract does not match the code")
        d.show(api)
        with Scene(d, "The simulated Gap Analysis Agent adds what scripts can't judge. The API contract doesn't match the code, and the template guide leaves out required steps."):
            page.wait_for_timeout(4500)
            d.show(d.finding("Template guide leaves out required steps"))

        # ================================================================== assign
        d.show(api)
        with Scene(d, "AgentReady records each gap and assigns it to the owning team, with evidence, a recommendation and what must pass to close it. This happens inside the app. There's no Jira link yet."):
            pass

        # ================================================================== fix
        with Scene(d, "In a real product, the team would be informed and would make the fix. In this demo, the team isn't informed, "
                      "and the fix is simulated with a prepared change to the sample files."):
            for title in ("API contract does not match the code", "Template guide leaves out required steps",
                          "Service is registered in the catalog", "Test command is documented"):
                d.fix(title)

        # ================================================================== reassess
        d.go("#/", "notifications-service")
        d.show("#reassess")
        with Scene(d, "A team can't close its own finding. We reassess."):
            d.click("#reassess", settle=400)
        page.wait_for_function("() => document.querySelector('.stat')?.innerText.trim() === '9 of 17'")
        page.wait_for_selector(".running", state="detached", timeout=30_000)
        expect(d.checks_passed() == "9 of 17", "reassessment should pass 9 of 17")
        data = page.evaluate("() => fetch('/api/services/notifications-service').then(r => r.json())")
        expect(all(f["status"] == "verified" for f in data["findings"] if f["source"] != "script"), "the agent's findings should be closed")
        d.show(page.locator(".card", has_text="Readiness checks").first)
        with Scene(d, "Script checks rise to 9 of 17, and the simulated recheck closes the agent's two findings. The remaining gaps stay open and visible."):
            page.wait_for_timeout(5500)
            d.go("#/findings", "Findings")

        # ================================================================== coding task
        d.go("#/coding", "Coding task validation")
        with Scene(d, "Now the coding agent attempts a task: add a payment failed template. In this simulated run, the task passes."):
            d.click("#validate", settle=300)
            page.wait_for_selector(".stat:text-is('Passed')", timeout=30_000)
            d.show(page.locator(".card", has_text="Outcome").first)

        # ================================================================== what happens later
        d.slide('<div class="kicker">After the first assessment</div><h2>The same process applies whenever work gets stuck</h2>'
                '<ul><li>A <b>story, bug or requirement</b> is raised in Jira</li>'
                '<li>If the coding agent can\'t complete it, it <b>raises an issue to the platform</b></li>'
                '<li>The platform <b>analyses the issue</b>, and the gap goes to the owning team</li>'
                '<li>The team <b>fixes it</b>, and the service is <b>reassessed</b></li></ul>'
                '<div class="note">Not built yet. This demo shows the first assessment only.</div>')
        with Scene(d, "After this first assessment, the same process applies whenever work gets stuck. A story, bug or requirement is raised in Jira. "
                      "If the coding agent can't complete it, it raises an issue to the platform. The platform analyses the issue, the gap goes to the owning team, "
                      "it's fixed, and the service is reassessed. This part isn't built yet. This demo shows the first assessment only.", pad=0.5):
            pass

        # ================================================================== close
        d.slide('<div class="kicker">AgentReady</div>'
                '<h2>Don\'t just ask whether the AI agent is ready for work. Make sure it always has what it needs to do the work.</h2>'
                '<ul><li>Shows whether a service is ready <b>before work is assigned</b></li>'
                '<li>Finds what\'s missing <b>whenever agents get stuck</b></li>'
                '<li>Gives every gap an <b>owner and evidence</b></li>'
                '<li>Closes a gap only when <b>reassessment confirms the fix</b></li>'
                '<li><b>Repeats as work continues</b>, so agents can work smoothly</li></ul>'
                '<div class="note">Early prototype. Making the real coding agent reliable comes next.</div>')
        with Scene(d, "AgentReady shows whether a service is ready for AI coding agents before work is assigned, and finds what's missing whenever agents get stuck. "
                      "Every gap has an owner and evidence, and a gap closes only when reassessment confirms the fix. "
                      "The process repeats as work continues, so agents can work smoothly. "
                      "Don't just ask whether the AI agent is ready for work. Make sure it always has what it needs to do the work. "
                      "This is an early prototype, and the next step is making the real coding agent reliable.", pad=1.2):
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
