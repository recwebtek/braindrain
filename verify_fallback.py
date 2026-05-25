import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
import threading
import time
from playwright.sync_api import sync_playwright

app = FastAPI()

def get_fallback_html():
    from braindrain.livingdash_sidecar import create_app
    dummy_path = Path(".")
    dummy_auth = {"username": "admin", "password": "password", "session_secret": "secret"}
    sidecar_app = create_app(project_root=dummy_path, data_dir=dummy_path, ui_dist=dummy_path, auth_config=dummy_auth)

    for route in sidecar_app.routes:
        if route.path == "/{full_path:path}":
            return route.endpoint("anything").body.decode()
    return None

@app.get("/")
def read_index():
    return HTMLResponse(get_fallback_html())

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        page.goto("http://127.0.0.1:8001")

        page.screenshot(path="fallback_initial.png")

        copy_btn = page.locator(".copy-btn")
        if copy_btn.count() > 0:
            copy_btn.click()
            page.wait_for_function("btn => btn.innerText === 'Copied!'", arg=copy_btn.element_handle(), timeout=5000)
            page.screenshot(path="fallback_final.png")
            print("Verification successful")
        else:
            print("FAILURE: Copy button not found!")

        browser.close()
