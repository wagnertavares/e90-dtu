#!/usr/bin/env python3
"""
E90-DTU(900SL30) — Interactive Configuration Editor
Reads, displays and edits register settings via serial port (Config Mode 2).
Requires: pip install pyserial
"""

import serial, time, sys, os, argparse, tty, termios, copy, re
from typing import Optional, List, Tuple, Any

# ══════════════════════════════════════════════════════════════════════════════
#  ANSI palette
# ══════════════════════════════════════════════════════════════════════════════
class C:
    RST  = "\033[0m";  BOLD = "\033[1m";  DIM  = "\033[2m"
    AMB  = "\033[38;5;214m";  AMBB = "\033[1;38;5;214m"
    CYN  = "\033[38;5;87m";   CYNB = "\033[1;38;5;87m"
    GRN  = "\033[38;5;120m";  RED  = "\033[38;5;203m"
    YEL  = "\033[38;5;228m";  PUR  = "\033[38;5;183m"
    GRY  = "\033[38;5;242m";  WHT  = "\033[38;5;255m"
    BLU  = "\033[38;5;39m";   ORG  = "\033[38;5;208m"
    BX   = "\033[38;5;240m"   # box lines dim
    BXA  = "\033[38;5;214m"   # box lines amber
    BXM  = "\033[38;5;203m"   # box lines red/modified
    HLB  = "\033[48;5;235m"   # highlight bg
    KEY  = "\033[38;5;226m"   # key letter colour

W = 78  # total width

# ══════════════════════════════════════════════════════════════════════════════
#  Low-level terminal helpers
# ══════════════════════════════════════════════════════════════════════════════
def cls():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

def getch() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def hide_cursor():  sys.stdout.write("\033[?25l"); sys.stdout.flush()
def show_cursor():  sys.stdout.write("\033[?25h"); sys.stdout.flush()

def p(s=""):
    print(s)

def ansi_len(s: str) -> int:
    return len(re.sub(r'\033\[[0-9;]*m', '', s))

def fit(s: str, width: int) -> str:
    """Pad/truncate string to exactly `width` visible chars."""
    vis = ansi_len(s)
    if vis < width:
        return s + " " * (width - vis)
    # trim raw chars until visible length matches
    out, cnt = "", 0
    i = 0
    while i < len(s):
        if s[i] == '\033':
            j = s.find('m', i)
            if j == -1:
                break
            out += s[i:j+1]
            i = j + 1
        else:
            if cnt < width:
                out += s[i]
                cnt += 1
            i += 1
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  Box-drawing primitives
# ══════════════════════════════════════════════════════════════════════════════
def bc(mod: bool) -> str:
    return C.BXM if mod else C.BX

def box_top(title: str = "", w: int = W, mod: bool = False) -> str:
    col = bc(mod)
    if title:
        tlen = len(title) + 2
        lpad = (w - 2 - tlen) // 2
        rpad = w - 2 - tlen - lpad
        tc = C.RED if mod else C.AMBB
        return f"{col}┌{'─'*lpad}{tc} {title} {col}{'─'*rpad}┐{C.RST}"
    return f"{col}┌{'─'*(w-2)}┐{C.RST}"

def box_bot(w: int = W, mod: bool = False) -> str:
    col = bc(mod)
    return f"{col}└{'─'*(w-2)}┘{C.RST}"

def box_mid(w: int = W, mod: bool = False) -> str:
    col = bc(mod)
    return f"{col}├{'─'*(w-2)}┤{C.RST}"

def box_divider(w: int = W, mod: bool = False) -> str:
    """Horizontal separator with vertical divider at midpoint."""
    col = bc(mod)
    half = (w - 2) // 2
    return f"{col}├{'─'*(half-1)}┼{'─'*(w-2-half)}┤{C.RST}"

def box_row2(left_str: str, right_str: str, w: int = W, mod: bool = False) -> str:
    """Two-column row. left_str and right_str are already ANSI-coloured."""
    col = bc(mod)
    half = (w - 2) // 2        # left column inner width (incl. divider position)
    l_inner = half - 1          # usable chars in left col
    r_inner = w - 2 - half      # usable chars in right col
    lp = fit(left_str,  l_inner)
    rp = fit(right_str, r_inner)
    return f"{col}│{C.RST}{lp}{col}│{C.RST}{rp}{col}│{C.RST}"

def box_full(text: str, w: int = W, mod: bool = False) -> str:
    col = bc(mod)
    inner = w - 2
    return f"{col}│{C.RST}{fit(text, inner)}{col}│{C.RST}"

# ══════════════════════════════════════════════════════════════════════════════
#  Banner
# ══════════════════════════════════════════════════════════════════════════════
BANNER = [
    r"   ███████╗ █████╗  ██████╗       ██████╗ ████████╗██╗   ██╗",
    r"   ██╔════╝██╔══██╗██╔═══██╗      ██╔══██╗╚══██╔══╝██║   ██║",
    r"   █████╗  ╚██████║██║   ██║█████╗██║  ██║   ██║   ██║   ██║",
    r"   ██╔══╝   ╚═══██║██║   ██║╚════╝██║  ██║   ██║   ██║   ██║",
    r"   ███████╗ █████╔╝╚██████╔╝      ██████╔╝   ██║   ╚██████╔╝",
    r"   ╚══════╝ ╚════╝  ╚═════╝       ╚═════╝    ╚═╝    ╚═════╝ ",
]
SHADES = [C.AMB, C.AMB, "\033[38;5;215m", "\033[38;5;220m", C.YEL, C.YEL]

def print_banner(port: str, demo: bool, pid: Optional[bytes]):
    cls()
    for line, shade in zip(BANNER, SHADES):
        print(f"{shade}{line}{C.RST}")
    print(f"{C.GRY}{'─'*W}{C.RST}")
    pid_str = (''.join(chr(b) if 32 <= b < 127 else '.' for b in pid)) if pid else "—"
    mode_lbl = f"{C.YEL}DEMO{C.RST}" if demo else f"{C.GRN}LIVE{C.RST}"
    print(f"  {C.DIM}E90-DTU(900SL30) · ISM 868/915 MHz LoRa · "
          f"Port: {C.CYNB}{port}{C.RST}  "
          f"{C.DIM}PID: {C.WHT}{pid_str}{C.RST}  [{mode_lbl}]")
    print(f"{C.GRY}{'─'*W}{C.RST}")

# ══════════════════════════════════════════════════════════════════════════════
#  Option tables
# ══════════════════════════════════════════════════════════════════════════════
BAUD_OPTS   = [(0,"1200 bps"),(1,"2400 bps"),(2,"4800 bps"),(3,"9600 bps"),
               (4,"19200 bps"),(5,"38400 bps"),(6,"57600 bps"),(7,"115200 bps")]
PARITY_OPTS = [(0,"8N1"),(1,"8O1"),(2,"8E1")]
AIR_OPTS    = [(2,"2.4 kbps"),(3,"4.8 kbps"),(4,"9.6 kbps"),
               (5,"19.2 kbps"),(6,"38.4 kbps"),(7,"62.5 kbps")]
SUBPK_OPTS  = [(0,"240 bytes"),(1,"128 bytes"),(2,"64 bytes"),(3,"32 bytes")]
POWER_OPTS  = [(0,"30 dBm (1W)"),(1,"27 dBm"),(2,"24 dBm"),(3,"21 dBm")]
BOOL_OPTS   = [(0,"Disabled"),(1,"Enabled")]
TXMOD_OPTS  = [(0,"Transparent"),(1,"Fixed")]
WORMD_OPTS  = [(0,"WOR Receiver"),(1,"WOR Transmitter")]
WORTM_OPTS  = [(0,"500 ms"),(1,"1000 ms"),(2,"1500 ms"),(3,"2000 ms"),
               (4,"2500 ms"),(5,"3000 ms"),(6,"3500 ms"),(7,"4000 ms")]
CHAN_OPTS   = [(i, f"CH {i:02d}  {850.125+i:.3f} MHz") for i in range(81)]

# ══════════════════════════════════════════════════════════════════════════════
#  Decode / encode register bytes
# ══════════════════════════════════════════════════════════════════════════════
def decode_state(raw: bytes) -> dict:
    reg0, reg1, reg2, reg3 = raw[3], raw[4], raw[5], raw[6]
    return {
        "addh":    raw[0],
        "addl":    raw[1],
        "netid":   raw[2],
        "baud":    (reg0 >> 5) & 0x07,
        "parity":  (reg0 >> 3) & 0x03,
        "airrate": reg0 & 0x07,
        "subpk":   (reg1 >> 6) & 0x03,
        "rssi_n":  (reg1 >> 5) & 0x01,
        "power":   reg1 & 0x03,
        "channel": reg2 & 0x7F,
        "rssi_b":  (reg3 >> 7) & 0x01,
        "txmode":  (reg3 >> 6) & 0x01,
        "repeat":  (reg3 >> 5) & 0x01,
        "lbt":     (reg3 >> 4) & 0x01,
        "wormd":   (reg3 >> 3) & 0x01,
        "wortm":   reg3 & 0x07,
        "crypt_h": raw[7],
        "crypt_l": raw[8],
    }

def encode_state(s: dict) -> bytes:
    reg0 = ((s["baud"] & 0x07) << 5) | ((s["parity"] & 0x03) << 3) | (s["airrate"] & 0x07)
    reg1 = ((s["subpk"] & 0x03) << 6) | ((s["rssi_n"] & 0x01) << 5) | (s["power"] & 0x03)
    reg3 = ((s["rssi_b"] & 0x01) << 7) | ((s["txmode"] & 0x01) << 6) | \
           ((s["repeat"] & 0x01) << 5) | ((s["lbt"] & 0x01) << 4) | \
           ((s["wormd"] & 0x01) << 3)  | (s["wortm"] & 0x07)
    return bytes([s["addh"], s["addl"], s["netid"], reg0, reg1,
                  s["channel"] & 0x7F, reg3, s["crypt_h"], s["crypt_l"]])

def opt_label(opts: list, val: int) -> str:
    for k, v in opts:
        if k == val:
            return v
    return f"0x{val:02X}"

def fmt_value(fid: str, state: dict, opts) -> str:
    val = state[fid]
    if fid == "channel":
        return f"CH {val:02d}  {850.125+val:.3f} MHz"
    if opts:
        return opt_label(opts, val)
    if fid in ("addh", "addl", "netid"):
        return f"0x{val:02X} ({val})"
    return f"0x{val:02X}"

# ══════════════════════════════════════════════════════════════════════════════
#  Field definitions
#  Each: (key_char, field_id, display_label, options_list | None)
# ══════════════════════════════════════════════════════════════════════════════
LEFT_FIELDS: List[Tuple] = [
    ("a", "addh",    "Addr High (ADDH)",   None),
    ("b", "addl",    "Addr Low  (ADDL)",   None),
    ("n", "netid",   "Network ID",         None),
    ("u", "baud",    "UART Baud Rate",     BAUD_OPTS),
    ("p", "parity",  "UART Parity/Frame",  PARITY_OPTS),
    ("r", "airrate", "Air Data Rate",      AIR_OPTS),
    ("c", "channel", "RF Channel",         CHAN_OPTS),
    ("v", "power",   "TX Power",           POWER_OPTS),
]
RIGHT_FIELDS: List[Tuple] = [
    ("s", "subpk",   "Sub-packet Size",    SUBPK_OPTS),
    ("t", "txmode",  "TX Mode",            TXMOD_OPTS),
    ("l", "lbt",     "LBT (Listen B4 TX)", BOOL_OPTS),
    ("e", "rssi_b",  "RSSI Byte Append",   BOOL_OPTS),
    ("i", "rssi_n",  "RSSI Noise Monitor", BOOL_OPTS),
    ("d", "repeat",  "Repeater Mode",      BOOL_OPTS),
    ("m", "wormd",   "WOR Role",           WORMD_OPTS),
    ("o", "wortm",   "WOR Period",         WORTM_OPTS),
]
ALL_FIELDS = LEFT_FIELDS + RIGHT_FIELDS

KEY_MAP = {k: (fid, lbl, opts) for k, fid, lbl, opts in ALL_FIELDS}
KEY_MAP["h"] = ("crypt_h", "Encrypt Key High Byte", None)
KEY_MAP["j"] = ("crypt_l", "Encrypt Key Low Byte",  None)

# ══════════════════════════════════════════════════════════════════════════════
#  Cell renderer
# ══════════════════════════════════════════════════════════════════════════════
def render_cell(key: str, label: str, value: str, modified: bool) -> str:
    """Return coloured cell content (no fixed width — caller uses fit())."""
    kb  = f"{C.KEY}[{key}]{C.RST}"
    mod = f"{C.ORG}*{C.RST}" if modified else f"{C.GRY}·{C.RST}"
    lbl = f"{C.GRY}{label}:{C.RST}"
    vc  = C.ORG if modified else C.CYNB
    val = f"{vc}{value}{C.RST}"
    return f" {kb} {mod} {lbl} {val} "

# ══════════════════════════════════════════════════════════════════════════════
#  Column header cell
# ══════════════════════════════════════════════════════════════════════════════
def col_header(title: str) -> str:
    return f" {C.AMBB}{title}{C.RST} "

# ══════════════════════════════════════════════════════════════════════════════
#  Full display
# ══════════════════════════════════════════════════════════════════════════════
def display(state: dict, orig: dict, port: str, demo: bool, pid: Optional[bytes],
            status: str = ""):
    any_mod = (state != orig)
    print_banner(port, demo, pid)

    # ── Main box ────────────────────────────────────────────────────────────
    title = "CONFIGURATION REGISTERS" + ("  ● UNSAVED CHANGES" if any_mod else "")
    p(box_top(title, W, any_mod))

    # Column headers
    p(box_row2(col_header("  Network & Radio Parameters"),
               col_header("  Packet · Features · WOR"),
               W, any_mod))
    p(box_divider(W, any_mod))

    # Parameter rows
    nrows = max(len(LEFT_FIELDS), len(RIGHT_FIELDS))
    for i in range(nrows):
        lc = LEFT_FIELDS[i]  if i < len(LEFT_FIELDS)  else None
        rc = RIGHT_FIELDS[i] if i < len(RIGHT_FIELDS) else None

        if lc:
            k, fid, lbl, opts = lc
            lcell = render_cell(k, lbl, fmt_value(fid, state, opts), state[fid] != orig[fid])
        else:
            lcell = ""

        if rc:
            k, fid, lbl, opts = rc
            rcell = render_cell(k, lbl, fmt_value(fid, state, opts), state[fid] != orig[fid])
        else:
            rcell = ""

        p(box_row2(lcell, rcell, W, any_mod))

    # Encryption row (full width)
    p(box_mid(W, any_mod))
    enc_on  = state["crypt_h"] != 0 or state["crypt_l"] != 0
    enc_mod = (state["crypt_h"] != orig["crypt_h"]) or (state["crypt_l"] != orig["crypt_l"])
    vc      = C.ORG if enc_mod else (C.GRN if enc_on else C.GRY)
    mh = f"{C.ORG}*{C.RST}" if (state["crypt_h"] != orig["crypt_h"]) else f"{C.GRY}·{C.RST}"
    ml = f"{C.ORG}*{C.RST}" if (state["crypt_l"] != orig["crypt_l"]) else f"{C.GRY}·{C.RST}"
    enc_summary = f"Key 0x{state['crypt_h']:02X}{state['crypt_l']:02X}" if enc_on else "No encryption"
    enc_line = (
        f" {C.KEY}[h]{C.RST} {mh} {C.GRY}Encrypt Key Hi:{C.RST} {vc}0x{state['crypt_h']:02X}{C.RST}"
        f"   {C.KEY}[j]{C.RST} {ml} {C.GRY}Encrypt Key Lo:{C.RST} {vc}0x{state['crypt_l']:02X}{C.RST}"
        f"   {C.GRY}→{C.RST} {vc}{enc_summary}{C.RST}"
    )
    p(box_full(enc_line, W, any_mod))

    # Raw bytes row
    p(box_mid(W, any_mod))
    raw_now  = encode_state(state)
    raw_hex  = " ".join(f"{b:02X}" for b in raw_now)
    raw_col  = C.ORG if any_mod else C.GRY
    raw_line = f" {C.DIM}Reg 00–08:{C.RST}  {raw_col}{raw_hex}{C.RST}"
    if any_mod:
        orig_hex = " ".join(f"{b:02X}" for b in encode_state(orig))
        raw_line += f"  {C.DIM}(was: {orig_hex}){C.RST}"
    p(box_full(raw_line, W, any_mod))
    p(box_bot(W, any_mod))

    # ── Status bar ──────────────────────────────────────────────────────────
    p()
    if status:
        p(f"  {status}")
        p()

    # ── Command bar ─────────────────────────────────────────────────────────
    if any_mod:
        n_mod = sum(1 for _, fid, _, _ in ALL_FIELDS if state[fid] != orig[fid])
        if state["crypt_h"] != orig["crypt_h"] or state["crypt_l"] != orig["crypt_l"]:
            n_mod += 1
        p(f"  {C.ORG}● {n_mod} field(s) modified{C.RST}  │  "
          f"{C.GRN}[W]{C.RST} Write to device  "
          f"{C.RED}[X]{C.RST} Discard changes  "
          f"{C.GRY}[Q]{C.RST} Quit")
    else:
        p(f"  {C.GRY}Press a key in {C.KEY}[brackets]{C.GRY} to edit a field.   "
          f"[Q] Quit{C.RST}")

# ══════════════════════════════════════════════════════════════════════════════
#  Option picker (full-screen menu)
# ══════════════════════════════════════════════════════════════════════════════
def pick_option(label: str, opts: list, current: int) -> Optional[int]:
    cur_idx = next((i for i, (k, _) in enumerate(opts) if k == current), 0)
    while True:
        cls()
        p(f"\n  {C.AMBB}▸ Edit field:{C.RST}  {C.WHT}{label}{C.RST}")
        p(f"  {C.GRY}{'─'*54}{C.RST}\n")
        for i, (k, v) in enumerate(opts):
            if i == cur_idx:
                p(f"  {C.HLB}{C.AMB} ▶  {v:<38}{C.RST}  {C.GRY}← current selection{C.RST}")
            else:
                p(f"     {C.GRY}{v}{C.RST}")
        p(f"\n  {C.GRY}↑ / k = up   ↓ / j = down   Enter = confirm   Esc = cancel{C.RST}")

        ch = getch()
        if ch == '\x1b':
            nxt = getch()
            if nxt == '[':
                arr = getch()
                if arr == 'A':  cur_idx = (cur_idx - 1) % len(opts)
                if arr == 'B':  cur_idx = (cur_idx + 1) % len(opts)
            else:
                return None
        elif ch in ('k', 'K'):  cur_idx = (cur_idx - 1) % len(opts)
        elif ch in ('j', 'J'):  cur_idx = (cur_idx + 1) % len(opts)
        elif ch in ('\r', '\n'):
            return opts[cur_idx][0]

# ══════════════════════════════════════════════════════════════════════════════
#  Numeric input (full-screen)
# ══════════════════════════════════════════════════════════════════════════════
def pick_numeric(label: str, current: int, lo: int = 0, hi: int = 255) -> Optional[int]:
    buf = str(current)
    while True:
        cls()
        p(f"\n  {C.AMBB}▸ Edit field:{C.RST}  {C.WHT}{label}{C.RST}")
        p(f"  {C.GRY}Range: {lo} – {hi}   (0x{lo:02X} – 0x{hi:02X}){C.RST}\n")
        try:
            v = int(buf) if buf else 0
            ok = lo <= v <= hi
        except ValueError:
            ok = False
        vc = C.GRN if ok else C.RED
        cursor = f"{C.AMB}▌{C.RST}"
        p(f"  {C.GRY}Value:{C.RST}  {vc}{buf}{cursor}")
        if ok:
            p(f"          {C.DIM}= 0x{int(buf):02X}{C.RST}")
        else:
            p(f"          {C.RED}✘ out of range{C.RST}")
        p(f"\n  {C.GRY}Type digits   Enter = confirm   Esc = cancel   Backspace = delete{C.RST}")

        ch = getch()
        if ch == '\x1b':
            return None
        if ch in ('\r', '\n'):
            try:
                v = int(buf)
                if lo <= v <= hi:
                    return v
            except ValueError:
                pass
        elif ch in ('\x7f', '\x08'):
            buf = buf[:-1]
        elif ch.isdigit():
            candidate = buf + ch
            try:
                if int(candidate) <= hi:
                    buf = candidate
            except ValueError:
                pass

# ══════════════════════════════════════════════════════════════════════════════
#  Serial helpers
# ══════════════════════════════════════════════════════════════════════════════
def open_port(port: str) -> serial.Serial:
    return serial.Serial(port=port, baudrate=9600, bytesize=8,
                         parity='N', stopbits=1, timeout=2.0)

def send_cmd(ser: serial.Serial, cmd: bytes) -> Optional[bytes]:
    for _ in range(3):
        ser.reset_input_buffer()
        ser.write(cmd)
        time.sleep(0.15)
        r = ser.read(64)
        if r:
            return r
        time.sleep(0.3)
    return None

def read_registers(ser: serial.Serial) -> Optional[bytes]:
    r = send_cmd(ser, bytes([0xC1, 0x00, 0x09]))
    if r and len(r) >= 12 and r[0] == 0xC1:
        return r[3:12]
    return None

def read_pid(ser: serial.Serial) -> Optional[bytes]:
    r = send_cmd(ser, bytes([0xC1, 0x80, 0x07]))
    if r and len(r) >= 10 and r[0] == 0xC1:
        return r[3:10]
    return None

def write_registers(ser: serial.Serial, raw: bytes) -> bool:
    cmd = bytes([0xC0, 0x00, 0x09]) + raw
    r = send_cmd(ser, cmd)
    return bool(r and len(r) >= 12 and r[0] == 0xC1)

# ══════════════════════════════════════════════════════════════════════════════
#  Spinner
# ══════════════════════════════════════════════════════════════════════════════
SPIN = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

def spin(msg: str, n: int = 8):
    for i in range(n):
        sys.stdout.write(f"\r  {C.AMB}{SPIN[i%10]}{C.RST}  {msg}   ")
        sys.stdout.flush()
        time.sleep(0.07)

# ══════════════════════════════════════════════════════════════════════════════
#  Mock data
# ══════════════════════════════════════════════════════════════════════════════
FACTORY_RAW = bytes([0x00,0x00,0x00,0x62,0x00,0x17,0x03,0x00,0x00])
MOCK_PID    = b'E90-900'

# ══════════════════════════════════════════════════════════════════════════════
#  Main interactive loop
# ══════════════════════════════════════════════════════════════════════════════
def run(port: str, demo: bool, ser: Optional[serial.Serial],
        raw: bytes, pid: Optional[bytes]):
    state  = decode_state(raw)
    orig   = copy.deepcopy(state)
    status = ""
    hide_cursor()
    try:
        while True:
            display(state, orig, port, demo, pid, status)
            status = ""

            ch = getch().lower()

            # ── Quit ──────────────────────────────────────────────────────
            if ch == 'q':
                if state != orig:
                    display(state, orig, port, demo, pid,
                            f"{C.YEL}⚠  Unsaved changes — discard and quit? (y/N){C.RST}")
                    if getch().lower() != 'y':
                        continue
                break

            # ── Write ─────────────────────────────────────────────────────
            elif ch == 'w':
                if state == orig:
                    status = f"{C.GRY}ℹ  No changes to write.{C.RST}"
                    continue
                display(state, orig, port, demo, pid,
                        f"{C.YEL}⚠  Write changes to device? (y/N){C.RST}")
                if getch().lower() != 'y':
                    status = f"{C.GRY}Write cancelled.{C.RST}"
                    continue
                new_raw = encode_state(state)
                if demo:
                    time.sleep(0.4)
                    status = (f"{C.YEL}[DEMO] Would write:{C.RST} "
                              f"{C.CYNB}{' '.join(f'{b:02X}' for b in new_raw)}{C.RST}")
                    orig = copy.deepcopy(state)
                elif ser:
                    display(state, orig, port, demo, pid,
                            f"{C.AMB}⠿  Writing registers to device…{C.RST}")
                    ok = write_registers(ser, new_raw)
                    if ok:
                        status = f"{C.GRN}✔  Registers written successfully.{C.RST}"
                        orig = copy.deepcopy(state)
                    else:
                        status = f"{C.RED}✘  Write failed — check connection and Mode 2.{C.RST}"
                else:
                    status = f"{C.RED}✘  No serial port available.{C.RST}"

            # ── Discard ───────────────────────────────────────────────────
            elif ch == 'x':
                if state == orig:
                    status = f"{C.GRY}ℹ  Nothing to discard.{C.RST}"
                    continue
                display(state, orig, port, demo, pid,
                        f"{C.RED}⚠  Discard ALL unsaved changes? (y/N){C.RST}")
                if getch().lower() == 'y':
                    state  = copy.deepcopy(orig)
                    status = f"{C.GRY}Changes discarded — restored original values.{C.RST}"
                else:
                    status = f"{C.GRY}Discard cancelled.{C.RST}"

            # ── Field edit ────────────────────────────────────────────────
            elif ch in KEY_MAP:
                fid, lbl, opts = KEY_MAP[ch]
                cur = state[fid]
                if opts:
                    v = pick_option(lbl, opts, cur)
                else:
                    v = pick_numeric(lbl, cur, 0, 255)
                if v is not None:
                    old_v  = state[fid]
                    state[fid] = v
                    is_mod = (state[fid] != orig[fid])
                    if v == old_v:
                        status = f"{C.GRY}No change to {lbl}.{C.RST}"
                    elif is_mod:
                        status = (f"{C.ORG}Modified:{C.RST}  {lbl}  →  "
                                  f"{C.CYNB}{fmt_value(fid, state, opts)}{C.RST}")
                    else:
                        status = (f"{C.GRN}Restored:{C.RST}  {lbl}  (matches original){C.RST}")
    finally:
        show_cursor()
        p()

# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(
        description="E90-DTU(900SL30) Interactive Configuration Editor",
        epilog="Press letter keys shown in [brackets] to edit each field.\n"
               "W = write  X = discard  Q = quit")
    ap.add_argument("-p","--port", default="/dev/ttyUSB0")
    ap.add_argument("-b","--baud", default=9600, type=int)
    ap.add_argument("--demo", action="store_true",
                    help="Demo mode — factory defaults, no hardware required")
    args = ap.parse_args()

    cls()
    for line, shade in zip(BANNER, SHADES):
        print(f"{shade}{line}{C.RST}")
    print(f"{C.GRY}{'─'*W}{C.RST}")
    print()

    if args.demo:
        print(f"  {C.YEL}⚠  Demo mode — factory defaults loaded, no hardware needed.{C.RST}")
        time.sleep(0.5)
        run(args.port + " [demo]", True, None, FACTORY_RAW, MOCK_PID)
        return

    print(f"  Connecting to {C.AMBB}{args.port}{C.RST} at {args.baud} bps …")
    print(f"  {C.GRY}Device must be in Mode 2  (M1=OFF, M0=ON){C.RST}\n")

    try:
        ser = open_port(args.port)
    except Exception as e:
        print(f"  {C.RED}✘  Cannot open port: {e}{C.RST}")
        print(f"  {C.GRY}Try:  python3 {sys.argv[0]} --demo{C.RST}\n")
        sys.exit(1)

    spin("Reading registers 0x00–0x08…", 10)
    raw = read_registers(ser)
    spin("Reading product ID…", 6)
    pid = read_pid(ser)
    print(f"\r  {C.GRN}✔  Data received.{C.RST}                         ")
    time.sleep(0.3)

    if not raw or len(raw) < 9:
        ser.close()
        print(f"\n  {C.RED}✘  No valid response from device.{C.RST}")
        print(f"  {C.GRY}Check: DIP switches in Mode 2 · cable connected{C.RST}\n")
        sys.exit(1)

    try:
        run(args.port, False, ser, raw, pid)
    finally:
        ser.close()

if __name__ == "__main__":
    main()
