"""Product identity for the two agents. Rename here and everything (sidebar, titles, reports) follows."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Agent:
    key: str            # "replay" | "dualrun"
    name: str           # two-word product name
    tagline: str
    accent: str         # primary action colour
    accent_soft: str    # tint of the accent for subtle fills
    sidebar: str        # deep sidebar colour, specific to this agent
    sidebar_raised: str
    glyph: str          # logo mark
    run_page_title: str
    run_page_hint: str


PARITY_REPLAY = Agent(
    key="replay", name="Replay Agent",
    tagline="Replay recorded production payments through the new code and prove the answers still agree.",
    accent="#0F4C5C", accent_soft="#E1EEF1", sidebar="#0A2F39", sidebar_raised="#12434F", glyph="↻",
    run_page_title="New replay",
    run_page_hint="Pick yesterday's recorded traffic, choose the new code to test, and run it.")

TWIN_RUN = Agent(
    key="dualrun", name="Live Agent",
    tagline="Send the same payment to the old and the new service at once and compare every decision.",
    accent="#2A3FA8", accent_soft="#E7EAF8", sidebar="#141E58", sidebar_raised="#1F2D7A", glyph="⇄",
    run_page_title="New run",
    run_page_hint="Send one payment, or a whole batch, to both services and compare what each decides.")
