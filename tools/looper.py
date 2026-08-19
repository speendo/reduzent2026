#!/usr/bin/env python3
"""Looper data model and reduzent-loop v1 save format (slice 2).

Pure model + text serializer only: no I/O beyond the two thin save/load file
wrappers, no threads, no clock. The engine (slice 3) and runtime (slice 4)
build on this module. See "Save format" in the MIDI looper design spec for
the file format.
"""

import os
import re
import select
import sys
import termios
import threading
import tty
from dataclasses import dataclass, field
from typing import Optional

from reduzent_shared import (
    DEFAULT_CONFIG,
    load_settings,
    menu_choice,
    midi_to_command,
    open_connections,
    raw_terminal,
    reset_scroll_region,
    resolve_settings,
    save_settings,
    select_ports,
    setup_scroll_region,
)


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

    def halt(self):
        live = ["panic"]
        if self._recording:
            return live
        if (
            not self._halted
            and self.loop.length > 0
            and self.loop.anchor is not None
            and self._last_now is not None
        ):
            hp = self.phase(self._last_now)
            if hp is not None:
                self._halt_phase = hp
                self._halted = True
        return live

    def resume(self, now):
        if not self._halted:
            return
        self._last_now = now
        if self._halt_phase is None:
            self._halted = False
            return
        self.loop.anchor = now - self._halt_phase / self.rate
        self._last_phase = self._halt_phase
        self._halted = False

    def due(self, now):
        self._last_now = now
        if self._halted or self.loop.length <= 0 or not self.loop.tracks:
            return []
        cur = self.phase(now)
        if cur is None:
            return []
        if cur < self._last_phase:  # the loop wrapped to a new cycle
            self._cycle += 1
            window = (-1.0, cur)  # inclusive of phase 0 so phase-0 events fire
        else:
            window = (self._last_phase, cur)
        candidates = []
        for track in self.loop.tracks.values():
            if track.muted:
                continue
            for e in track.events:
                if window[0] < e.phase <= window[1]:
                    candidates.append(e)
        candidates.sort(key=lambda e: (e.phase, e.seq))
        ons_at_phase = {}
        result = []
        for e in candidates:
            k = _note_key(e.cmd)
            if e.cmd.startswith("x") and k is not None:
                if k in self._seam_pending and self._seam_pending[k][0] < self._cycle:
                    result.append(self._seam_pending[k][1])  # deferred full-length off
                    del self._seam_pending[k]
                elif ons_at_phase.get(k) == e.phase:
                    self._seam_pending[k] = (self._cycle, e)  # clamp: off == on
                else:
                    result.append(e)
            else:
                if k is not None:
                    ons_at_phase[k] = e.phase
                result.append(e)
        self._last_phase = cur
        return result

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
        head = cmd.split(maxsplit=1)[0] if cmd else ""
        if head not in CAPTURED:
            return  # g / panic / noff / resetcc / settings are control, not content
        if self._take_ch is None:
            self._take_ch = ch
            if self._take_fresh is None:
                self._take_fresh = not (
                    len(self.loop.tracks) == 1 and ch not in self.loop.tracks
                )
            if self._speculative and self._take_ch != self._speculative_ch:
                # First note on a different channel: this is an overdub, not a
                # re-record, so undo the speculative mute of the survivor.
                track = self.loop.tracks.get(self._speculative_ch)
                if track is not None:
                    track.muted = self._old_muted
                self._old_track = None
                self._speculative = False
        if ch != self._take_ch:
            return  # single-channel take: other channels pass through live
        if head == "n" and note is not None:
            self._take_held.add((ch, note))
        elif head == "x" and note is not None:
            self._take_held.discard((ch, note))
        if self._take_fresh:
            t = now - self._take_anchor
            phase = t
        else:
            t = (now - self.loop.anchor) * self.rate
            phase = t % self.loop.length
        self._take_events.append((t, Event(phase=phase, seq=self._seq, cmd=cmd)))
        self._seq += 1

    def cancel(self):
        if self._recording:
            self._discard_take()

    def delete_track(self, ch):
        if self._recording:
            return []  # the runtime routes 'd' to cancel() instead
        if ch not in self.loop.tracks:
            return []
        del self.loop.tracks[ch]
        self._seam_pending.clear()
        if not self.loop.tracks:
            self.loop.length = 0.0  # deleting all tracks resets the loop
            self.loop.anchor = None
            self._reset_playback()
        return [f"noff {ch}"]

    def toggle_mute(self, ch):
        if self._recording:
            return []
        if ch not in self.loop.tracks:
            return []
        track = self.loop.tracks[ch]
        track.muted = not track.muted
        self._seam_pending.clear()
        return [f"noff {ch}"]

    # --- take lifecycle -------------------------------------------------

    def _start_take(self, now):
        ch = self.override_ch
        live = []
        if ch is not None and ch in self.loop.tracks:
            self._mute_for_take(ch)
            live.append(f"noff {ch}")
        elif ch is None and len(self.loop.tracks) == 1:
            lone = next(iter(self.loop.tracks))
            self._mute_for_take(lone)  # speculative: the survivor is being re-recorded
            live.append(f"noff {lone}")
            self._speculative = True
            self._speculative_ch = lone
        if not self.loop.tracks:
            fresh = True
        elif len(self.loop.tracks) == 1 and ch is not None and ch in self.loop.tracks:
            fresh = True  # lone-track overwrite: fresh length
        elif ch is None and len(self.loop.tracks) == 1:
            fresh = None  # resolve at the first note
        else:
            fresh = False  # loop exists: overdub against the current length
        self._recording = True
        self._take_ch = None if ch is None else ch
        self._take_anchor = now
        self._take_fresh = fresh
        self._take_events = []
        self._take_held = set()
        self._seam_pending.clear()
        return live

    def _stop_take(self, now):
        if self._take_ch is None or not self._take_events:
            self._discard_take()  # empty take: nothing recorded, nothing committed
            return []
        if self._take_fresh:
            length = now - self._take_anchor
            end_t = length
            stop_phase = 0.0  # closing notes land at phase 0 -> clamped full-length
        else:
            length = self.loop.length
            end_t = (now - self.loop.anchor) * self.rate
            stop_phase = end_t % length
        for k in self._take_held:
            self._take_events.append(
                (end_t, Event(phase=stop_phase, seq=self._seq, cmd=f"x {k[0]} {k[1]}"))
            )
            self._seq += 1
        final_start = end_t - length
        kept = [e for (t, e) in self._take_events if t >= final_start]
        kept = self._seam_close(self._take_events, kept)
        if self._take_fresh:
            self.loop.length = length
            self.loop.anchor = self._take_anchor
        track = Track(events=sorted(kept, key=lambda e: (e.phase, e.seq)))
        track.muted = self._old_muted if self._old_track is not None else False
        self.loop.tracks[self._take_ch] = track
        self._reset_playback()
        ch = self._take_ch
        self._clear_take()
        return [f"noff {ch}"]

    def _seam_close(self, events, kept):
        """Keep a note's on when its off survives the final pass but the on fell
        before it (a note held across the over-record boundary)."""
        kept_ids = {id(e) for e in kept}  # Event is unhashable: key by id()
        keys = set()
        for _, e in events:
            k = _note_key(e.cmd)
            if k is not None:
                keys.add(k)
        for k in keys:
            note_events = sorted(
                (e for _, e in events if _note_key(e.cmd) == k), key=lambda e: e.seq
            )
            last_on = None
            for e in note_events:
                if e.cmd.startswith("n"):
                    last_on = e
                else:
                    if id(e) in kept_ids and last_on is not None and id(last_on) not in kept_ids:
                        kept.append(last_on)
                        kept_ids.add(id(last_on))
                    last_on = None
        return kept

    def _mute_for_take(self, ch):
        track = self.loop.tracks[ch]
        self._old_track = track
        self._old_track_ch = ch
        self._old_muted = track.muted
        track.muted = True
        self._seam_pending.clear()

    def _discard_take(self):
        if self._old_track is not None:
            self.loop.tracks[self._old_track_ch].muted = self._old_muted
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


LOOPS_DIR = os.path.join(os.path.expanduser("~"), ".config", "reduzent", "loops")


def sanitize_name(name: str) -> str:
    """Sanitize a loop name into a safe directory name ('' if empty)."""
    clean = re.sub(r"[^a-z0-9_-]+", "-", name.lower())
    clean = re.sub(r"-+", "-", clean).strip("-")
    return clean


def loop_path(base: str, name: str) -> str:
    """Absolute path of `name`'s loop.loop file under `base`."""
    return os.path.join(base, name, "loop.loop")


def list_loop_names(base: str) -> list[str]:
    """Sorted names of saved loops under `base` (directories holding loop.loop)."""
    names = []
    try:
        entries = os.listdir(base)
    except OSError:
        return names
    for entry in entries:
        if os.path.isfile(loop_path(base, entry)):
            names.append(entry)
    return sorted(names)


def save_loop_named(base: str, name: str, loop: Loop) -> None:
    """Write `loop` to `<base>/<name>/loop.loop`, creating the directory."""
    os.makedirs(os.path.join(base, name), exist_ok=True)
    save_loop(loop_path(base, name), loop)


def load_loop_named(base: str, name: str) -> Loop:
    """Read `<base>/<name>/loop.loop`; raises ValueError on malformed content."""
    return load_loop(loop_path(base, name))
