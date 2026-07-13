"""CandidatePresenter -- format candidate lists and parse user selections."""
from __future__ import annotations

import re

from pjsk_core.ports.cache import CandidateSet


class CandidatePresenter:
    """Format OCR candidates for chat display and parse user replies."""

    @staticmethod
    def format(candidate_set: CandidateSet, candidate_set_id: str) -> str:
        lines = ["识别结果存在分歧，请选择：", ""]
        for i, c in enumerate(candidate_set.candidates, 1):
            diff = c.observation.difficulty.name if c.observation.difficulty else "?"
            lvl = c.observation.displayed_level
            title = c.observation.song_title
            lines.append(f"{i}. {title} / {diff} {lvl}")
        lines.append("")
        lines.append("请在 5 分钟内回复 1、2 或 3。")
        lines.append(f"候选编号：{candidate_set_id}")
        return "\n".join(lines)

    @staticmethod
    def parse_selection(
        text: str,
        candidate_set: CandidateSet,
        current_candidate_set_id: str,
    ) -> int | None:
        """Parse user message as a candidate selection.

        Returns 0-based index, or None if the message is not a valid
        selection for the current candidate set.
        """
        text = text.strip()

        # Priority 2: explicit "选 <id> <num>" format
        m = re.match(r'选\s+(\S+)\s+(\d+)', text)
        if m:
            cid, num = m.group(1), int(m.group(2))
            if cid == current_candidate_set_id:
                idx = num - 1
                if 0 <= idx < len(candidate_set.candidates):
                    return idx
            return None

        # Priority 3: pure number
        try:
            num = int(text)
        except ValueError:
            return None
        idx = num - 1
        if 0 <= idx < len(candidate_set.candidates):
            return idx
        return None
