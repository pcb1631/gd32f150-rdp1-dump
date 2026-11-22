from __future__ import annotations

import argparse
import hashlib
import socket
import tempfile
import time
from pathlib import Path

LOAD_ADDR = 0x20000000
ENTRY = 0x20000041
STACK = 0x20001000
CMD = 0x20000100
ADDR = 0x20000104
LEN = 0x20000108
DONE = 0x2000010C
FAULT = 0x20000110
BUFFER = 0x20001000
FLASH_BASE = 0x08000000
CHUNK_SIZE = 0x1000
WAIT_LOOP_PCS = ("20000068", "2000006a", "2000006c")


def rpc(sock: socket.socket, command: str) -> tuple[int, str]:
    wrapped = (
        "set code [catch {capture {" + command + "}} result]; "
        'format "%s\\n%s" $code $result'
    )
    sock.sendall(wrapped.encode("ascii") + b"\x1a")
    data = bytearray()
    while b"\x1a" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("OpenOCD closed the Tcl connection")
        data.extend(chunk)
    payload, _ = data.split(b"\x1a", 1)
    text = payload.decode("utf-8", errors="replace").strip()
    status, _, body = text.partition("\n")
    return int(status), body


def run(sock: socket.socket, command: str, quiet: bool = False) -> tuple[int, str]:
    status, body = rpc(sock, command)
    if not quiet:
        print(f"> {command}\n{body}\n", flush=True)

    if status:
        raise RuntimeError(f"status: {status}, {body}")
        
    return status, body


def word(sock: socket.socket, address: int) -> int:
    status, body = run(sock, f"mdw {address:#x} 1", quiet=True)
    if status:
        raise RuntimeError(f"mdw {address:#x} failed: {body}")
    return int(body.split(":", 1)[1].strip(), 16)


def init_dumper(sock: socket.socket, image: Path) -> None:
    run(sock, "halt", quiet=True)
    status, body = run(sock, f"load_image {image} {LOAD_ADDR:#x} bin", quiet=True)
    if status:
        raise RuntimeError(f"load_image failed: {body}")
    for command in (
        f"reg msp {STACK:#x}",
        f"reg psp {STACK:#x}",
        "reg control 0",
        "reg primask 1",
        "reg basepri 0",
        "reg faultmask 0",
        "reg xPSR 0x01000000",
        f"reg pc {ENTRY:#x}",
    ):
        status, body = run(sock, command, quiet=True)
        if status:
            raise RuntimeError(f"{command}: {body}")

    run(sock, f"mww {CMD:#x} 0", quiet=True)
    run(sock, "resume", quiet=True)
    time.sleep(0.2)
    run(sock, "halt", quiet=True)
    status, body = run(sock, "reg pc", quiet=True)
    if not any(pc in body.lower() for pc in WAIT_LOOP_PCS):
        raise RuntimeError(f"dumper did not reach its wait loop: {body}")
    run(sock, "resume", quiet=True)
    time.sleep(0.1)
    dhcsr = word(sock, 0xE000EDF0)
    if dhcsr & 0x20000:
        raise RuntimeError("CPU is still halted")


def dump_chunk(
    sock: socket.socket,
    image: Path,
    index: int,
    clear_seconds: float,
    attempts: int,
) -> bytes:
    address = FLASH_BASE + index * CHUNK_SIZE
    for attempt in range(1, attempts + 1):
        print(
            f"chunk {index}: {address:#010x} (attempt {attempt})",
            flush=True,
        )
        run(sock, f"mww {ADDR:#x} {address:#x}", quiet=True)
        run(sock, f"mww {LEN:#x} {CHUNK_SIZE:#x}", quiet=True)
        run(sock, f"mww {DONE:#x} 0", quiet=True)
        run(sock, f"mww {FAULT:#x} 0", quiet=True)
        run(sock, f"mww {CMD:#x} 1", quiet=True)
        time.sleep(0.05)

        # Drop only CDBGPWRUPREQ so the core can read flash.  CSYSPWRUPREQ
        # stays set, and the host reasserts both after the copy.
        run(sock, "stm32f1x.dap dpreg 0x4 0x40000000", quiet=True)
        time.sleep(clear_seconds)
        run(sock, "stm32f1x.dap dpreg 0x4 0x50000000", quiet=True)

        done = word(sock, DONE)
        fault = word(sock, FAULT)
        print(f"done={done:#x} fault={fault:#x}", flush=True)
        if done == 1 and fault == 0:
            with tempfile.TemporaryDirectory() as tmp:
                chunk_path = Path(tmp) / f"chunk{index:02d}.bin"
                status, body = run(
                    sock,
                    f"dump_image {chunk_path} {BUFFER:#x} {CHUNK_SIZE:#x}",
                    quiet=True,
                )
                if status:
                    raise RuntimeError(f"dump_image failed: {body}")
                data = chunk_path.read_bytes()
            if len(data) != CHUNK_SIZE:
                raise RuntimeError(f"short chunk: {len(data)}")
            return data

        print("retrying chunk after reinitializing the dumper ...", flush=True)
        init_dumper(sock, image)

    raise RuntimeError(f"chunk {index} failed after {attempts} attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description="GD32F150R8T6 RDP1 flash dump via SRAM dumper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6666)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path, default=Path("./dump.bin"))
    parser.add_argument("--start", type=int, default=0, help="first 4 KiB chunk")
    parser.add_argument("--chunks", type=int, default=16, help="number of chunks")
    parser.add_argument("--clear-seconds", type=float, default=8.0)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()

    if not args.image or not args.image.is_file():
        print("Include SRAM dumper with --image </path/to/file.bin>")
        raise SystemExit(
            f"dumper image not found: {args.image}\n"
        )

    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.settimeout(60)
        init_dumper(sock, args.image)

        result = bytearray()
        for index in range(args.start, args.start + args.chunks):
            result.extend(
                dump_chunk(sock, args.image, index, args.clear_seconds, args.attempts)
            )

        run(sock, "halt", quiet=True)
        args.output.write_bytes(result)
        print(f"wrote {len(result)} bytes to {args.output}")
        print(f"sha256: {hashlib.sha256(result).hexdigest()}")


if __name__ == "__main__":
    main()
