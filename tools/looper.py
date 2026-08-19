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


CAPTURED = ("n", "x", "p", "a", "pa", "v")


def _note_key(cmd):
    """Return (channel, note) for a note command, else None."""
    parts = cmd.split()
    if len(parts) >= 3 and parts[0] in ("n", "x"):
        return (int(parts[1]), int(parts[2]))
    return None


class Engine:
    """Recording + playback-scheduling engine (slice 3).

    A pure object driven by `now` values (monotonic seconds): no threads, no
    I/O, no sleeps. The runtime (slice 4) feeds it real time and the
    post-override reduzent command stream. Phases are master seconds at 1.0x;
    `rate` applies only once a loop exists (overdub stamping and playback).
    """

    def __init__(self, loop=None):
        self.loop = loop if loop is not None else Loop()
        self.rate = 1.0
        self.override_ch = None  # 'c' override; the runtime sets this
        self._seq = 0
        for track in self.loop.tracks.values():
            for e in track.events:
                self._seq = max(self._seq, e.seq + 1)
        self._recording = False
        self._take_ch = None
        self._take_anchor = None
        self._take_fresh = None
        self._take_events = []  # [(take-time, Event)]
        self._take_held = set()
        self._old_track = None
        self._old_track_ch = None
        self._old_muted = None
        self._speculative = False
        self._speculative_ch = None
        self._last_phase = -1.0
        self._cycle = 0
        self._seam_pending = {}  # (ch, note) -> (defer cycle, Event)
        self._halted = False
        self._halt_phase = None
        self._last_now = None

    @property
    def recording(self):
        return self._recording

    def phase(self, now):
        self._last_now = now
        if self._halted:
            return self._halt_phase
        if self.loop.anchor is None or self.loop.length <= 0:
            return None
        return ((now - self.loop.anchor) * self.rate) % self.loop.length

    def set_rate(self, rate):
        self.rate = min(4.0, max(0.25, rate))

    def toggle(self, now):
        self._last_now = now
        if self._halted:
            return []  # space is inert while halted
        if self._recording:
            return self._stop_take(now)
        return self._start_take(now)

    def record(self, cmd, ch, note, now):
        self._last_now = now
        if not self._recording:
            return
        if ch != self._take_ch:
            return
        if note is not None and cmd.startswith("n"):
            self._take_held.add((ch, note))
        elif note is not None and cmd.startswith("x"):
            self._take_held.discard((ch, note))
        phase = now - self._take_anchor  # fresh take: phase = now - start
        self._take_events.append((phase, Event(phase=phase, seq=self._seq, cmd=cmd)))
        self._seq += 1

    def cancel(self):
        if self._recording:
            self._discard_take()

    # --- take lifecycle -------------------------------------------------

    def _start_take(self, now):
        self._recording = True
        self._take_ch = self.override_ch
        self._take_anchor = now
        self._take_fresh = True
        self._take_events = []
        self._take_held = set()
        return []

    def _stop_take(self, now):
        if self._take_ch is None or not self._take_events:
            self._discard_take()  # empty take: nothing recorded, nothing committed
            return []
        length = now - self._take_anchor
        for k in self._take_held:
            self._take_events.append(
                (length, Event(phase=0.0, seq=self._seq, cmd=f"x {k[0]} {k[1]}"))
            )
            self._seq += 1
        events = [e for (t, e) in self._take_events]
        self.loop.length = length
        self.loop.anchor = self._take_anchor
        self.loop.tracks[self._take_ch] = Track(
            events=sorted(events, key=lambda e: (e.phase, e.seq))
        )
        self._reset_playback()
        ch = self._take_ch
        self._clear_take()
        return [f"noff {ch}"]

    def _discard_take(self):
        self._clear_take()

    def _clear_take(self):
        self._recording = False
        self._take_ch = None
        self._take_anchor = None
        self._take_fresh = None
        self._take_events = []
        self._take_held = set()
        self._old_track = None
        self._old_track_ch = None
        self._old_muted = None
        self._speculative = False
        self._speculative_ch = None

    def _reset_playback(self):
        self._last_phase = -1.0
        self._cycle = 0
        self._seam_pending.clear()
