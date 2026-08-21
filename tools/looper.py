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
import time
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

    def take_elapsed(self, now):
        """Seconds since the current take started, or None when not recording."""
        if not self._recording or self._take_anchor is None:
            return None
        return now - self._take_anchor

    @property
    def halted(self):
        return self._halted

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


_CHANNEL_ACTIONS = ("record", "cycle")


def _clean_name(name) -> str:
    """Collapse a config channel name to one short printable line (max 8)."""
    text = "".join(c if c.isprintable() else " " for c in str(name))
    return " ".join(text.split())[:8]


def parse_channels(settings):
    """Extract the "channels" map from settings.

    Returns (map|None, warnings): None when the key is absent or every entry
    is invalid; invalid entries are dropped with one warning each.
    """
    raw = settings.get("channels")
    if not isinstance(raw, dict) or not raw:
        return None, []
    chans, warns = {}, []
    for key, name in raw.items():
        try:
            ch = int(key)
            assert 0 <= ch <= 15 and isinstance(name, str)
        except (ValueError, AssertionError, TypeError):
            warns.append(f"ignoring bad channel entry: {key!r}")
            continue
        clean = _clean_name(name)
        if clean:
            chans[ch] = clean
        else:
            warns.append(f"ignoring channel {ch}: empty name")
    return (chans or None), warns


def parse_hotkeys(settings):
    """Extract the "midi_hotkeys" map from settings.

    Returns (action->(channel, note), warnings); {} when absent. Bad entries
    are dropped with one warning each.
    """
    raw = settings.get("midi_hotkeys")
    if not isinstance(raw, dict):
        return {}, []
    hk, warns = {}, []
    for action, spec in raw.items():
        pair = None
        if action in _CHANNEL_ACTIONS and isinstance(spec, dict):
            try:
                ch, note = int(spec["channel"]), int(spec["note"])
                assert 0 <= ch <= 15 and 0 <= note <= 127
                pair = (ch, note)
            except (KeyError, ValueError, AssertionError, TypeError):
                pair = None
        if pair is None:
            warns.append(f"ignoring bad midi hotkey: {action!r}")
        else:
            hk[action] = pair
    return hk, warns


def present_channels(channels, loop):
    """Channels the UI navigates: config list if set, else tracked channels."""
    if channels:
        return sorted(channels)
    return sorted(loop.tracks)


def step_channel(cur, present, delta):
    """Neighbor of `cur` in `present` (wrap-around); None when nothing to walk."""
    if not present:
        return None
    if cur in present:
        i = (present.index(cur) + delta) % len(present)
        return present[i]
    return present[0]


def edit_target(selected, override_ch, last_channel):
    """Channel a d/x/o hotkey acts on: selection wins over older mechanisms."""
    if selected is not None:
        return selected
    if override_ch is not None:
        return override_ch
    return last_channel


def hotkey_action(hotkeys, msg_type, channel, note, velocity):
    """Classify one MIDI message against the configured hotkeys.

    "record"/"cycle" fire on note-on; the matching note-off (or velocity-0
    note-on) is "swallow"ed so it never sounds or gets recorded.
    """
    hit = None
    for action, (ch, nt) in hotkeys.items():
        if ch == channel and nt == note:
            hit = action
            break
    if hit is None:
        return None
    return hit if msg_type == "note_on" and velocity > 0 else "swallow"


_PANEL_LABEL_MAX = 8  # keep in sync with _clean_name


def column_lines(present, loop, selected, names, max_rows, blink_on):
    """Render the right-side channel column, one string per terminal row.

    States: dim = no track, plain = track, '*' = muted, bold-red-inverse =
    selected while blink_on. Overflow beyond max_rows becomes "+n more".
    """
    lines = []
    visible = present[:max_rows - 1] if len(present) > max_rows else present
    for ch in visible:
        label = str(names.get(ch, ch))[:_PANEL_LABEL_MAX] if names else str(ch)
        track = loop.tracks.get(ch)
        if ch == selected and blink_on:
            body = f"\033[1;31;7m {label}\033[0m"
        elif track is None:
            body = f"\033[2m {label}\033[0m"
        elif track.muted:
            body = f"*{label}"
        else:
            body = f" {label}"
        lines.append(body)
    if len(present) > max_rows:
        lines.append(f"+{len(present) - max_rows + 1} more")
    return lines


_PROGRAM_NAMES = {0: "1-bit", 1: "arp", 2: "mono"}


class _noop_ctx:
    """Null context manager for when no lock is provided."""
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


def status_lines(port, baud, loop_name, loop, rate, override_ch, last_channel,
                 override_inst, last_program, recording=False, rec_elapsed=None,
                 selected=None, sel_name=None):
    """Return the two status-bar lines (the looper's two-line status bar).

    While `recording` is true, line 1 is prefixed with a blinking red
    "● REC" label (0.5 s half-period, derived from `rec_elapsed`) and a
    steady M:SS clock of the take's elapsed time.
    """
    name_disp = loop_name if loop_name is not None else "no loop"
    length_disp = f"{loop.length:.2f}s" if loop.length > 0 else "0.00s"
    if recording and rec_elapsed is not None:
        clock = f"{int(rec_elapsed // 60)}:{int(rec_elapsed) % 60:02d}"
        # Hidden phase reserves the label's columns so the line never jumps.
        label = "\033[1;31m\u25cf REC\033[0m" if int(rec_elapsed * 2) % 2 == 0 else "     "
        rec = f"{label} {clock}  "
    else:
        rec = ""
    if override_ch is not None:
        ch_display = str(override_ch)
        ch_mode = "(override)"
    elif last_channel is not None:
        ch_display = str(last_channel)
        ch_mode = "(MIDI)"
    else:
        ch_display = "--"
        ch_mode = "(MIDI)"
    if selected is not None:
        sel_disp = sel_name if sel_name else str(selected)
        seg = f"\033[1;33msel: {sel_disp}\033[0m"
        if override_ch is not None:
            seg += " (ovr)"
    else:
        seg = f"ch: \033[1;32m{ch_display}\033[0m {ch_mode}"
    if override_inst is not None:
        inst_display = str(override_inst)
    elif last_program is not None:
        inst_display = _PROGRAM_NAMES.get(last_program, str(last_program))
    else:
        inst_display = "--"
    line1 = (
        f" {rec}\033[1;36m\u25b8\033[0m \033[1;32m{port}\033[0m @ \033[1;32m{baud}\033[0m"
        f"  loop: \033[1;33m{name_disp}\033[0m  len: \033[1;32m{length_disp}\033[0m"
        f"  trk: {len(loop.tracks)}  rate: x{rate:.2f}"
    )
    line2 = (
        f" \033[1;36m\u25b8\033[0m {seg}  "
        f"inst: \033[1;32m{inst_display}\033[0m   "
        f"\033[2mspace rec  d del  x mute  p panic  o noff  w save  r load  "
        f"+/- rate  \u232b rate1  0-9 ch  tab/\u2190\u2192 nav  "
        f"c ch  i inst  m menu  s settings  q quit\033[0m"
    )
    return line1, line2


def draw_status(port, baud, loop_name, engine, override_ch, last_channel,
                override_inst, last_program, lock=None,
                selected=None, sel_name=None):
    """Redraw the two-line status bar at the terminal bottom."""
    rows = os.get_terminal_size().lines
    line1, line2 = status_lines(port, baud, loop_name, engine.loop, engine.rate,
                                override_ch, last_channel, override_inst, last_program,
                                recording=engine.recording,
                                rec_elapsed=engine.take_elapsed(time.monotonic()),
                                selected=selected, sel_name=sel_name)
    ctx = lock if lock else _noop_ctx()
    with ctx:
        sys.stdout.write("\033[s")  # save cursor
        sys.stdout.write(f"\033[{rows - 1};1H\033[2K{line1}")
        sys.stdout.write(f"\033[{rows};1H\033[2K{line2}")
        sys.stdout.write("\033[u")  # restore cursor
        sys.stdout.flush()


def main() -> None:
    import serial
    import serial.tools.list_ports
    import mido

    argv = sys.argv[1:]
    config = DEFAULT_CONFIG
    quiet = "--quiet" in argv
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            config = argv[i + 1]

    def detected():
        return (
            mido.get_input_names(),
            [p.device for p in serial.tools.list_ports.comports()],
        )

    if "--list" in argv:
        print("MIDI inputs:")
        for n in mido.get_input_names():
            print(f"  - {n}")
        print("Serial ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  - {p.device} - {p.description}")
        return

    midi_names, serial_names = detected()
    try:
        midi_name, port, baud = select_ports(load_settings(config), midi_names, serial_names)
    except KeyboardInterrupt:
        return
    if midi_name is None or port is None:
        raise SystemExit("no MIDI input or serial port detected")
    inport, ser = open_connections(midi_name, port, baud)
    save_settings(config, {"midi_input": midi_name, "serial_port": port, "baud": baud})

    # One shared lock guards the serial handle AND the engine: the MIDI callback
    # (record + live forward), the scheduler thread (playback), and the hotkey
    # handlers all touch the same model through it.
    lock = threading.Lock()
    stdout_lock = threading.Lock()
    state = {"ser": ser}
    write_error = False
    override_ch = None
    override_inst = None
    last_channel = None
    last_program = None
    loop_name = None  # None == "no loop"; set by 'w'/'r'
    engine = Engine()

    def emit(cmd: str) -> None:
        """Write one reduzent command to the serial port; reconnect on failure."""
        nonlocal write_error
        with lock:
            s = state["ser"]
            if s is None:
                return
            try:
                s.write((cmd + "\n").encode())
            except OSError:
                if not write_error:
                    write_error = True
                    with stdout_lock:
                        sys.stdout.write("serial write failed; will retry\r\n")
                        sys.stdout.flush()
                try:
                    state["ser"] = None
                    s.close()
                except OSError:
                    pass

    def on_message(msg):
        nonlocal last_channel
        nonlocal last_program
        cmd = midi_to_command(msg)
        if cmd is None:
            return
        if msg.type in ("note_on", "note_off"):
            last_channel = msg.channel
        if msg.type == "program_change":
            last_program = msg.program
        if override_ch is not None or override_inst is not None:
            parts = cmd.split()
            if override_ch is not None:
                if parts[0] in ("n", "x", "p", "a", "g", "v") and len(parts) >= 2:
                    parts[1] = str(override_ch)
                elif parts[0] == "pa" and len(parts) >= 3:
                    parts[1] = str(override_ch)
            if override_inst is not None and parts[0] == "g" and len(parts) >= 3:
                parts[2] = str(override_inst)
            cmd = " ".join(parts)
        parts = cmd.split()
        ch = int(parts[1]) if len(parts) >= 2 else 0
        note = int(parts[2]) if len(parts) >= 3 and parts[0] in ("n", "x") else None
        with lock:
            engine.record(cmd, ch, note, time.monotonic())
        emit(cmd)
        if not quiet:
            with stdout_lock:
                sys.stdout.write(cmd + "\r\n")
                sys.stdout.flush()

    def scheduler(stop_event):
        """Poll the engine's due events and emit them; deep-sleep only when idle."""
        while not stop_event.is_set():
            with lock:
                now = time.monotonic()
                due = engine.due(now)
                idle = (
                    engine.loop.length <= 0
                    or not engine.loop.tracks
                    or engine.halted
                )
            for e in due:
                emit(e.cmd)
            if idle:
                stop_event.wait(0.05)  # no loop playing: stay dormant like the bridge
            else:
                time.sleep(0.001)  # loop playing: tight poll for timing accuracy

    inport.callback = on_message

    # Raw stdin so a single keypress is detected without Enter (Unix only).
    fd = sys.stdin.fileno()
    with raw_terminal(fd) as old:

        last_redraw = 0
        serial_buf = ""
        sys.stdout.write("\033[2J\033[1;1H")
        sys.stdout.flush()
        setup_scroll_region(2)
        draw_status(port, baud, loop_name, engine, override_ch,
                    last_channel, override_inst, last_program, stdout_lock)
        stop_event = threading.Event()
        sched_thread = threading.Thread(target=scheduler, args=(stop_event,), daemon=True)
        sched_thread.start()
        try:
            while True:
                # Echo whatever the controller writes back (tx / send failed / hb).
                with lock:
                    s = state["ser"]
                    if s is not None:
                        try:
                            data = s.read(256)
                        except OSError:
                            data = b""
                        if data:
                            serial_buf += data.decode("utf-8", errors="replace")
                            # Write only complete lines (ending with \n).
                            # Partial lines stay in the buffer until next read.
                            while "\n" in serial_buf:
                                line, serial_buf = serial_buf.split("\n", 1)
                                out = line + "\r\n"
                                if out.startswith("hb "):
                                    out = f"\033[2;36m{out}\033[0m"
                                with stdout_lock:
                                    sys.stdout.write(out)
                                    sys.stdout.flush()

                # Auto-reopen the serial port after a dropped connection.
                if state["ser"] is None:
                    try:
                        new_ser = serial.Serial(port, baud, timeout=0)
                    except OSError:
                        pass
                    else:
                        with lock:
                            state["ser"] = new_ser
                        write_error = False
                        with stdout_lock:
                            sys.stdout.write(f"reconnected to {port}\r\n")
                            sys.stdout.flush()

                if not select.select([sys.stdin], [], [], 0.1)[0]:
                    now = time.monotonic()
                    # Live clock + blink while recording; lazy refresh otherwise.
                    interval = 0.15 if engine.recording else 2.0
                    if now - last_redraw >= interval:
                        draw_status(port, baud, loop_name, engine, override_ch,
                                    last_channel, override_inst, last_program, stdout_lock)
                        last_redraw = now
                    continue
                ch = sys.stdin.read(1)
                if ch in ("\x03", "q", "Q"):
                    if engine.recording:
                        with stdout_lock:
                            sys.stdout.write("finish or cancel the take first (space/d)\r\n")
                            sys.stdout.flush()
                    else:
                        reset_scroll_region()
                        break
                if ch == " ":
                    with lock:
                        live = engine.toggle(time.monotonic())
                    for c in live:
                        emit(c)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("d", "D"):
                    with lock:
                        if engine.recording:
                            engine.cancel()
                            live = []
                        else:
                            target = override_ch if override_ch is not None else last_channel
                            live = engine.delete_track(target) if target is not None else []
                    for c in live:
                        emit(c)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("x", "X"):
                    with lock:
                        target = override_ch if override_ch is not None else last_channel
                        live = engine.toggle_mute(target) if target is not None else []
                    for c in live:
                        emit(c)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("p", "P"):
                    with lock:
                        if engine.halted:
                            engine.resume(time.monotonic())
                            live = []
                        else:
                            live = engine.halt()
                    for _ in range(3):  # panic sent 3x so the leaves reliably stop
                        for c in live:
                            emit(c)
                if ch in ("o", "O"):
                    target = override_ch if override_ch is not None else last_channel
                    if target is None:
                        with stdout_lock:
                            sys.stdout.write("no active channel to silence\r\n")
                            sys.stdout.flush()
                    else:
                        emit(f"noff {target}")
                if ch in ("+", "="):
                    with lock:
                        engine.set_rate(engine.rate + 0.05)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("-",):
                    with lock:
                        engine.set_rate(engine.rate - 0.05)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch == "0":
                    with lock:
                        engine.set_rate(1.0)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("c", "C"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        raw = input("Channel [0-15, empty=reset]: ").strip()
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    if raw:
                        try:
                            val = int(raw)
                            if 0 <= val <= 15:
                                override_ch = val
                                engine.override_ch = val
                            else:
                                print("channel must be 0-15")
                        except ValueError:
                            print("invalid input")
                    else:
                        override_ch = None
                        engine.override_ch = None
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("i", "I"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        raw = input("Instrument [0-127, empty=reset]: ").strip()
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    if raw:
                        try:
                            val = int(raw)
                            if 0 <= val <= 127:
                                override_inst = val
                                # Send program change immediately to all leaves
                                emit(f"g {override_ch if override_ch is not None else 0} {override_inst}")
                            else:
                                print("program must be 0-127")
                        except ValueError:
                            print("invalid input")
                    else:
                        override_inst = None
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("m", "M"):
                    # Restore canonical mode so the menu's input() works.
                    # Disable MIDI callback so messages don't corrupt the menu display.
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        midi_names, serial_names = detected()
                        new_midi, new_port, new_baud = select_ports(
                            load_settings(config), midi_names, serial_names
                        )
                        if new_midi is None or new_port is None:
                            print("no ports detected; keeping current connection")
                        else:
                            try:
                                new_inport, new_ser = open_connections(new_midi, new_port, new_baud)
                            except OSError:
                                print("could not open new ports; keeping current connection")
                            else:
                                with lock:
                                    state["ser"] = None
                                    ser.close()
                                inport.close()
                                inport, ser = new_inport, new_ser
                                with lock:
                                    state["ser"] = ser
                                midi_name, port, baud = new_midi, new_port, new_baud
                                save_settings(config, {
                                    "midi_input": midi_name,
                                    "serial_port": port,
                                    "baud": baud,
                                })
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("s", "S"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        target = input("Settings mode for leaf id [all]: ").strip()
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    cmd = "settings"
                    if target:
                        try:
                            int(target)
                            cmd = f"settings {target}"
                        except ValueError:
                            cmd = "settings"
                    emit(cmd)
                    draw_status(port, baud, loop_name, engine, override_ch,
                                last_channel, override_inst, last_program, stdout_lock)
                if ch in ("w", "W"):
                    if engine.recording:
                        with stdout_lock:
                            sys.stdout.write("finish or cancel the take first (space/d)\r\n")
                            sys.stdout.flush()
                    else:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
                        inport.callback = None
                        try:
                            name = input("Loop name: ").strip()
                        finally:
                            inport.callback = on_message
                            tty.setraw(fd)
                        clean = sanitize_name(name)
                        if not clean:
                            print("no name given; save cancelled")
                        else:
                            try:
                                save_loop_named(LOOPS_DIR, clean, engine.loop)
                            except OSError as e:
                                print(f"save failed: {e}")
                            else:
                                loop_name = clean
                                print(f"saved {clean}")
                        draw_status(port, baud, loop_name, engine, override_ch,
                                    last_channel, override_inst, last_program, stdout_lock)
                if ch in ("r", "R"):
                    if engine.recording:
                        with stdout_lock:
                            sys.stdout.write("finish or cancel the take first (space/d)\r\n")
                            sys.stdout.flush()
                    else:
                        names = list_loop_names(LOOPS_DIR)
                        if not names:
                            with stdout_lock:
                                sys.stdout.write("no saved loops\r\n")
                                sys.stdout.flush()
                        else:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old)
                            inport.callback = None
                            try:
                                chosen = menu_choice("Load loop:", names, loop_name)
                            except KeyboardInterrupt:
                                chosen = None
                            finally:
                                inport.callback = on_message
                                tty.setraw(fd)
                            if chosen is not None:
                                try:
                                    loop = load_loop_named(LOOPS_DIR, chosen)
                                except (OSError, ValueError) as e:
                                    print(f"load failed: {e}")
                                else:
                                    with lock:
                                        loop.anchor = time.monotonic()  # start at phase 0
                                        engine = Engine(loop)  # fresh seq + playback state
                                        engine.override_ch = override_ch
                                    loop_name = chosen
                                    print(f"loaded {chosen}")
                            draw_status(port, baud, loop_name, engine, override_ch,
                                        last_channel, override_inst, last_program, stdout_lock)
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            inport.callback = None
            for _ in range(3):
                emit("panic")
            with lock:
                state["ser"] = None
                ser.close()
            inport.close()
            sched_thread.join(timeout=1.0)
            reset_scroll_region()
            # Clear screen and restore cursor to top-left on exit
            sys.stdout.write("\033[2J\033[1;1H")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
