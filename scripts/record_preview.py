"""Record a preview walkthrough of the app as preview.mp4 for the README.

Boots the FastAPI backend and the Vite dev server, drives a scripted walkthrough
of the console with Playwright, then converts the capture to MP4.

    python scripts/record_preview.py

Notes on what this does and does not assume:

* Both servers are started as child processes and torn down at the end, even on
  failure. If either port is already serving, the script reuses what is running
  instead of starting a duplicate.
* Playwright records WebM — that is the only format Chromium exposes. The MP4 at
  the end is an ffmpeg transcode. Without ffmpeg on PATH the script keeps the
  WebM and tells you; it does not fail the run.
* The triage itself is a real request through Ollama and the vector store, so
  the walkthrough waits minutes, not seconds. `--skip-analysis` records the UI
  tour without submitting, which is much faster if you only need the visuals.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
VIDEO_DIR = os.path.join(ROOT, "videos")
OUT_MP4 = os.path.join(ROOT, "preview.mp4")

BACKEND_PORT = 8000
FRONTEND_PORT = 5173
# `localhost`, not 127.0.0.1: Vite binds the IPv6 loopback on Windows, and this
# is also the origin the backend's CORS allowlist names.
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

VIEWPORT = {"width": 1280, "height": 800}

# Synthetic phishing-SMS screenshot, padded with carrier/clock/battery chrome so
# the recording exercises OCR and the sanitiser. Regenerate with
# scripts/make_sample_screenshot.py.
SAMPLE_SCREENSHOT = os.path.join(ROOT, "assets", "sample-scam-screenshot.png")

# Deliberately complementary to the screenshot rather than a restatement of it:
# the SMS carries the lure, the typed narrative carries the loss and the
# negation. Fusing the two is Node A's job.
SAMPLE_COMPLAINT = (
    "I got this SMS and then a man called saying he was from the bank. He asked "
    "me to read out the OTP to verify my identity, and within minutes Rs 48,000 "
    "was debited through UPI to an unknown handle. I did NOT authorise that "
    "transfer and the bank has still not blocked my account."
)


def _find_ffmpeg() -> str | None:
    """Locate an ffmpeg binary, preferring a system install.

    Falls back to the static build bundled by the `imageio-ffmpeg` wheel, so a
    Python-only environment can still produce an MP4 without asking anyone to
    install system packages.
    """
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------
def _port_open(port: int) -> bool:
    """Is something listening on this port, on either loopback family?

    create_connection resolves `localhost` and tries each address, so this sees
    a server bound only to ::1 (which is what Vite does on Windows) as well as
    one bound only to 127.0.0.1.
    """
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for(check, label: str, timeout: float) -> None:
    """Poll `check` until it returns True, or raise once `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            print(f"[preview] {label} is up")
            return
        time.sleep(1.0)
    raise RuntimeError(f"{label} did not come up within {timeout:.0f}s")


def _backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/health", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _start_backend() -> subprocess.Popen | None:
    if _port_open(BACKEND_PORT):
        print(f"[preview] reusing the server already on :{BACKEND_PORT}")
        return None

    print("[preview] starting FastAPI (loading EasyOCR + ChromaDB, this is slow)...")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(BACKEND_PORT)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def _start_frontend() -> subprocess.Popen | None:
    if _port_open(FRONTEND_PORT):
        print(f"[preview] reusing the server already on :{FRONTEND_PORT}")
        return None

    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        raise RuntimeError("frontend/node_modules is missing — run `npm install` in frontend/")

    print("[preview] starting Vite dev server...")
    return subprocess.Popen(
        # shell=True so Windows resolves npm.cmd without us guessing the extension.
        "npm run dev",
        cwd=FRONTEND,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def _stop(proc: subprocess.Popen | None, label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    print(f"[preview] stopping {label}")
    if os.name == "nt":
        # `npm run dev` spawns vite as a grandchild; terminate() would orphan it.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# The walkthrough
# ---------------------------------------------------------------------------
def _walkthrough(page, skip_analysis: bool, analysis_timeout_ms: int) -> None:
    def beat(seconds: float = 1.2) -> None:
        """Hold still so the recording has a readable pause between actions."""
        page.wait_for_timeout(int(seconds * 1000))

    # --- Sign in -----------------------------------------------------------
    print("[preview] scene 1/5 — sign in")
    page.goto(FRONTEND_URL, wait_until="networkidle")
    beat(2.0)

    page.get_by_placeholder("e.g. officer.rao").click()
    page.get_by_placeholder("e.g. officer.rao").type("officer.rao", delay=90)
    beat(0.5)
    page.get_by_placeholder("••••••••").click()
    page.get_by_placeholder("••••••••").type("demo-passphrase", delay=70)
    beat(0.8)
    page.get_by_role("button", name="Enter Console").click()

    page.wait_for_selector("text=File an Incident", timeout=15_000)
    beat(1.8)

    # --- Fill the complaint -------------------------------------------------
    print("[preview] scene 2/5 — describe the incident")
    textarea = page.locator("textarea")
    textarea.click()
    # Typed rather than filled: the point of the recording is to look like use.
    textarea.type(SAMPLE_COMPLAINT, delay=14)
    beat(1.5)

    # --- Attach the evidence screenshot -------------------------------------
    print("[preview] scene 3/5 — attach the evidence screenshot (OCR path)")
    if not os.path.isfile(SAMPLE_SCREENSHOT):
        raise RuntimeError(
            f"{SAMPLE_SCREENSHOT} is missing — run "
            "`python scripts/make_sample_screenshot.py` first."
        )
    # The input is visually hidden behind a drop zone; set_input_files does not
    # need it to be visible.
    page.locator('input[type="file"]').set_input_files(SAMPLE_SCREENSHOT)
    # Wait for the thumbnail so the recording shows the attachment landing.
    page.wait_for_selector('img[alt="Evidence preview"]', timeout=15_000)
    beat(2.5)

    if skip_analysis:
        print("[preview] scenes 4-5/5 — skipped (--skip-analysis)")
        beat(2.0)
        return

    # --- Run the triage -----------------------------------------------------
    print("[preview] scene 4/5 — running triage (OCR + graph; takes a few minutes)")
    page.get_by_role("button", name="Run Triage Analysis").click()
    beat(2.5)  # let the loading state be visible in the recording

    # The report is the first thing rendered when the request lands.
    page.wait_for_selector("text=Threat Classification", timeout=analysis_timeout_ms)
    print("[preview] report received")
    beat(2.5)

    # --- Read the report ----------------------------------------------------
    print("[preview] scene 5/5 — walking the full sourced report")
    # Scroll the report's own overflow container, not the window. Scrolling the
    # page drags the form column out of frame and leaves half the video black.
    scroller = page.locator(".thin-scroll").first
    distance = scroller.evaluate("el => el.scrollHeight - el.clientHeight")
    viewport = scroller.evaluate("el => el.clientHeight")

    if distance <= 0:
        # The panel is not bounded (narrow viewport, or the layout changed), so
        # the page itself is what scrolls. Fall back rather than silently
        # recording a walkthrough that never moves.
        print("[preview] report panel is not bounded — scrolling the window instead")
        scroller = None
        distance = page.evaluate(
            "document.documentElement.scrollHeight - window.innerHeight"
        )
        viewport = page.evaluate("window.innerHeight")

    # Step by a bit less than a viewport so consecutive frames overlap and
    # nothing is skipped past. The report length varies with how many playbook
    # entries matched, so derive the step count rather than fixing it.
    stride = max(int(viewport * 0.7), 1)
    steps = max((distance + stride - 1) // stride, 1)
    print(f"[preview] report is {distance}px past the fold — {steps} scroll steps")

    def scroll_to(top: int) -> None:
        if scroller is not None:
            scroller.evaluate("(el, top) => el.scrollTo({top, behavior: 'smooth'})", top)
        else:
            page.evaluate("top => window.scrollTo({top, behavior: 'smooth'})", top)

    for i in range(1, steps + 1):
        scroll_to(min(stride * i, distance))
        beat(1.6)  # long enough to actually read a step and its citation
    beat(2.0)

    # Return to the top so the recording ends on the classification, not on
    # whatever happened to be at the bottom of the scroll.
    scroll_to(0)
    beat(2.5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="record the UI tour without submitting the incident (much faster)",
    )
    parser.add_argument(
        "--analysis-timeout",
        type=int,
        default=480,
        help="seconds to wait for the triage report (default: 480)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="show the browser window while recording",
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. Run:\n"
            "    pip install playwright\n"
            "    python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    backend = frontend = None
    video_path = None

    try:
        # A UI-only tour never calls the API, so there is no reason to spend
        # minutes booting EasyOCR, the vector store and Ollama for it.
        if not args.skip_analysis:
            backend = _start_backend()
        frontend = _start_frontend()

        _wait_for(lambda: _port_open(FRONTEND_PORT), "Vite dev server", timeout=90)
        if not args.skip_analysis:
            # The backend imports EasyOCR and opens the vector store on first
            # load, which is minutes on a cold start, not seconds.
            _wait_for(_backend_healthy, "FastAPI backend", timeout=600)

        shutil.rmtree(VIDEO_DIR, ignore_errors=True)
        os.makedirs(VIDEO_DIR, exist_ok=True)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=VIDEO_DIR,
                record_video_size=VIEWPORT,
            )
            page = context.new_page()

            # Diagnostics. A walkthrough that stalls tells you nothing on its
            # own — you cannot see the browser, and the failure surfaces as a
            # selector timeout no matter what actually went wrong.
            console_errors: list[str] = []
            page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
            page.on(
                "console",
                lambda m: console_errors.append(f"console.error: {m.text}")
                if m.type == "error"
                else None,
            )
            page.on(
                "requestfailed",
                lambda r: console_errors.append(f"request failed: {r.url} ({r.failure})"),
            )
            page.on(
                "response",
                lambda r: print(f"[preview] <- {r.status} {r.url}")
                if "/analyze" in r.url
                else None,
            )

            try:
                _walkthrough(page, args.skip_analysis, args.analysis_timeout * 1000)
            except Exception:
                shot = os.path.join(ROOT, "preview-failure.png")
                try:
                    page.screenshot(path=shot, full_page=True)
                    print(f"[preview] captured failure screenshot: {shot}", file=sys.stderr)
                except Exception:
                    pass
                for line in console_errors[-15:]:
                    print(f"[preview]   {line}", file=sys.stderr)
                raise
            finally:
                # The video is only flushed to disk once the context closes.
                page.close()
                context.close()
                browser.close()

        videos = [f for f in os.listdir(VIDEO_DIR) if f.endswith(".webm")]
        if not videos:
            print("[preview] no video was produced", file=sys.stderr)
            return 1
        video_path = os.path.join(VIDEO_DIR, videos[0])

    except Exception as exc:
        print(f"[preview] failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _stop(frontend, "Vite")
        _stop(backend, "FastAPI")

    # --- WebM -> MP4 --------------------------------------------------------
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        fallback = os.path.join(ROOT, "preview.webm")
        shutil.move(video_path, fallback)
        shutil.rmtree(VIDEO_DIR, ignore_errors=True)
        print(
            f"\n[preview] no ffmpeg available, so the recording was kept as\n"
            f"          {fallback}\n"
            f"          For preview.mp4, install either:\n"
            f"              uv pip install imageio-ffmpeg     (no system install)\n"
            f"              winget install Gyan.FFmpeg        (system-wide)\n"
            f"          GitHub READMEs can also embed the .webm as-is.",
        )
        return 0

    print("[preview] transcoding to MP4...")
    result = subprocess.run(
        [
            ffmpeg, "-y", "-i", video_path,
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "26",
            # H.264 needs even dimensions, and yuv420p is what browsers and
            # GitHub's player actually decode.
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            OUT_MP4,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        print(f"[preview] ffmpeg failed:\n{result.stderr[-1500:]}", file=sys.stderr)
        print(f"[preview] the raw recording is still at {video_path}", file=sys.stderr)
        return 1

    shutil.rmtree(VIDEO_DIR, ignore_errors=True)
    size_mb = os.path.getsize(OUT_MP4) / (1024 * 1024)
    print(f"\n[preview] wrote {OUT_MP4} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
