import base64
import hashlib
import hmac
import json
import time
import urllib.parse

from settings import settings

PDF_TEMPLATE_VERSION = 2


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _build_invoice_pdf_token(invoice_data: dict, *, secret: str, ttl_seconds: int = 300) -> str:
    payload = {
        "v": 1,
        "exp": int(time.time()) + int(ttl_seconds),
        "invoice": invoice_data,
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_b64 = _b64url_encode(payload_raw)
    sig_raw = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig_raw)
    return f"{payload_b64}.{sig_b64}"


def generate_invoice_pdf_content(invoice_data: dict) -> bytes:
    """
    Generates PDF bytes from invoice data by rendering the frontend invoice HTML
    (so PDF output matches the web invoice UI).

    Requires:
    - Backend env: FRONTEND_BASE_URL, OMS_PDF_TOKEN_SECRET
    - Python deps: playwright (and chromium installed via `playwright install chromium`)
    """
    if not settings.OMS_PDF_TOKEN_SECRET:
        return None

    frontend_base = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not frontend_base:
        return None

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None

    token = _build_invoice_pdf_token(invoice_data, secret=settings.OMS_PDF_TOKEN_SECRET)
    url = f"{frontend_base}/invoice-pdf?token={urllib.parse.quote(token, safe='')}"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(url, wait_until="load", timeout=getattr(settings, "PDF_RENDER_TIMEOUT_MS", 30000))
            page.wait_for_selector("#invoice-root", timeout=getattr(settings, "PDF_RENDER_TIMEOUT_MS", 30000))
            # Ensure external assets (QR image, fonts) are loaded before printing.
            page.wait_for_load_state("networkidle", timeout=getattr(settings, "PDF_RENDER_TIMEOUT_MS", 30000))
            page.evaluate(
                """async () => {
                    const imgs = Array.from(document.images || []);
                    await Promise.all(imgs.map(img => {
                        if (img.complete) return Promise.resolve();
                        return new Promise(resolve => {
                            const done = () => resolve();
                            img.addEventListener('load', done, { once: true });
                            img.addEventListener('error', done, { once: true });
                        });
                    }));
                }"""
            )
            page.wait_for_timeout(150)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
            )
            browser.close()
            return pdf_bytes
    except Exception:
        return None
