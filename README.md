# GD32F150R8T6 RDP1 Bypass PoC
 
This proof of concept demonstrates an SRAM-assisted readout of RDP1-protected flash on a GD32F150R8T6. It was inspired by the published GigaVulnerability #2 research.
 
- Kovrizhnykh, A. — [GigaVulnerability: readout protection bypass on GigaDevice GD32 MCUs](https://ptswarm.com/blog/gigavulnerability-readout-protection-bypass-on-gigadevice-gd32-mcus/)
- Obermaier, J. et al. — [One Exploit to Rule them All? On the Security of Drop-in Replacement and Counterfeit Microcontrollers (USENIX WOOT '20)](https://files.usenix.org/s3fs-public/cdn/woot20-paper-obermaier.pdf)
 
The dumper can read from flash in the range `0x08000000..0x0800FFFF`. It does not call the FMC, does not unlock flash, and does not touch option bytes. The host writes DAP control registers and SRAM through the debugger, and clears `CDBGPWRUPREQ` while each chunk is copied.
 
https://github.com/user-attachments/assets/70245a5a-96dc-4752-aa36-cb83f2535a62




## Requirements
- Debugger (I used RP2040)
- GD32F150R8T6 (device id = 0x13030410)
## Build
 
```sh
cd dumper
make
```
 
or:
```sh
arm-none-eabi-as -mcpu=cortex-m3 -mthumb sram_dumper.S -o sram_dumper.o
arm-none-eabi-ld -Ttext=0x20000000 -e _start sram_dumper.o -o sram_dumper.elf
arm-none-eabi-objcopy -O binary sram_dumper.elf sram_dumper.bin
```
 
## Run
 
```sh
openocd -f interface/cmsis-dap.cfg -c "transport select swd" -f target/stm32f1x.cfg -c "init; flash info 0"
```
 
Assuming tcl port 6666
 
```sh
uv run host.py --image dumper/sram_dumper.bin --output /path/to/file.bin
```
`--image` must be relative to OpenOCD's cwd, and have no spaces.
 
| Option | Meaning |
|---|---|
| `--start N` | First 4 KiB chunk (default 0) |
| `--chunks N` | Number of chunks (default 16 for 64 KiB) |
| `--clear-seconds S` | Debug-power-clear window (default 8 s) |
| `--attempts N` | Per-chunk retries (default 3) |
| `--image PATH` | Prebuilt dumper binary |
| `--host`, `--port` | OpenOCD Tcl endpoint |
 
## How?
 
Even with RDP1 enabled, the debugger can still read and write data to SRAM. RDP1 doesn't restrict the AHB-AP's access to SRAM, so the debugger can still write and run code there.
 
> Previously, it was observed that on the investigated GD32E230 microcontroller, flash memory locking occurs when the debug power domain is enabled — that is, when the `CDBGPWRUPREQ` bit in the CTRL/STAT DP register is set — and that resetting this bit deactivates the lock after a full microcontroller reset. ([source](https://ptswarm.com/blog/gigavulnerability-readout-protection-bypass-on-gigadevice-gd32-mcus/#:~:text=Previously,reset%2E))
 
The host script did not issue a full MCU reset for a successful readout from our chip. This differs from the GD32E230 behavior PT describes above.
 
Our communication method is simply another region of SRAM:
 
1. Write dumper program to SRAM
2. Debugger tells dumper to dump by setting `CMD` to 1, clears `CDBGPWRUPREQ`, waits for 8 seconds
3. Dumper copies flash to SRAM mailbox region
4. Debugger asserts `CDBGPWRUPREQ` again, reads SRAM command block. If `DONE`=1 and `FAULT`=0, host dumps mailbox region to disk
5. Step 2 but host tells dumper to copy next source address
The dumper's command block is at `0x20000100`:
 
| Offset | Word |
|---|---|
| `+0x00` | `CMD` (`1` starts a copy) |
| `+0x04` | Flash source address |
| `+0x08` | Byte count (multiple of 4) |
| `+0x0C` | `DONE` |
| `+0x10` | `FAULT` (`0xDEADBEEF` if the fault handler ran, e.g. on an illegal flash access) |
 
The 4 KiB destination is `0x20001000..0x20001FFF`. The vector table is at `0x20000000`; the entry is `0x20000041`.
 
For each chunk the host writes the address and length, sets `CMD = 1`, waits 50 ms, clears `CDBGPWRUPREQ` (`DP CTRL/STAT = 0x40000000`), waits 8 s, then reasserts both power requests (`0x50000000`). It accepts the chunk only when `DONE = 1` and `FAULT = 0`.
 
## Timing Notes
 
The dumper waits about 3 seconds (probably not needed) to give the host time to clear `CDBGPWRUPREQ` before proceeding, the host's default 8s is a safety margin above that. the loop timing suggested a core clock below the expected 72 MHz, roughly 8 MHz, though neither the active clock source nor the exact frequency was confirmed.
 
After a fresh dump, the first chunk attempt may end with `DONE = 0` and fail. A retry succeeded in the recorded run.
 
