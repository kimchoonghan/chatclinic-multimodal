"""
Patient SOAP Summary Plugin (local Ollama)
==========================================
Summarizes a patient's longitudinal clinical notes into a single concise
SOAP note (Subjective / Objective / Assessment / Plan) using a local Ollama
Qwen model. No external API and no GPU required by the plugin itself — the
Ollama server handles GPU inference.

Environment variables:
  OLLAMA_HOST   (default: http://127.0.0.1:11434)
  OLLAMA_MODEL  (default: qwen3:14b)
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")

# A clinical note may be wrapped in the dementia-prediction task prompt. The
# real longitudinal record starts at the first dated chunk marker, e.g.
#   2022-02-04: <<<CHUNK 1/2 (row:5350:chunk:0)>>>
VISIT_MARKER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}: <<<CHUNK", re.MULTILINE)

SYSTEM_PROMPT = (
    "You are a clinical documentation assistant. You read longitudinal clinical "
    "notes for a single patient and produce a faithful, concise summary. Never "
    "invent findings; only use what the notes state. Be terse and clinical."
)

SOAP_INSTRUCTION = (
    "Summarize this patient's ENTIRE longitudinal record into ONE concise SOAP note.\n"
    "Use exactly these four sections and keep each to a few short bullet points:\n"
    "S (Subjective): chief complaints, symptom course, relevant history.\n"
    "O (Objective): key exam/cognitive scores (MMSE, CDR, GDS, etc.), labs, imaging.\n"
    "A (Assessment): the working diagnosis / problem list and trajectory.\n"
    "P (Plan): medications and follow-up plan.\n"
    "Be maximally concise. Do not repeat the raw notes. Output only the SOAP note."
)


def _strip_task_preamble(text: str) -> str:
    """Return the clinical-note body, dropping any dementia-task instructions."""
    match = VISIT_MARKER_RE.search(text)
    if match:
        return text[match.start():].strip()
    return text.strip()


def _call_ollama(prompt: str) -> str:
    """POST a single-turn generation request to the local Ollama server."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {url}. Is `ollama serve` running and is "
            f"the model '{OLLAMA_MODEL}' pulled? Error: {exc}"
        ) from exc
    return _clean(str(data.get("response", "")))


def _clean(text: str) -> str:
    """Drop any stray <think> reasoning block and trim whitespace."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def execute(payload: dict[str, object]) -> dict[str, object]:
    """Entry point called by the ChatClinic tool runner."""
    text_path = str(payload.get("text_path") or "").strip()
    if not text_path:
        raise ValueError("`text_path` is required. Upload a .txt clinical note first.")
    path = Path(text_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Clinical note not found: {path}")

    raw = path.read_text(encoding="utf-8", errors="replace")
    notes = _strip_task_preamble(raw)
    if not notes:
        raise ValueError("The clinical note is empty after removing task instructions.")

    prompt = f"{SOAP_INSTRUCTION}\n\nClinical notes:\n{notes}"
    soap = _call_ollama(prompt)

    return {
        "patient_soap_summary": {
            "summary": soap,
            "format": "SOAP",
            "source_file": path.name,
            "model": OLLAMA_MODEL,
            "inference_server": OLLAMA_HOST,
        },
    }
