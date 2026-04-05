#!/usr/bin/env python3
"""
E90-DTU — Hardware-in-the-loop test
Reads registers from the device, validates the response, and prints a report.
Usage: python3 test_hw.py [--port /dev/ttyUSB0]
Exit code 0 = PASS, 1 = FAIL
"""

import sys, argparse, time
sys.path.insert(0, __file__.rsplit('/', 1)[0])  # allow import from same dir

import serial as _serial

# ── Reuse protocol helpers from dtu.py ──────────────────────────────────────
from dtu import open_port, send_cmd, read_registers, read_pid, decode_state

PASS = "\033[38;5;120m✔  PASS\033[0m"
FAIL = "\033[38;5;203m✘  FAIL\033[0m"
INFO = "\033[38;5;87m·\033[0m "

def check(label: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    print(f"  {status}  {label}" + (f"  — {detail}" if detail else ""))
    return ok

def main():
    ap = argparse.ArgumentParser(description="E90-DTU hardware test")
    ap.add_argument("-p", "--port", default="/dev/ttyUSB0")
    args = ap.parse_args()

    print(f"\n\033[1;38;5;214m  E90-DTU Hardware Test\033[0m")
    print(f"  Port: {args.port}\n")

    results = []

    # ── 1. Open serial port ──────────────────────────────────────────────────
    try:
        ser = open_port(args.port)
        results.append(check("Serial port open", True, args.port))
    except Exception as e:
        results.append(check("Serial port open", False, str(e)))
        print(f"\n  \033[38;5;203mAborted — cannot open port.\033[0m\n")
        sys.exit(1)

    # ── 2. Read product ID ───────────────────────────────────────────────────
    pid = read_pid(ser)
    pid_str = (''.join(chr(b) if 32 <= b < 127 else '.' for b in pid)) if pid else None
    results.append(check("Read Product ID", pid is not None,
                         pid_str or "no response"))

    # ── 3. Read registers ────────────────────────────────────────────────────
    raw = read_registers(ser)
    results.append(check("Read registers (0x00–0x08)", raw is not None,
                         f"{len(raw)} bytes" if raw else "no response"))

    # ── 4. Validate register length ─────────────────────────────────────────
    if raw:
        results.append(check("Register payload length == 9", len(raw) == 9,
                             f"got {len(raw)}"))

    # ── 5. Decode fields ─────────────────────────────────────────────────────
    if raw and len(raw) == 9:
        try:
            state = decode_state(raw)
            results.append(check("Decode register fields", True))

            # Print decoded values
            print()
            print(f"  {INFO} \033[38;5;242mDecoded registers:\033[0m")
            for k, v in state.items():
                print(f"       {k:<10} = {v}")

            # Sanity checks on field ranges
            results.append(check("ADDH in 0–255",       0 <= state["addh"]    <= 255))
            results.append(check("ADDL in 0–255",       0 <= state["addl"]    <= 255))
            results.append(check("Channel in 0–80",     0 <= state["channel"] <= 80))
            results.append(check("Baud index in 0–7",   0 <= state["baud"]    <= 7))
            results.append(check("Air rate index in 0–7", 0 <= state["airrate"] <= 7))
            results.append(check("Power index in 0–3",  0 <= state["power"]   <= 3))

        except Exception as e:
            results.append(check("Decode register fields", False, str(e)))

    ser.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    n_pass = sum(results)
    n_fail = len(results) - n_pass
    print()
    print(f"  {'─'*50}")
    print(f"  Results: {n_pass}/{len(results)} passed"
          + (f"  \033[38;5;203m({n_fail} failed)\033[0m" if n_fail else "  \033[38;5;120mAll OK\033[0m"))
    print()
    sys.exit(0 if n_fail == 0 else 1)

if __name__ == "__main__":
    main()
