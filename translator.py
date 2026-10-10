#!/usr/bin/env python3
"""
Translation providers.

Primary:  Azure Translator official API (free F0 tier = 2M chars/month,
          no auto-charge; quota just blocks until the next month).
Fallback: Google Translate via the unofficial `translators` library.

Configuration (.env next to the app or exe):
  AZURE_TRANSLATOR_KEY     - Azure resource key (optional; Google is used if missing)
  AZURE_TRANSLATOR_REGION  - resource region (e.g. eastus) or "global" (default)
"""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path
from typing import cast

import requests
import translators as ts
from dotenv import load_dotenv
from translators.server import TranslatorError

if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).parent

load_dotenv(_APP_DIR / ".env")

AZURE_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"
MAX_RETRIES = 5
BASE_DELAY = 3
REQUEST_TIMEOUT = 30
GOOGLE_PAUSE = (1.0, 2.5)
# Legacy ISO codes the `translators` Google endpoint expects
GOOGLE_LANG = {"he": "iw"}
# Marker injected when a block could not be translated and the source text is
# kept, so the failure is visible instead of English appearing mid-book.
FAIL_MARKER = "[translation failed; kept original text below]\n"

_azure_disabled = False


class TranslationFailed(Exception):
    """Both Azure and Google failed for this request."""


class _HTTPStatus(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class _AzureUnavailable(Exception):
    """Invalid key, blocked account, or exhausted quota — stop using Azure."""


def _azure_key() -> str:
    return (os.getenv("AZURE_TRANSLATOR_KEY") or "").strip()


def _azure_region() -> str:
    return (os.getenv("AZURE_TRANSLATOR_REGION") or "global").strip()


def _call_azure(text: str, tgt: str, src: str) -> str:
    params = {"api-version": "3.0", "from": src, "to": tgt}
    headers = {
        "Ocp-Apim-Subscription-Key": _azure_key(),
        "Ocp-Apim-Subscription-Region": _azure_region(),
        "Content-Type": "application/json",
    }
    resp = requests.post(
        AZURE_ENDPOINT,
        params=params,
        headers=headers,
        json=[{"Text": text}],
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 200:
        return resp.json()[0]["translations"][0]["text"]
    if (
        resp.status_code in (401, 403)
        or resp.headers.get("X-User-Quota-Reached", "").lower() == "true"
    ):
        raise _AzureUnavailable(f"HTTP {resp.status_code}")
    raise _HTTPStatus(resp.status_code)


def _azure_translate(text: str, tgt: str, src: str, verbose: bool) -> str | None:
    global _azure_disabled
    if _azure_disabled or not _azure_key():
        return None

    last_status = None
    for attempt in range(MAX_RETRIES):
        try:
            return _call_azure(text, tgt, src)
        except _AzureUnavailable as e:
            _azure_disabled = True
            if verbose:
                print(f"    Azure unavailable ({e}), using Google fallback")
            return None
        except _HTTPStatus as e:
            last_status = e.status
        except requests.RequestException:
            last_status = None

        if attempt < MAX_RETRIES - 1:
            wait = BASE_DELAY * (attempt + 1) + random.uniform(0, 2)
            if verbose:
                print(f"    Azure retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s...")
            time.sleep(wait)

    if last_status == 429:
        _azure_disabled = True
        if verbose:
            print("    Azure monthly quota reached, using Google fallback")
    return None


def _google_translate(text: str, tgt: str, src: str, verbose: bool) -> str | None:
    time.sleep(random.uniform(*GOOGLE_PAUSE))
    lang = GOOGLE_LANG.get(tgt, tgt)
    for attempt in range(MAX_RETRIES):
        try:
            return cast(
                str,
                ts.translate_text(
                    text,
                    translator="google",
                    from_language=src,
                    to_language=lang,
                ),
            )
        except TranslatorError as e:
            if verbose:
                print(f"    Google cannot translate to '{tgt}': {e}")
            return None
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = BASE_DELAY * (attempt + 1) + random.uniform(0, 2)
                if verbose:
                    print(f"    Google retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s... ({e})")
                time.sleep(wait)
    return None


def translate(text: str, tgt: str, src: str = "en", verbose: bool = False) -> str:
    """Translate text into `tgt`: Azure first, Google fallback.

    Raises TranslationFailed if both providers fail (instead of silently
    returning untranslated English, which looked like broken words among
    translated text).
    """
    if not text.strip():
        return ""

    result = _azure_translate(text, tgt, src, verbose)
    if result is not None:
        return result

    result = _google_translate(text, tgt, src, verbose)
    if result is not None:
        return result

    raise TranslationFailed(text)
