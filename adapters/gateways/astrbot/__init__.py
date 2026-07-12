"""AstrBot gateway adapter.

Converts AstrMessageEvent objects into internal events and maps
TextReply / ImageReply / CandidateReply / ProgressReply / ErrorReply
back to AstrBot MessageEventResult objects.

All AstrBot-specific types (AstrMessageEvent, Context, etc.) stay
in this module and never enter pjsk_core.
"""
