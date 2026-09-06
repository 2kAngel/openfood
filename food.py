#!/usr/bin/env python3
"""
food — analyze a food photo via Gemini and get calories + macros.
Reuses the prompt and API format from Fud AI's GeminiService.swift.

Usage:
  python food.py <image.jpg>       (or .png)

Requires:
  export GEMINI_API_KEY="your_key"
"""
import sys, os, json, base64, re, textwrap
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-3.5-flash-lite"   # vision, cheapest current stable (Fud AI default)
MAX_DIM = 1600                      # max longest side (px), same as Fud AI
JPEG_QUALITY = 80                   # same as Fud AI
TIMEOUT = 60                        # seconds

# ── Prompt (adapted from Fud AI GeminiService.swift analyzeFood) ──────────────
ANALYSIS_PROMPT = textwrap.dedent("""\
Analyze this food image. Identify every distinct food item visible and estimate
its nutritional content. The photo may contain multiple foods (e.g. chicken + rice).

Respond ONLY with a JSON object in this exact format, no other text before or after:

{"name":"<overall meal name>","calories":0,"protein":0.0,"carbs":0.0,"fat":0.0,
 "serving_size_grams":0.0,
 "ingredients":[
   {"name":"<food name>","grams":0.0,"calories":0,"protein":0.0,"carbs":0.0,"fat":0.0}
 ]}

Rules:
- name: a short overall description of the meal (e.g. "Chicken and rice plate").
- calories: integer total for the whole visible portion.
- protein, carbs, fat: total grams for the whole visible portion.
- serving_size_grams: estimated total weight in grams of everything visible.
- ingredients: list each distinct food as a separate object.
  * name: the specific food (e.g. "Grilled chicken breast", "White rice").
  * grams: estimated weight of that specific item in grams.
  * calories, protein, carbs, fat: values for that specific item.
  * Ingredient totals must add up approximately to the top-level totals.
- Use only numbers (no text explanations).
- When the image is ambiguous, give your best reasonable estimate.
- Account for visible cooking oils, sauces, or dressings when detectable.
- Distinguish cooked vs raw when possible (e.g. "Cooked white rice").
- Round calories to integers, macros to 1 decimal place.
- Return an empty ingredients list [] if only a single undifferentiated food is visible.
""")

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("\n  GEMINI_API_KEY not set.", file=sys.stderr)
        print("  Run:  export GEMINI_API_KEY=\"your_key\"", file=sys.stderr)
        print("  Get a free key at: https://aistudio.google.com/apikey\n", file=sys.stderr)
        sys.exit(1)
    return key


def encode_image(path: str) -> str:
    """Open image, resize to max 1600px, JPEG 80%, return base64."""
    img = Image.open(path)
    # Convert RGBA/P to RGB (JPEG doesn't support alpha)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > MAX_DIM:
        scale = MAX_DIM / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def call_gemini(api_key: str, image_b64: str, prompt: str) -> str:
    url = f"{GEMINI_BASE}/models/{MODEL}:generateContent"
    body = {
        "contents": [{"parts": [
            {"inlineData": {"mimeType": "image/jpeg", "data": image_b64}},
            {"text": prompt},
        ]}]
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
    }

    # Retry on transient overload (503/529/429), same as Fud AI
    delays = [1, 2, 4]
    for attempt in range(len(delays) + 1):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"\n  Network error: {e}", file=sys.stderr)
            sys.exit(1)

        if resp.status_code == 200:
            data = resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                print("\n  Unexpected API response structure.", file=sys.stderr)
                print(json.dumps(data, indent=2)[:2000], file=sys.stderr)
                sys.exit(1)

        if resp.status_code in (503, 529, 429) and attempt < len(delays):
            import time
            time.sleep(delays[attempt])
            continue

        # Non-retryable error
        msg = ""
        try:
            err = resp.json().get("error", {})
            msg = err.get("message", "") if isinstance(err, dict) else str(err)
        except Exception:
            pass
        print(f"\n  API error (HTTP {resp.status_code}): {msg or resp.text[:500]}", file=sys.stderr)
        sys.exit(1)

    print("\n  API overloaded after retries. Try again later.", file=sys.stderr)
    sys.exit(1)


def extract_json(text: str) -> dict:
    """Extract JSON from model response, stripping markdown fences."""
    cleaned = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if m:
        cleaned = m.group(1).strip()
    # Find first { ... } block
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON found in response:\n{text[:1000]}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : i + 1])
    return json.loads(cleaned[start:])


# ── Display ───────────────────────────────────────────────────────────────────

def display(data: dict):
    ingredients = data.get("ingredients", [])
    total_cal = data.get("calories", 0)
    total_p = data.get("protein", 0.0)
    total_c = data.get("carbs", 0.0)
    total_f = data.get("fat", 0.0)
    total_g = data.get("serving_size_grams", 0.0)

    print()
    if ingredients:
        print(f"  {data.get('name', 'Meal')}")
        print(f"  Total ~{total_g:.0f}g visible")
        print()
        for i, item in enumerate(ingredients, 1):
            name = item.get("name", "?")
            g = item.get("grams", 0)
            cal = item.get("calories", 0)
            p = item.get("protein", 0)
            c = item.get("carbs", 0)
            f = item.get("fat", 0)
            print(f"  {i}. {name}")
            print(f"     ~{g:.0f} g")
            print(f"     ~{cal} kcal")
            print(f"     P: {p:.1f} g   C: {c:.1f} g   F: {f:.1f} g")
            print()
    else:
        name = data.get("name", "Food")
        cal = total_cal
        g = total_g
        p = total_p
        c = total_c
        f = total_f
        print(f"  {name}")
        print(f"  ~{g:.0f} g")
        print(f"  ~{cal} kcal")
        print(f"  P: {p:.1f} g   C: {c:.1f} g   F: {f:.1f} g")
        print()

    print("  ──────────────────────────────────")
    print(f"  TOTAL  ~{total_cal} kcal")
    print(f"  P: {total_p:.1f} g   C: {total_c:.1f} g   F: {total_f:.1f} g")
    print()


# ── Public API ──────────────────────────────────────────────────────────────────

def analyze_image(img_path: str, api_key: str = None) -> dict:
    """Analyze a food image and return nutrition data dict."""
    if api_key is None:
        api_key = load_api_key()
    
    if not os.path.isfile(img_path):
        raise FileNotFoundError(f"Image not found: {img_path}")

    image_b64 = encode_image(img_path)
    raw = call_gemini(api_key, image_b64, ANALYSIS_PROMPT)
    return extract_json(raw)


def format_results(data: dict) -> str:
    """Format nutrition data as human-readable string."""
    ingredients = data.get("ingredients", [])
    total_cal = data.get("calories", 0)
    total_p = data.get("protein", 0.0)
    total_c = data.get("carbs", 0.0)
    total_f = data.get("fat", 0.0)
    total_g = data.get("serving_size_grams", 0.0)

    lines = []
    if ingredients:
        lines.append(f"{data.get('name', 'Meal')}")
        lines.append(f"Total ~{total_g:.0f}g visible")
        lines.append("")
        for i, item in enumerate(ingredients, 1):
            name = item.get("name", "?")
            g = item.get("grams", 0)
            cal = item.get("calories", 0)
            p = item.get("protein", 0)
            c = item.get("carbs", 0)
            f = item.get("fat", 0)
            lines.append(f"{i}. {name}")
            lines.append(f"   ~{g:.0f} g")
            lines.append(f"   ~{cal} kcal")
            lines.append(f"   P: {p:.1f}g  C: {c:.1f}g  F: {f:.1f}g")
            lines.append("")
    else:
        name = data.get("name", "Food")
        cal = total_cal
        g = total_g
        p = total_p
        c = total_c
        f = total_f
        lines.append(f"{name}")
        lines.append(f"~{g:.0f} g")
        lines.append(f"~{cal} kcal")
        lines.append(f"P: {p:.1f}g  C: {c:.1f}g  F: {f:.1f}g")
        lines.append("")

    lines.append("──────────────────")
    lines.append(f"TOTAL  ~{total_cal} kcal")
    lines.append(f"P: {total_p:.1f}g  C: {total_c:.1f}g  F: {total_f:.1f}g")
    return "\n".join(lines)


# ── CLI (kept for backwards compatibility) ──────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python food.py <image.jpg|image.png>", file=sys.stderr)
        sys.exit(1)

    img_path = sys.argv[1]
    api_key = load_api_key()

    print(f"  Encoding {img_path} ...", end=" ", flush=True)
    image_b64 = encode_image(img_path)
    print("ok")

    print(f"  Sending to Gemini ({MODEL}) ...", end=" ", flush=True)
    raw = call_gemini(api_key, image_b64, ANALYSIS_PROMPT)
    print("ok")

    print("  Parsing response ...", end=" ", flush=True)
    data = extract_json(raw)
    print("ok")

    print(format_results(data))


if __name__ == "__main__":
    main()
