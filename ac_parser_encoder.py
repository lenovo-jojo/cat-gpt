#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ac_parser_encoder.py

Animal Crossing (GC) dialogue reader/generator/writer with:
- dolphin-window-only screenshots (Windows)
- vision image passed to the model every generation
- memory + gossip preserved
- light sanitizer to avoid charset warnings

Requires:
  - dialogue_prompt.py  (already patched to use image_url data URLs)
  - screenshot_util.py  (the Dolphin-window grabber we set up)
  - memory_ipc.py       (your Dolphin mem bridge)
  - gossip.py           (optional; guarded by ENABLE_GOSSIP)
  - screenshot_util.screenshot_dolphin_window() must exist.

Environment (example):
  OPENAI_API_KEY=...
  MODEL=gpt-4o-mini
  TEMPERATURE=0.7
  ENABLE_GOSSIP=1
  ENABLE_SCREENSHOT=1
  GENERATION_SUPPRESS_SECONDS=2
"""

import argparse
import os
import re
import struct
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime

import memory_ipc
from dialogue_prompt import generate_dialogue, generate_spotlight_dialogue
from gossip import seed_if_needed, spread, observe_interaction, get_context_for

# 👇 NEW: window-targeted screenshot (returns PIL.Image or None)
from screenshot_util import screenshot_dolphin_window

# --- Configuration ---
TARGET_ADDRESS = 0x81298360
MAX_READ_SIZE = 8192
READ_SIZE = 512
PREFIX_BYTE = 0x7F

# Cooldown after writing generated dialogue to avoid mid-read overwrites
SUPPRESS_SECONDS = float(os.environ.get("GENERATION_SUPPRESS_SECONDS", "25"))

# --- Data from Decompilation ---

# 1. Character Maps
CHARACTER_MAP = {
    0x00:"¡", 0x01:"¿", 0x02:"Ä", 0x03:"À", 0x04:"Á", 0x05:"Â", 0x06:"Ã", 0x07:"Å", 0x08:"Ç", 0x09:"È", 0x0A:"É",
    0x0B:"Ê", 0x0C:"Ë", 0x0D:"Ì", 0x0E:"Í", 0x0F:"Î", 0x10:"Ï", 0x11:"Ð", 0x12:"Ñ", 0x13:"Ò", 0x14:"Ó", 0x15:"Ô",
    0x16:"Õ", 0x17:"Ö", 0x18:"Ø", 0x19:"Ù", 0x1A:"Ú", 0x1B:"Û", 0x1C:"Ü", 0x1D:"ß", 0x1E:"\u00de", 0x1F:"à",
    0x20:" ", 0x21:"!", 0x22:"\"", 0x23:"á", 0x24:"â", 0x25:"%", 0x26:"&", 0x27:"'", 0x28:"(", 0x29:")", 0x2A:"~",
    0x2B:"♥", 0x2C:",", 0x2D:"-", 0x2E:".", 0x2F:"♪", 0x30:"0", 0x31:"1", 0x32:"2", 0x33:"3", 0x34:"4", 0x35:"5",
    0x36:"6", 0x37:"7", 0x38:"8", 0x39:"9", 0x3A:":", 0x3B:"🌢", 0x3C:"<", 0x3D:"=", 0x3E:">", 0x3F:"?", 0x40:"@",
    0x41:"A", 0x42:"B", 0x43:"C", 0x44:"D", 0x45:"E", 0x46:"F", 0x47:"G", 0x48:"H", 0x49:"I", 0x4A:"J", 0x4B:"K",
    0x4C:"L", 0x4D:"M", 0x4E:"N", 0x4F:"O", 0x50:"P", 0x51:"Q", 0x52:"R", 0x53:"S", 0x54:"T", 0x55:"U", 0x56:"V",
    0x57:"W", 0x58:"X", 0x59:"Y", 0x5A:"Z", 0x5B:"ã", 0x5C:"💢", 0x5D:"ä", 0x5E:"å", 0x5F:"_", 0x60:"ç", 0x61:"a",
    0x62:"b", 0x63:"c", 0x64:"d", 0x65:"e", 0x66:"f", 0x67:"g", 0x68:"h", 0x69:"i", 0x6A:"j", 0x6B:"k", 0x6C:"l",
    0x6D:"m", 0x6E:"n", 0x6F:"o", 0x70:"p", 0x71:"q", 0x72:"r", 0x73:"s", 0x74:"t", 0x75:"u", 0x76:"v", 0x77:"w",
    0x78:"x", 0x79:"y", 0x7A:"z", 0x7B:"è", 0x7C:"é", 0x7D:"ê", 0x7E:"ë", 0x81:"ì", 0x82:"í", 0x83:"î", 0x84:"ï",
    0x85:"•", 0x86:"ð", 0x87:"ñ", 0x88:"ò", 0x89:"ó", 0x8A:"ô", 0x8B:"õ", 0x8C:"ö", 0x8D:"⁰", 0x8E:"ù", 0x8F:"ú",
    0x90:"ー", 0x91:"û", 0x92:"ü", 0x93:"ý", 0x94:"ÿ", 0x95:"\u00fe", 0x96:"Ý", 0x97:"¦", 0x98:"§", 0x99:"a̱",
    0x9A:"o̱", 0x9B:"‖", 0x9C:"µ", 0x9D:"³", 0x9E:"²", 0x9F:"¹", 0xA0:"¯", 0xA1:"¬", 0xA2:"Æ", 0xA3:"æ", 0xA4:"„",
    0xA5:"»", 0xA6:"«", 0xA7:"☀", 0xA8:"☁", 0xA9:"☂", 0xAA:"🌬", 0xAB:"☃", 0xAE:"/", 0xAF:"∞", 0xB0:"○", 0xB1:"🗙",
    0xB2:"□", 0xB3:"△", 0xB4:"+", 0xB5:"⚡", 0xB6:"♂", 0xB7:"♀", 0xB8:"🍀", 0xB9:"★", 0xBA:"💀", 0xBB:"😮", 0xBC:"😄",
    0xBD:"😣", 0xBE:"😠", 0xBF:"😃", 0xC0:"×", 0xC1:"÷", 0xC2:"🔨", 0xC3:"🎀", 0xC4:"✉", 0xC5:"💰", 0xC6:"🐾",
    0xC7:"🐶", 0xC8:"🐱", 0xC9:"🐰", 0xCA:"🐦", 0xCB:"🐮", 0xCC:"🐷", 0xCD:"\n", 0xCE:"🐟", 0xCF:"🐞", 0xD0:";", 0xD1:"#",
}
REVERSE_CHARACTER_MAP = {v: k for k, v in CHARACTER_MAP.items()}

# 2. Control Codes Maps
CONTROL_CODES = {
    0x00: "<End Conversation>", 0x01: "<Continue>", 0x02: "<Clear Text>", 0x03: "<Pause [{:02X}]>", 0x04: "<Press A>",
    0x05: "<Color Line [{:06X}]>", 0x06: "<Instant Skip>", 0x07: "<Unskippable>", 0x08: "<Player Emotion [{:02X}] [{}]>",
    0x09: "<NPC Expression [Cat:{:02X}] [{}]>", 0x0A: "<Set Demo Order [{:02X}, {:02X}, {:02X}]>", 0x0B: "<Set Demo Order [{:02X}, {:02X}, {:02X}]>",
    0x0C: "<Set Demo Order [{:02X}, {:02X}, {:02X}]>", 0x0D: "<Open Choice Menu>", 0x0E: "<Set Jump [{:04X}]>",
    0x0F: "<Choice 1 Jump [{:04X}]>", 0x10: "<Choice 2 Jump [{:04X}]>", 0x11: "<Choice 3 Jump [{:04X}]>",
    0x12: "<Choice 4 Jump [{:04X}]>", 0x13: "<Rand Jump 2 [{:04X}, {:04X}]>", 0x14: "<Rand Jump 3 [{:04X}, {:04X}, {:04X}]>",
    0x15: "<Rand Jump 4 [{:04X}, {:04X}, {:04X}, {:04X}]>", 0x16: "<Set 2 Choices [{:04X}, {:04X}]>",
    0x17: "<Set 3 Choices [{:04X}, {:04X}, {:04X}]>", 0x18: "<Set 4 Choices [{:04X}, {:04X}, {:04X}, {:04X}]>",
    0x19: "<Force Dialog Switch>", 0x1A: "<Player Name>", 0x1B: "<NPC Name>", 0x1C: "<Catchphrase>", 0x1D: "<Year>",
    0x1E: "<Month>", 0x1F: "<Day of Week>", 0x20: "<Day>", 0x21: "<Hour>", 0x22: "<Minute>", 0x23: "<Second>",
    0x24: "<String 0>", 0x25: "<String 1>", 0x26: "<String 2>", 0x27: "<String 3>", 0x28: "<String 4>",
    0x2F: "<Town Name>", 0x50: "<Color [{:06X}] for [{:02X}] chars>", 0x53: "<Line Type [{:02X}]>", 0x54: "<Char Size [{:04X}]>",
    0x56: "<Play Music [{}] [{}]>", 0x57: "<Stop Music [{}] [{}]>", 0x59: "<Play Sound Effect [{}]>", 0x5A: "<Line Size [{:04X}]>",
    0x76: "<AM/PM>", 0x4C: "<Angry Voice>",
}
REVERSE_CONTROL_CODES = {re.sub(r'\[.*?\]', '[{}]', v): k for k, v in CONTROL_CODES.items()}
REVERSE_CONTROL_CODES.update({
    "<NPC Expression [{}] [{}]>": 0x09,
    "<Player Emotion [{}] [{}]>": 0x08,
})

GLOBAL_GENERATION_LOCK = threading.Lock()

FEELING_CHATTY_LABEL = "Feeling chatty"
_CONTROL_TAG_RE = re.compile(r"<[^>]+>")
_CHOICE_ONE_PATTERN = re.compile(
    r"(<Open Choice Menu>)([\s\S]*?)(<Choice 1 Jump \[[0-9A-F]{4}\]>)",
    re.IGNORECASE,
)


def _strip_control_codes(text: str) -> str:
    return _CONTROL_TAG_RE.sub("", text)


def _inject_feeling_chatty_option(text: str) -> Optional[str]:
    def _replacement(match: re.Match) -> str:
        between = match.group(2)
        leading_ws_match = re.match(r"^\s*", between)
        trailing_ws_match = re.search(r"\s*$", between)
        leading_ws = leading_ws_match.group(0) if leading_ws_match else ""
        trailing_ws = trailing_ws_match.group(0) if trailing_ws_match else ""
        return (
            f"{match.group(1)}"
            f"{leading_ws}{FEELING_CHATTY_LABEL}{trailing_ws}"
            f"{match.group(3)}"
        )

    if not _CHOICE_ONE_PATTERN.search(text):
        return None
    return _CHOICE_ONE_PATTERN.sub(_replacement, text, count=1)


@dataclass
class ConversationState:
    lines_seen: int = 0
    last_visible_text: Optional[str] = None
    ready_for_chatty: bool = False
    menu_injected: bool = False
    awaiting_choice_resolution: bool = False
    chatty_requested: bool = False
    menu_skip_logged: bool = False

    def reset(self) -> None:
        self.lines_seen = 0
        self.last_visible_text = None
        self.ready_for_chatty = False
        self.menu_injected = False
        self.awaiting_choice_resolution = False
        self.chatty_requested = False
        self.menu_skip_logged = False

    def observe_text(self, text: str) -> None:
        if "<End Conversation>" in text:
            self.reset()
            return

        if self.awaiting_choice_resolution and "<Open Choice Menu>" not in text:
            self.awaiting_choice_resolution = False
            self.menu_injected = False
            self.menu_skip_logged = False
            visible_followup = _strip_control_codes(text).strip()
            if visible_followup:
                self.chatty_requested = True
                if visible_followup != self.last_visible_text:
                    self.last_visible_text = visible_followup
                    self.lines_seen += 1
                    if self.lines_seen >= 2:
                        self.ready_for_chatty = True
            return

        if "<Open Choice Menu>" in text:
            if not self.ready_for_chatty and self.lines_seen >= 1:
                self.ready_for_chatty = True
            return

        visible = _strip_control_codes(text).strip()
        if not visible:
            return

        if visible != self.last_visible_text:
            self.last_visible_text = visible
            self.lines_seen += 1
            if self.lines_seen >= 2:
                self.ready_for_chatty = True
            self.menu_skip_logged = False

CODE_ARG_COUNT = {
    0x03: 1, 0x05: 3, 0x08: 3, 0x09: 3, 0x0A: 3, 0x0B: 3, 0x0C: 3, 0x0E: 2, 0x0F: 2, 0x10: 2, 0x11: 2, 0x12: 2,
    0x13: 4, 0x14: 6, 0x15: 8, 0x16: 4, 0x17: 6, 0x18: 8, 0x50: 4, 0x53: 1, 0x54: 2, 0x56: 2, 0x57: 2, 0x59: 1, 0x5A: 2,
}

EXPRESSION_MAP = {
    0x00: "None?", 0x01: "Glare", 0x02: "Shocked", 0x03: "Laugh", 0x04: "Surprised",
    0x05: "Angry", 0x06: "Excited", 0x07: "Worried", 0x08: "Scared", 0x09: "Cry",
    0x0A: "Happy", 0x0B: "Wondering", 0x0C: "Idea", 0x0D: "Sad", 0x0E: "Happy Dance",
    0x0F: "Thinking", 0x10: "Depressed", 0x11: "Heartbroken", 0x12: "Sinister",
    0x13: "Tired", 0x14: "Love", 0x15: "Smile", 0x16: "Scowl", 0x17: "Frown",
    0x18: "Laughing (Sitting)", 0x19: "Shocked (Sitting)", 0x1A: "Idea (Sitting)",
    0x1B: "Surprised (Sitting)", 0x1C: "Angry (Sitting)", 0x1D: "Smile (Sitting)",
    0x1E: "Frown (Sitting)", 0x1F: "Wondering (Sitting)", 0x20: "Salute",
    0x21: "Angry (Resetti)", 0x22: "Reset Expressions (Resetti)", 0x23: "Sad (Resetti)",
    0x24: "Excitement (Resetti)", 0x25: "Jaw Drop (Resetti)", 0x26: "Annoyed (Resetti)",
    0x27: "Furious (Resetti)", 0x28: "Surprised (K.K.)", 0x29: "Fortune",
    0x2A: "Smile (Resetti)", 0xFD: "Reset Expressions (K.K.)",
    0xFE: "Reset Expressions (Sitting)", 0xFF: "Reset Expressions"
}

MUSIC_TRANSITIONS = {0x00: "None", 0x01: "Undetermined", 0x02: "Fade"}
SOUNDEFFECT_LIST = {
    0x00: "Bell Transaction", 0x01: "Happy", 0x02: "Very Happy",
    0x03: "Variable 0", 0x04: "Variable 1", 0x05: "Annoyed",
    0x06: "Thunder", 0x07: "None"
}
MUSIC_LIST = {
    0x00: "Silence", 0x01: "Arriving in Town", 0x02: "House Selection",
    0x03: "House Selected", 0x04: "House Selected (2)", 0x05: "Resetti",
    0x06: "Current Hourly Music", 0x07: "Resetti (2)", 0x08: "Don Resetti"
}
PLAYER_EMOTIONS = {0x02: "Surprised", 0xFD: "Purple Mist", 0xFE: "Scared", 0xFF: "Reset Emotion"}

# --- Helpers: normalization/sanitization -------------------------------------

def _normalize_control_tags(text: str) -> str:
    def two_hex(m): return f"{m.group(1)} [{m.group(2).upper().zfill(2)}]>"
    def four_hex(m): return f"{m.group(1)} [{m.group(2).upper().zfill(4)}]>"
    text = re.sub(r"</[^>]+>", "", text)
    text = re.sub(
        r"<NPC\s+Expression\s+\[?(?:Cat:)?([0-9A-Fa-f]{1,2})\]?\s+\[?([0-9A-Fa-f]{1,4})\]?>",
        lambda m: f"<NPC Expression [{m.group(1).upper().zfill(2)}] [{m.group(2).upper().zfill(4)}]>", text
    )
    text = re.sub(
        r"<Player\s+Emotion\s+\[?([0-9A-Fa-f]{1,2})\]?\s+\[?([0-9A-Fa-f]{1,4})\]?>",
        lambda m: f"<Player Emotion [{m.group(1).upper().zfill(2)}] [{m.group(2).upper().zfill(4)}]>", text
    )
    text = re.sub(r"<(Pause)\s+([0-9A-Fa-f]{1,2})>", lambda m: f"<Pause [{m.group(2).upper().zfill(2)}]>", text)
    text = re.sub(r"<(Line Type)\s+([0-9A-Fa-f]{1,2})>", lambda m: f"<Line Type [{m.group(2).upper().zfill(2)}]>", text)
    text = re.sub(r"<(Play Sound Effect)\s+([0-9A-Fa-f]{1,2})>", lambda m: f"<Play Sound Effect [{m.group(2).upper().zfill(2)}]>", text)
    text = re.sub(r"<(Char Size)\s+([0-9A-Fa-f]{1,4})>", lambda m: f"<Char Size [{m.group(2).upper().zfill(4)}]>", text)
    text = re.sub(r"<(Line Size)\s+([0-9A-Fa-f]{1,4})>", lambda m: f"<Line Size [{m.group(2).upper().zfill(4)}]>", text)
    text = re.sub(
        r"<Color\s+\[?([0-9A-Fa-f]{6})\]?\s+for\s+\[?([0-9A-Fa-f]{1,2})\]?>",
        lambda m: f"<Color [{m.group(1).upper()}] for [{m.group(2).upper().zfill(2)}] chars>", text
    )
    text = re.sub(
        r"<Color\s+\[?([0-9A-Fa-f]{6})\]?\s+for\s+\[?([0-9A-Fa-f]{1,2})\]?\s+chars?>",
        lambda m: f"<Color [{m.group(1).upper()}] for [{m.group(2).upper().zfill(2)}] chars>", text
    )
    text = re.sub(r"<Color\s+Line\s+\[?([0-9A-Fa-f]{6})\]?>",
                  lambda m: f"<Color Line [{m.group(1).upper()}]>", text)
    text = re.sub(r"<Color\s+([0-9A-Fa-f]{6})>", lambda m: f"<Color Line [{m.group(1).upper()}]>", text)
    text = re.sub(r"<Color\s+\[([0-9A-Fa-f]{6})\]>", lambda m: f"<Color Line [{m.group(1).upper()}]>", text)
    return text

def _normalize_visible_text(text: str) -> str:
    replacements = {
        "\u2019": "'", "\u2018": "'", "\u201C": '"', "\u201D": '"',
        "\u2014": "-", "\u2013": "-", "\u2026": "...", "\u00A0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text

def _sanitize_for_charset(text: str) -> str:
    """
    Remove or replace characters not present in REVERSE_CHARACTER_MAP.
    Keeps newlines, basic punctuation, and ASCII; drops stray emoji.
    """
    out = []
    for ch in text:
        if ch == "\n" or ch in REVERSE_CHARACTER_MAP:
            out.append(ch)
            continue
        # ascii safe?
        if 32 <= ord(ch) < 127:
            out.append(ch)
            continue
        # otherwise drop
        # (you could also map 🌼->* etc if you want)
    return "".join(out)

# --- Parsing/encoding ---------------------------------------------------------

def parse_ac_text(data: bytes) -> str:
    text_buffer = []
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == 0x00:
            break
        if byte == PREFIX_BYTE:
            i += 1
            if i >= len(data): break
            command = data[i]
            if command == 0x00:
                text_buffer.append(CONTROL_CODES[command])
                break
            desc = CONTROL_CODES.get(command, f"<Code 0x{command:02X}>")
            num_args = CODE_ARG_COUNT.get(command, 0)
            if num_args > 0:
                args_bytes = data[i+1 : i+1+num_args]
                args_tuple = []
                if len(args_bytes) < num_args:
                    text_buffer.append(f"<Malformed Code 0x{command:02X}>")
                    i += 1 + len(args_bytes)
                    continue
                if command in [0x08, 0x09]:  # 1B + 2B
                    first_arg = args_bytes[0]
                    val = struct.unpack('>H', args_bytes[1:3])[0]
                    if command == 0x09:
                        name = EXPRESSION_MAP.get(val, f"Unknown_{val:04X}")
                    else:
                        name = PLAYER_EMOTIONS.get(val, f"Unknown_Emotion_{val:04X}")
                    args_tuple.extend([first_arg, name])
                elif command in [0x56, 0x57]:  # 1B + 1B
                    music_id = args_bytes[0]
                    transition_type = args_bytes[1]
                    music_name = MUSIC_LIST.get(music_id, f"Unknown_Music_{music_id:02X}")
                    transition_name = MUSIC_TRANSITIONS.get(transition_type, f"Unknown_Transition_{transition_type:02X}")
                    args_tuple.extend([music_name, transition_name])
                elif num_args == 1:
                    if command == 0x59:
                        sound_id = args_bytes[0]
                        sound_name = SOUNDEFFECT_LIST.get(sound_id, f"Unknown_Sound_{sound_id:02X}")
                        args_tuple.append(sound_name)
                    else:
                        args_tuple.append(args_bytes[0])
                elif num_args == 2:
                    args_tuple.append(struct.unpack('>H', args_bytes)[0])
                elif num_args == 3 and command == 0x05:
                    args_tuple.append(int.from_bytes(args_bytes, 'big'))
                elif num_args == 3:
                    args_tuple.extend([args_bytes[0], args_bytes[1], args_bytes[2]])
                elif num_args == 4 and command == 0x50:
                    args_tuple.extend([int.from_bytes(args_bytes[0:3], 'big'), args_bytes[3]])
                else:
                    for j in range(0, num_args, 2):
                        args_tuple.append(struct.unpack('>H', args_bytes[j:j+2])[0])
                try:
                    text_buffer.append(desc.format(*args_tuple))
                except (TypeError, IndexError):
                    text_buffer.append(desc)
                i += num_args
            else:
                text_buffer.append(desc)
            i += 1
            continue
        char = CHARACTER_MAP.get(byte, f"[?{byte:02X}]")
        text_buffer.append(char)
        i += 1
    return "".join(text_buffer)

def encode_ac_text(text: str) -> bytes:
    encoded = bytearray()
    # normalize + sanitize
    text = _sanitize_for_charset(_normalize_visible_text(_normalize_control_tags(text)))
    tokens = re.split(r'(<[^>]+>)', text)
    char_count = 0
    for token in tokens:
        if not token: continue
        if token.startswith('<') and token.endswith('>'):
            arg_pattern = re.compile(r'\[[^\]]*?([0-9a-fA-F]{1,6})\]')
            args = [int(arg, 16) for arg in arg_pattern.findall(token)]
            base_tag = re.sub(r'\[.*?\]', '[{}]', token)
            command_byte = REVERSE_CONTROL_CODES.get(base_tag)
            if command_byte is not None:
                encoded.append(PREFIX_BYTE)
                encoded.append(command_byte)
                num_args_expected = CODE_ARG_COUNT.get(command_byte, 0)
                if num_args_expected > 0:
                    arg_bytes = bytearray()
                    if num_args_expected == 1:
                        arg_bytes.extend(struct.pack('>B', args[0]))
                    elif num_args_expected == 2:
                        arg_bytes.extend(struct.pack('>H', args[0]))
                    elif num_args_expected == 3 and command_byte == 0x05:
                        arg_bytes.extend(args[0].to_bytes(3, 'big'))
                    elif num_args_expected == 3 and command_byte in (0x08, 0x09):
                        arg_bytes.extend(struct.pack('>B', args[0]))
                        arg_bytes.extend(struct.pack('>H', args[1]))
                    elif num_args_expected == 4 and command_byte == 0x50:
                        arg_bytes.extend(args[0].to_bytes(3, 'big'))
                        arg_bytes.extend(struct.pack('>B', args[1]))
                    else:
                        for arg in args:
                            arg_bytes.extend(struct.pack('>H', arg))
                    encoded.extend(arg_bytes)
            else:
                print(f"Warning: Unknown tag '{token}'")
        else:
            words = token.split(' ')
            for word_idx, word in enumerate(words):
                word_length = len(word)
                space_needed = 1 if word_idx > 0 and char_count > 0 else 0
                if char_count > 0 and char_count + space_needed + word_length > 30:
                    encoded.append(0xCD)  # newline
                    char_count = 0
                    space_needed = 0
                if space_needed > 0:
                    encoded.append(0x20)
                    char_count += 1
                for char in word:
                    byte_val = REVERSE_CHARACTER_MAP.get(char)
                    if byte_val is not None:
                        encoded.append(byte_val)
                        if char == '\n':
                            char_count = 0
                        else:
                            char_count += 1
                    else:
                        # already sanitized; shouldn't hit here often
                        pass
    encoded.append(0x00)
    return bytes(encoded)

# --- Start menu matcher (stubbed false by design here) -----------------------

START_MENU_TIME_REGEXES = []
def is_start_menu_time_announcement(text: str) -> bool:
    return False

# --- Memory read/write helpers -----------------------------------------------

def write_dialogue_to_address(dialogue: str, target_address: int) -> bool:
    wrote = memory_ipc.write_memory(target_address, b"")
    if wrote is False:
        if not memory_ipc.connect():
            print("❌ Connection failed. Is the game running?")
            return False
    encoded_bytes = encode_ac_text(dialogue)
    return memory_ipc.write_memory(target_address, encoded_bytes)

def _read_dialogue_once(target_address: int, end_markers: List[bytes], max_size: int, chunk_size: int) -> bytes:
    full_data = bytearray()
    for i in range(0, max_size, chunk_size):
        chunk = memory_ipc.read_memory(target_address + i, chunk_size)
        if not chunk:
            break
        full_data.extend(chunk)
        if any(marker in chunk for marker in end_markers):
            break
    return bytes(full_data)

def get_current_speaker() -> Optional[str]:
    raw_bytes = memory_ipc.read_memory(0x8129A3EA, 32)
    if not raw_bytes or all(b == 0 for b in raw_bytes):
        return None
    candidate = raw_bytes.split(b"\x00", 1)[0]
    for idx, byte in enumerate(candidate):
        if byte < 0x20 or byte == 0x7F:
            candidate = candidate[:idx]
            break
    try:
        speaker = candidate.decode("utf-8", errors="ignore")
    except Exception:
        return None
    import re as _re
    speaker = _re.sub(r"[\x00-\x1F\x7F]+$", "", speaker).rstrip()
    return speaker or None

# --- Screenshot helpers -------------------------------------------------------

def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _take_dolphin_window_screenshot() -> Optional[str]:
    """
    Focuses the Dolphin AC window and captures that window only.
    Returns saved file path or None.
    """
    try:
        img = screenshot_dolphin_window()
        if img is None:
            return None
        _ensure_dir("screenshots")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = os.path.join("screenshots", f"AC_{ts}.png")
        img.save(out_path)
        print(f"📷 Saved screenshot: {out_path}")
        return out_path
    except Exception as e:
        print(f"⚠ screenshot failed: {e}")
        return None

# --- Main watch loop ----------------------------------------------------------

def watch_dialogue(
    addresses: List[int],
    per_read_size: int,
    interval_s: float,
    print_all: bool,
    include_speaker: bool,
) -> None:
    if not memory_ipc.connect():
        sys.exit(1)

    last_text_by_addr: Dict[int, Optional[str]] = {addr: None for addr in addresses}
    generation_in_progress: Dict[int, bool] = {addr: False for addr in addresses}
    suppress_until_by_addr: Dict[int, float] = {addr: 0.0 for addr in addresses}
    conversation_state: Dict[int, ConversationState] = {addr: ConversationState() for addr in addresses}
    seen_characters = set()
    enable_screenshot = os.environ.get("ENABLE_SCREENSHOT", "0") == "1"
    enable_gossip = os.environ.get("ENABLE_GOSSIP", "0") == "1"

    try:
        while True:
            try:
                current_speaker = get_current_speaker()
            except Exception:
                current_speaker = None

            if current_speaker is not None:
                seen_characters.add(current_speaker)

            if seen_characters and enable_gossip:
                try:
                    villager_list = sorted(seen_characters)
                    seed_if_needed(villager_list)
                    spread(villager_list)
                except Exception:
                    pass

            for addr in addresses:
                raw = memory_ipc.read_memory(addr, per_read_size)
                if not raw:
                    continue
                text = parse_ac_text(raw)

                if print_all or text != last_text_by_addr[addr]:
                    state = conversation_state[addr]
                    state.observe_text(text)

                    now_ts = time.time()
                    if now_ts < suppress_until_by_addr.get(addr, 0.0):
                        if "<End Conversation>" in text:
                            suppress_until_by_addr[addr] = 0.0
                            state.reset()
                        else:
                            last_text_by_addr[addr] = text
                        continue

                    if (
                        state.ready_for_chatty
                        and "<Open Choice Menu>" in text
                        and not state.menu_injected
                    ):
                        modified = _inject_feeling_chatty_option(text)
                        if modified and modified != text:
                            predicted = parse_ac_text(encode_ac_text(modified))
                            if write_dialogue_to_address(modified, addr):
                                print("✨ Injected 'Feeling chatty' option into choice menu.")
                                state.menu_injected = True
                                state.awaiting_choice_resolution = True
                                text = predicted
                                last_text_by_addr[addr] = predicted
                                header = f"Address 0x{addr:08X}"
                                if include_speaker:
                                    try:
                                        speaker = get_current_speaker()
                                        header += f" | Speaker: {speaker}"
                                    except Exception:
                                        pass
                                print("Did generate: False")
                                print(f"\n--- {header} ---")
                                print(text)
                                continue
                    elif (
                        "<Open Choice Menu>" in text
                        and not state.menu_injected
                        and not state.ready_for_chatty
                        and not state.menu_skip_logged
                    ):
                        print(
                            "ℹ️ Skipping 'Feeling chatty' injection: "
                            f"lines_seen={state.lines_seen}, "
                            f"awaiting_choice_resolution={state.awaiting_choice_resolution}, "
                            f"chatty_requested={state.chatty_requested}"
                        )
                        state.menu_skip_logged = True

                    did_generate = False
                    should_generate = state.chatty_requested and not state.awaiting_choice_resolution

                    if (
                        should_generate
                        and not generation_in_progress.get(addr, False)
                        and not GLOBAL_GENERATION_LOCK.locked()
                    ):
                        state.chatty_requested = False
                        generation_in_progress[addr] = True

                        initial_text = text
                        current_speaker_for_gen: Optional[str] = None
                        if include_speaker:
                            try:
                                current_speaker_for_gen = get_current_speaker()
                            except Exception:
                                current_speaker_for_gen = None

                        loading_text = ".<Pause [0A]>.<Pause [0A]>.<Pause [0A]><Press A><Clear Text>"

                        with GLOBAL_GENERATION_LOCK:
                            write_dialogue_to_address(loading_text, addr)

                            image_paths = None
                            if enable_screenshot:
                                time.sleep(0.15)
                                shot = _take_dolphin_window_screenshot()
                                if shot:
                                    image_paths = [shot]

                            gossip_ctx = None
                            if enable_gossip and current_speaker_for_gen:
                                try:
                                    observe_interaction(current_speaker_for_gen, villager_names=sorted(seen_characters))
                                    gossip_ctx = get_context_for(
                                        current_speaker_for_gen, villager_names=sorted(seen_characters)
                                    )
                                except Exception:
                                    gossip_ctx = None

                            try:
                                if is_start_menu_time_announcement(initial_text) and current_speaker_for_gen:
                                    llm_text = generate_spotlight_dialogue(
                                        current_speaker_for_gen, image_paths=image_paths, gossip_context=gossip_ctx
                                    )
                                elif current_speaker_for_gen:
                                    llm_text = generate_dialogue(
                                        current_speaker_for_gen, image_paths=image_paths, gossip_context=gossip_ctx
                                    )
                                else:
                                    llm_text = generate_dialogue(
                                        "Ace", image_paths=image_paths, gossip_context=gossip_ctx
                                    )

                                combined = llm_text
                                write_dialogue_to_address(combined, addr)

                                encoded_combined = encode_ac_text(combined)
                                predicted = parse_ac_text(encoded_combined)
                                last_text_by_addr[addr] = predicted

                                suppress_until_by_addr[addr] = time.time() + SUPPRESS_SECONDS
                                did_generate = True
                            except Exception as e:
                                print(f"⚠ generation error: {e}")
                            finally:
                                generation_in_progress[addr] = False
                                state.menu_injected = False
                                state.awaiting_choice_resolution = False

                    print(f"Did generate: {did_generate}")
                    header = f"Address 0x{addr:08X}"
                    if include_speaker:
                        try:
                            speaker = get_current_speaker()
                            header += f" | Speaker: {speaker}"
                        except Exception:
                            pass
                    print(f"\n--- {header} ---")
                    print(text)
                    if not did_generate:
                        last_text_by_addr[addr] = text
                        if "<End Conversation>" in text:
                            state.reset()
                        elif not state.awaiting_choice_resolution:
                            state.chatty_requested = False

            time.sleep(max(0.0, interval_s))
    except KeyboardInterrupt:
        return

# --- One-shot mode ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse current dialogue and generate new dialogue; optionally write with -w.")
    parser.add_argument("-w", "--write", action="store_true", help="Write the generated dialogue to memory (default: print only)")
    parser.add_argument("--watch", action="store_true", help="Continuously read and scan dialogue blocks in a loop")
    parser.add_argument("--interval", type=float, default=0.10, help="Seconds between reads in watch mode (default: 0.10)")
    parser.add_argument("--size", type=int, default=READ_SIZE, help="Bytes to read per iteration in watch mode (default: READ_SIZE)")
    parser.add_argument("--addresses", nargs="*", type=lambda x: int(x, 0), help="Optional list of addresses (hex or int) to watch. Defaults to TARGET_ADDRESS")
    parser.add_argument("--print-all", action="store_true", help="In watch mode, print on every tick (default: only when text changes)")
    parser.add_argument("--dump", action="store_true", help="In one-shot mode, also hex dump the bytes read")
    args = parser.parse_args()

    if args.watch:
        addrs = [TARGET_ADDRESS]
        watch_dialogue(addrs, max(32, min(args.size, MAX_READ_SIZE)), max(0.0, args.interval), args.print_all, include_speaker=True)
        return

    print(f"▶ Reading from address 0x{TARGET_ADDRESS:08X} until end marker is found...")
    if not memory_ipc.connect():
        sys.exit(1)

    end_markers = [bytes([PREFIX_BYTE, 0x00]), bytes([PREFIX_BYTE, 0x0D])]
    raw_data = _read_dialogue_once(TARGET_ADDRESS, end_markers, MAX_READ_SIZE, 256)
    if not raw_data:
        print("❌ Failed to read memory.")
        sys.exit(1)

    print(f"\n--- Read {len(raw_data)} bytes in total ---")
    if args.dump:
        print("\n--- Raw Hex Dump ---")
        memory_ipc.dump(TARGET_ADDRESS, len(raw_data))

    parsed_text = parse_ac_text(raw_data)
    print("\n--- 💎 Final Parsed Dialogue 💎 ---")
    print(parsed_text)
    print("\n✅ Done.")

    if args.write:
        current_speaker = get_current_speaker()
        fallback_speaker = current_speaker or "Ace"

        image_paths = None
        if os.environ.get("ENABLE_SCREENSHOT", "0") == "1":
            shot = _take_dolphin_window_screenshot()
            if shot:
                image_paths = [shot]

        gossip_ctx = None
        if os.environ.get("ENABLE_GOSSIP", "0") == "1":
            try:
                if current_speaker:
                    observe_interaction(current_speaker)
                gossip_ctx = get_context_for(current_speaker or fallback_speaker)
            except Exception:
                gossip_ctx = None

        if is_start_menu_time_announcement(parsed_text) and current_speaker:
            dialogue = generate_spotlight_dialogue(current_speaker, image_paths=image_paths, gossip_context=gossip_ctx)
        else:
            dialogue = generate_dialogue(fallback_speaker, image_paths=image_paths, gossip_context=gossip_ctx)

        print("\n--- 🧠 Generated Dialogue ---")
        print(dialogue)
        ok = write_dialogue_to_address(dialogue, TARGET_ADDRESS)
        if ok:
            print("\n💾 Wrote generated dialogue to memory successfully.")
        else:
            print("\n❌ Failed to write generated dialogue to memory.")

if __name__ == "__main__":
    main()



