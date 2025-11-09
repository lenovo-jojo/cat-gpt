#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
dialogue_prompt.py
Clean, cozy Animal Crossing dialogue generator.

- Uses OpenRouter by default (requests-based), with OpenAI client fallback.
- Supports image + text (screenshots sent as data: URLs).
- No real-world news or politics. Cozy, in-character, short lines.
- Optional gossip integration (pass gossip_context or set ENABLE_GOSSIP=1 upstream).
- Exposes:
    generate_dialogue(villager_name, image_paths=None, gossip_context=None)
    generate_spotlight_dialogue(villager_name, image_paths=None, gossip_context=None)

ENV (via .env):
  OPENROUTER_API_KEY=...
  OPENAI_API_KEY=...                 # optional fallback
  BASE_URL=https://openrouter.ai/api/v1
  OPENAI_BASE=...                    # optional (OpenAI-compatible base, overrides BASE_URL if using OpenAI client)
  MODEL=openai/gpt-4o-mini
  TEMPERATURE=0.7
  ENABLE_GOSSIP=1
"""

import os
import re
import json
import base64
import requests
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv
load_dotenv()

# -------------------- configuration --------------------

MODEL = os.getenv("MODEL", "openai/gpt-4o-mini")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
USE_GOSSIP = os.getenv("ENABLE_GOSSIP", "1") == "1"

# prefer OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://openrouter.ai/api/v1")

# optional OpenAI fallback (python client)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY")
OPENAI_BASE = os.getenv("OPENAI_BASE")

# attempt to import openai client (>=1.0) if needed
_openai_client = None
_openai_import_err = None
if not OPENROUTER_API_KEY and OPENAI_API_KEY:
    try:
        from openai import OpenAI
        if OPENAI_BASE:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE)
        else:
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as _e:
        _openai_import_err = _e
        _openai_client = None

# -------------------- utils --------------------

def _encode_image_to_data_url(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        print(f"⚠ could not read screenshot '{image_path}': {e}")
        return None

def _build_messages(system_prompt: str, user_prompt: str, image_paths: Optional[List[str]]) -> List[Dict[str, Any]]:
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    if image_paths:
        for p in image_paths:
            data_url = _encode_image_to_data_url(p)
            if data_url:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": data_url}
                })
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

def _post_to_openrouter(messages: List[Dict[str, Any]], max_tokens: int) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        # optional but recommended metadata
        "HTTP-Referer": "http://localhost",
        "X-Title": "Animal Crossing LLM Mod",
    }
    payload = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    url = f"{BASE_URL.rstrip('/')}/chat/completions"
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    if r.status_code != 200:
        raise RuntimeError(f"OpenRouter error {r.status_code}: {r.text}")
    data = r.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return (content or "").strip() or "(silence)"

def _post_to_openai(messages: List[Dict[str, Any]], max_tokens: int) -> str:
    if _openai_client is None:
        raise RuntimeError(f"OpenAI client unavailable: {_openai_import_err}")
    resp = _openai_client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        max_tokens=max_tokens,
        messages=messages,
    )
    txt = (resp.choices[0].message.content or "").strip()
    return txt or "(silence)"

def _call_chat(system_prompt: str, user_prompt: str, image_paths: Optional[List[str]], max_tokens: int = 220) -> str:
    messages = _build_messages(system_prompt, user_prompt, image_paths)
    try:
        if OPENROUTER_API_KEY:
            return _post_to_openrouter(messages, max_tokens)
        # fallback path
        if OPENAI_API_KEY:
            return _post_to_openai(messages, max_tokens)
        print("⚠ no API key found (OPENROUTER_API_KEY or OPENAI_API_KEY). returning fallback line.")
        return "…(the wind rustles; nobody answers)…"
    except Exception as e:
        print(f"⚠ chat error: {e}")
        return "(…the villager zones out for a moment…)"

# -------------------- villager data --------------------

_VILLAGERS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None

def _load_villagers() -> Dict[str, Dict[str, Any]]:
    global _VILLAGERS_CACHE
    if _VILLAGERS_CACHE is not None:
        return _VILLAGERS_CACHE
    paths = [
        "villagers.json",
        os.path.join(os.path.dirname(__file__), "villagers.json"),
    ]
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _VILLAGERS_CACHE = json.load(f) or {}
                return _VILLAGERS_CACHE
        except Exception:
            continue
    print("⚠ villagers.json not found; using empty map")
    _VILLAGERS_CACHE = {}
    return _VILLAGERS_CACHE

def _sanitize_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = name.strip()
    s = re.sub(r'^[\"\'\s]+', "", s)
    s = re.sub(r'[\"\'\s]+$', "", s)
    s = re.sub(r'^[xX]{3,}.*$', "", s)  # handles noisy "xxxxx"
    return s or None

def _title_name(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s

def _get_profile(name: Optional[str]) -> Dict[str, Any]:
    villagers = _load_villagers()
    clean = _sanitize_name(name) or "Unknown"
    for candidate in (clean, clean.title(), _title_name(clean)):
        if candidate in villagers:
            data = dict(villagers[candidate])
            data.setdefault("name", candidate)
            data.setdefault("modded", False)
            return data
    return {
        "name": clean,
        "modded": True,
        "personality": "normal",
        "species": "unknown",
        "catchphrase": "",
        "style": "",
    }

# -------------------- prompt building --------------------

_BASE_STYLE = (
    "You are roleplaying as a villager from Animal Crossing (GameCube-era tone). "
    "Stay in-character, cozy, and brief (1–3 short lines). "
    "Do not mention being an AI. No real-world politics or news. "
    "Use gentle humor. Avoid breaking the fourth wall unless the player clearly asks."
)

_DECORATION_RULES = (
    "Decorate minimally with in-engine tags WHEN useful:\n"
    "- Use <Pause [0A]> sparingly for timing.\n"
    "- Keep each line under ~30 visible chars; insert '\\n' where natural.\n"
    "- If multiple beats, end with '<Press A><Clear Text>'.\n"
)

def _gossip_snippet(gossip_context: Optional[Dict[str, Any]]) -> str:
    if not (USE_GOSSIP and gossip_context):
        return ""
    try:
        bits: List[str] = []
        if "rumor_topic" in gossip_context:
            bits.append(f"- rumor: {gossip_context['rumor_topic']}")
        if "targets" in gossip_context and gossip_context["targets"]:
            bits.append("- villagers mentioned: " + ", ".join(gossip_context["targets"][:4]))
        if "opinion" in gossip_context:
            bits.append(f"- vibe: {gossip_context['opinion']}")
        return ("\nGossip context:\n" + "\n".join(bits) + "\n") if bits else ""
    except Exception:
        return ""

def _persona_blurb(profile: Dict[str, Any]) -> str:
    name = profile.get("name", "Villager")
    pers = profile.get("personality", "normal")
    species = profile.get("species", "unknown")
    catch = profile.get("catchphrase", "")
    modded = profile.get("modded", False)
    parts = [f"Villager persona: {name} ({species}, {pers})."]
    if catch:
        parts.append(f"Catchphrase: “{catch}” (use very sparingly).")
    if modded:
        parts.append("This villager may be modded/unknown — keep tone neutral but friendly.")
    return " ".join(parts)

# -------------------- public api --------------------

def generate_dialogue(
    villager_name: Optional[str],
    image_paths: Optional[List[str]] = None,
    gossip_context: Optional[Dict[str, Any]] = None,
) -> str:
    profile = _get_profile(villager_name)

    system_prompt = "\n".join([
        _BASE_STYLE,
        _DECORATION_RULES,
        _persona_blurb(profile),
        _gossip_snippet(gossip_context),
        "Respond as the villager speaking to the player.",
    ])

    user_prompt = (
        "Create 1–3 short lines of cozy dialogue, specific to this villager. "
        "If an image is attached, subtly infer the setting or activity. "
        "Finish with '<Press A><Clear Text>' if you used multiple beats."
    )

    text = _call_chat(system_prompt, user_prompt, image_paths=image_paths, max_tokens=220)
    return _postprocess(text)

def generate_spotlight_dialogue(
    villager_name: Optional[str],
    image_paths: Optional[List[str]] = None,
    gossip_context: Optional[Dict[str, Any]] = None,
) -> str:
    profile = _get_profile(villager_name)

    system_prompt = "\n".join([
        _BASE_STYLE,
        _DECORATION_RULES,
        _persona_blurb(profile),
        _gossip_snippet(gossip_context),
        "Create a short, welcoming 'spotlight' blurb (like a title-card quip).",
    ])

    user_prompt = (
        "Write 1–2 charming lines introducing the day/vibes in-character. "
        "Optionally include one <Pause [0A]> for timing."
    )

    text = _call_chat(system_prompt, user_prompt, image_paths=image_paths, max_tokens=160)
    return _postprocess(text)

# -------------------- output cleanup --------------------

CONTROL_SAFE = [
    "<Press A>", "<Clear Text>", "<Pause [0A]>", "<Pause [05]>", "<Pause [14]>"
]

def _strip_forbidden_codes(s: str) -> str:
    # allow a small whitelist; strip unknown angle-bracket blocks
    def repl(m):
        frag = m.group(0)
        return frag if any(frag.startswith(x[:-1]) for x in CONTROL_SAFE) else ""
    return re.sub(r"<[^>]{1,40}>", repl, s)

def _trim_lines(s: str) -> str:
    # keep lines short-ish; encoder wraps too, but this helps
    out: List[str] = []
    for line in s.splitlines():
        t = line.strip()
        if len(t) <= 90:
            out.append(t)
            continue
        # soft wrap ~30 chars at spaces
        buf = ""
        parts: List[str] = []
        for word in t.split():
            if len(buf) + (1 if buf else 0) + len(word) > 30:
                if buf:
                    parts.append(buf)
                buf = word
            else:
                buf = word if not buf else f"{buf} {word}"
        if buf:
            parts.append(buf)
        out.extend(parts)
    return "\n".join(out)

def _postprocess(text: str) -> str:
    if not text:
        return "…<Press A><Clear Text>"
    text = text.strip()
    # strip code fences/markdown
    text = re.sub(r"^```.*?```$", lambda m: m.group(0).strip("`"), text, flags=re.S)
    text = _strip_forbidden_codes(text)
    text = _trim_lines(text)
    if not text.strip():
        text = "…"
    if ("<Press A>" in text or "\n" in text) and "<Clear Text>" not in text:
        text = f"{text}<Clear Text>"
    return text

