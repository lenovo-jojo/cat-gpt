import os
import json
import openai
from screenshot_util import capture_dolphin_screenshot

# Make sure OpenAI key is loaded from .env
openai.api_key = os.getenv("OPENAI_API_KEY")

# Path to villagers.json (adjust if needed)
VILLAGER_JSON_PATH = "villagers.json"

def clean_villager_name(raw_name: str) -> str:
    """Cleans OCR / Vision output so it becomes a valid villager name."""
    if not raw_name:
        return None

    # Remove punctuation and extra words
    name = raw_name.strip().replace("!", "").replace(".", "").replace(",", "")
    
    # Split words, keep capitalized ones
    parts = name.split()
    caps = [p for p in parts if p[0].isupper()]

    # If OCR returned a sentence like "That looks like Bones"
    if len(caps) >= 1:
        return caps[-1]  # "Bones"

    # If it's a 1-word lowercase name like "bones"
    return name.capitalize()

def identify_from_screenshot() -> dict:
    """
    Takes a screenshot of Dolphin window, sends to GPT-4 Vision,
    returns villager name + dialogue text (if possible).
    """
    screenshot_path = capture_dolphin_screenshot()
    if not screenshot_path:
        return {"error": "no_screenshot"}

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert at reading Animal Crossing screenshots and recognizing characters."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is the villager's name and what are they saying? Reply in JSON with keys 'name' and 'text'."},
                        {"type": "image_url", "image_url": f"file://{os.path.abspath(screenshot_path)}"}
                    ]
                }
            ]
        )
        reply = response.choices[0].message.content
        # Expecting something like: {"name": "Bones", "text": "Hey, how are you yip yip?"}
        data = json.loads(reply)
        return data

    except Exception as e:
        print(f"❌ OCR error: {e}")
        return {"error": "vision_fail"}

def resolve_villager_data(name: str):
    """
    Loads info from villagers.json if available.
    If not found, marks as modded/custom villager.
    """
    try:
        with open(VILLAGER_JSON_PATH, "r", encoding="utf-8") as f:
            villagers = json.load(f)

        if name in villagers:
            return {"name": name, "data": villagers[name], "modded": False}
        else:
            return {"name": name, "modded": True, "data": None}

    except Exception as e:
        print(f"⚠ Could not read villagers.json: {e}")
        return {"name": name, "modded": True, "data": None}

# Example test
if __name__ == "__main__":
    raw = identify_from_screenshot()
    if "name" in raw:
        name = clean_villager_name(raw["name"])
        print("Detected villager:", name)
        info = resolve_villager_data(name)
        print(info)
    else:
        print("No villager detected.", raw)
