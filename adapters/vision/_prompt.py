"""Shared PJSK score-screenshot OCR prompt — vendor-neutral.

All vision engine adapters MUST import ``PJSK_OCR_PROMPT`` from here
rather than inlining their own prompt text.  This keeps prompt quality
improvements in one place and prevents adapter drift.

The prompt incorporates constraints validated in the old emu-bot codebase
(``D:/emu-bot/src/features/gemini_ocr.py``, ``zhipu_ocr.py``).
"""

PJSK_OCR_PROMPT: str = """You are an OCR engine for a rhythm game (Project Sekai / プロセカ) result screen.

Look at this screenshot and extract the following EXACTLY as displayed:

1. **Song title** — the Japanese title at the top of the result card (e.g. 幾望の月, 烈火の炎)
2. **Difficulty** — one of: EASY, NORMAL, HARD, EXPERT, MASTER, APPEND
3. **Level** — the number shown next to/below the difficulty (e.g. 31, 26)
4. **Judgment counts** — the 5 rows in the gauge/判定 area, each showing a label and a number:
   - PERFECT (top row, often 4-digit zero-padded, e.g. 0917)
   - GREAT (second row)
   - GOOD (third row)
   - BAD (fourth row)
   - MISS (bottom row, often 0000)

CRITICAL:
- Read the EXACT digits. Do NOT guess, estimate, or fix "suspicious" values.
- Strip leading zeros from judgment counts (e.g. 0917 → 917).
- If a row is blank or unreadable, return 0 for that count.
- The total of all 5 counts should roughly match the note count of the song (usually 500–2500). If the total is way off, reconsider your reading.

Return ONLY a valid JSON object with these exact keys:
{"song_title": "...", "difficulty": "...", "level": 0, "perfect": 0, "great": 0, "good": 0, "bad": 0, "miss": 0}"""
