#!/usr/bin/env python3
"""Looper data model and reduzent-loop v1 save format (slice 2).

Pure model + text serializer only: no I/O beyond the two thin save/load file
wrappers, no threads, no clock. The engine (slice 3) and runtime (slice 4)
build on this module. See "Save format" in the MIDI looper design spec for
the file format.
"""

from dataclasses import dataclass, field


@dataclass
class Event:
    phase: float  # position in [0, length), master seconds at 1.0x
    seq: int      # monotonic; = file line order
    cmd: str      # reduzent text command; channel embedded


@dataclass
class Track:
    events: list[Event] = field(default_factory=list)  # kept sorted by (phase, seq)
    muted: bool = False


@dataclass
class Loop:
    length: float = 0.0                                    # 0.0 == "no loop"
    tracks: dict[int, Track] = field(default_factory=dict)  # channel -> Track
    anchor: float | None = None  # time.monotonic() at phase 0; None == no loop


def loop_to_text(loop: Loop) -> str:
    """Serialize a Loop to the reduzent-loop v1 text format (deterministic).

    `length` and every phase are written with microsecond precision (6 decimal
    places). Muted tracks get one `mute <ch>` header line (channels sorted
    ascending); events are written globally sorted by (seq, phase, cmd) across
    all tracks. Every line ends with a newline.
    """
    lines = ["reduzent-loop v1", f"length {loop.length:.6f}"]
    for ch in sorted(loop.tracks):
        if loop.tracks[ch].muted:
            lines.append(f"mute {ch}")
    events = []
    for track in loop.tracks.values():
        events.extend(track.events)
    for e in sorted(events, key=lambda e: (e.seq, e.phase, e.cmd)):
        lines.append(f"{e.phase:.6f} {e.cmd}")
    return "\n".join(lines) + "\n"
