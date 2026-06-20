"""
Per-Visit Summary Plugin (local Ollama)
=======================================
Splits a patient's longitudinal clinical notes into individual visits (by
date) and summarizes each visit separately using a local Ollama Qwen model.
The Ollama server handles GPU inference; the plugin itself needs no GPU.

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

# Each visit chunk is introduced by a dated marker line, e.g.
#   2022-02-04: <<<CHUNK 1/2 (row:5350:chunk:0)>>>
# Multiple same-date chunks belong to the same visit.
CHUNK_MARKER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}): <<<CHUNK[^>]*>>>\s*$", re.MULTILINE
)
FIRST_MARKER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}: <<<CHUNK", re.MULTILINE)

SYSTEM_PROMPT = (
    "You are a clinical documentation assistant. You read a single clinical "
    "visit note and produce a faithful, concise summary. Never invent findings; "
    "only use what the note states. Be terse and clinical."
)

VISIT_INSTRUCTION = (
    "Summarize this single clinical visit in 2-4 short bullet points. Capture: "
    "the reason/complaint, any cognitive or functional scores (MMSE, CDR, GDS, "
    "etc.), notable findings or imaging, and any medication or plan change. "
    "Be maximally concise. Output only the bullet points, no preamble."
)


def _strip_task_preamble(text: str) -> str:
    match = FIRST_MARKER_RE.search(text)
    return text[match.start():].strip() if match else text.strip()


def _split_visits(notes: str) -> list[dict[str, str]]:
    """Group dated note chunks into ordered visits (same date = one visit)."""
    markers = list(CHUNK_MARKER_RE.finditer(notes))
    if not markers:
        return []

    # Slice the body that follows each marker line.
    segments: list[tuple[str, str]] = []
    for i, m in enumerate(markers):
        date = m.group(1)
        body_start = m.end()
        body_end = markers[i + 1].start() if i + 1 < len(markers) else len(notes)
        body = notes[body_start:body_end].strip()
        segments.append((date, body))

    # Merge consecutive segments that share the same date into one visit.
    visits: list[dict[str, str]] = []
    for date, body in segments:
        if visits and visits[-1]["date"] == date:
            visits[-1]["text"] = f"{visits[-1]['text']}\n{body}".strip()
        else:
            visits.append({"date": date, "text": body})
    return visits


def _clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


def _call_ollama(prompt: str) -> str:
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


def execute(payload: dict[str, object]) -> dict[str, object]:
    """Entry point called by the ChatClinic tool runner."""
    text_path = str(payload.get("text_path") or "").strip()
    if not text_path:
        raise ValueError("`text_path` is required. Upload a .txt clinical note first.")
    path = Path(text_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Clinical note not found: {path}")

    notes = _strip_task_preamble(path.read_text(encoding="utf-8", errors="replace"))
    visits = _split_visits(notes)
    if not visits:
        raise ValueError("No dated visit markers were found in this clinical note.")

    results: list[dict[str, object]] = []
    markdown_parts: list[str] = []
    for idx, visit in enumerate(visits, start=1):
        prompt = f"{VISIT_INSTRUCTION}\n\nVisit date: {visit['date']}\nVisit note:\n{visit['text']}"
        summary = _call_ollama(prompt)
        results.append({"visit": idx, "date": visit["date"], "summary": summary})
        markdown_parts.append(f"### Visit {idx} ({visit['date']})\n{summary}")

    return {
        "visit_summary": {
            "summary": "\n\n".join(markdown_parts),
            "visits": results,
            "num_visits": len(results),
            "source_file": path.name,
            "model": OLLAMA_MODEL,
            "inference_server": OLLAMA_HOST,
        },
    }
