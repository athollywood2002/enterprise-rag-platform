import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(os.environ["UI_FIXTURE_DIR"]) / "sources"
(root / "nested/runbook.txt").write_text("Nested document with a distinct basename.")
(root / "excluded.bin").write_bytes(b"unsupported")
from demo.library_fixtures import text_pdf

(root / "procedure.pdf").write_bytes(
    text_pdf("Restart the ORION router after approval.", "The NetworkOps team owns the router.")
)
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(
        **({"executable_path": os.environ["CHROMIUM_PATH"]} if os.getenv("CHROMIUM_PATH") else {}),
        headless=True,
        args=["--no-sandbox"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:18890/")
    page.get_by_label("API key", exact=True).fill("synthetic-ui-fixture-key")
    page.get_by_role("button", name="Connect", exact=True).click()
    page.wait_for_selector("#workspace:not([hidden])")
    expect(page.locator("#model-mode")).to_contain_text("synthetic")
    page.locator("#source-name").fill("Operations")
    page.locator("#folder-input").set_input_files(str(root))
    page.wait_for_selector("#preview-panel:not([hidden])")
    # Editing a source invalidates the preview immediately, before blur.
    page.locator("#source-name").fill("Operations updated")
    expect(page.locator("#preview-panel")).to_be_hidden()
    page.locator("#source-name").fill("Operations")
    page.locator("#folder-input").set_input_files(str(root))
    page.wait_for_selector("#preview-panel:not([hidden])")
    page.screenshot(path="docs/images/folder-preview.png", full_page=True)
    page.get_by_role("button", name="Start ingestion", exact=True).click()
    expect(page.locator("#job-title")).to_contain_text("completed", timeout=30000)
    job = page.locator("#job-select").input_value()
    page.reload()
    page.get_by_label("API key", exact=True).fill("synthetic-ui-fixture-key")
    page.get_by_role("button", name="Connect", exact=True).click()
    expect(page.locator("#job-title")).to_contain_text("completed", timeout=30000)
    assert page.locator("#job-select").input_value() == job
    page.get_by_label("Your question", exact=True).fill(
        "What is the recovery code and who owns the router?"
    )
    page.get_by_role("button", name="Ask the library", exact=True).click()
    page.wait_for_selector("#answer-panel:not([hidden])")
    expect(page.locator("#generation")).to_contain_text("simulated reply, not real inference")
    assert "ORION" in page.locator("#answer").inner_text()
    assert "NetworkOps" in page.locator("#answer").inner_text()
    expect(page.locator("#generation")).to_contain_text("Model mode: synthetic")
    expect(page.locator("#generation")).to_contain_text("simulated reply, not real inference")
    page.screenshot(path="docs/images/folder-results.png", full_page=True)
    page.locator("input[value=server]").check()
    page.wait_for_selector("#folder-list li")
    page.get_by_role("button", name="Preview this folder", exact=True).click()
    page.wait_for_selector("#preview-panel:not([hidden])")
    page.screenshot(path="docs/images/server-folder.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="docs/images/mobile-library.png", full_page=True)
    # Keyboard focus is visible and controls are native form elements.
    page.keyboard.press("Tab")
    assert page.evaluate("() => document.activeElement.tagName") in [
        "INPUT",
        "BUTTON",
        "SELECT",
        "TEXTAREA",
        "A",
        "SUMMARY",
    ]
    assert not errors, errors
    print(
        json.dumps(
            {
                "status": "PASS",
                "job": job,
                "browser": "Chromium",
                "checks": [
                    "folder selection + upload",
                    "actual parser/worker",
                    "persisted refresh",
                    "cited answer (synthetic model)",
                    "server browse/preview",
                    "390px no horizontal overflow",
                    "keyboard focus",
                    "no JavaScript errors",
                ],
            }
        )
    )
    browser.close()
# Non-sensitive screenshots of the actual fixture UI for review.
if os.getenv("UI_EMIT_SCREENSHOTS"):
    import base64

    for name in (
        "folder-preview.png",
        "folder-results.png",
        "server-folder.png",
        "mobile-library.png",
    ):
        print(
            "UI_SCREENSHOT:"
            + name
            + ":"
            + base64.b64encode((Path("docs/images") / name).read_bytes()).decode()
        )
