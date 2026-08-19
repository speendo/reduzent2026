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


def loop_from_text(text: str) -> Loop:
    """Parse reduzent-loop v1 text into a Loop.

    Raises ValueError on malformed input: a missing or wrong version header, a
    bad `length`/`mute` value, a missing `length` line, or an event line whose
    phase or channel does not parse. A line whose first token starts with a
    digit, `+`, `-`, or `.` is an event line and must parse; any other first
    token is a header line — `length`/`mute` are handled, everything else is
    ignored, and blank lines are skipped. Events keep their line order as
    `seq`. A loaded loop always has `anchor = None`.
    """
    loop = Loop()
    muted = set()
    seen_length = False
    first_line = True
    seq = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if first_line:
            if line != "reduzent-loop v1":
                raise ValueError(f"missing 'reduzent-loop v1' header: {line!r}")
            first_line = False
            continue
        head, _, rest = line.partition(" ")
        if head == "length":
            try:
                loop.length = float(rest)
            except ValueError:
                raise ValueError(f"bad length line: {line!r}")
            seen_length = True
            continue
        if head == "mute":
            try:
                muted.add(int(rest))
            except ValueError:
                raise ValueError(f"bad mute line: {line!r}")
            continue
        if not (head[:1].isdigit() or head[:1] in ("+", "-", ".")):
            continue  # unknown/legacy header line
        try:
            phase = float(head)
        except ValueError:
            raise ValueError(f"bad phase in line: {line!r}")
        cmd = rest.strip()
        parts = cmd.split()
        if len(parts) < 2:
            raise ValueError(f"command without channel: {line!r}")
        try:
            ch = int(parts[1])
        except ValueError:
            raise ValueError(f"bad channel in line: {line!r}")
        track = loop.tracks.setdefault(ch, Track())
        track.events.append(Event(phase=phase, seq=seq, cmd=cmd))
        seq += 1
    if not seen_length:
        raise ValueError("missing 'length' line")
    for ch in muted:
        if ch in loop.tracks:
            loop.tracks[ch].muted = True
    return loop


def save_loop(path: str, loop: Loop) -> None:
    """Write `loop` to `path` as reduzent-loop v1 text."""
    with open(path, "w") as f:
        f.write(loop_to_text(loop))


def load_loop(path: str) -> Loop:
    """Read a Loop from `path`; raises ValueError on malformed content."""
    with open(path) as f:
        return loop_from_text(f.read())
