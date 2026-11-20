/*
 * Read-only 64 KiB flash dumper for VEIKK S640 stock unit (GD32F150R8T6).
 *
 * The unit is RDP1.  With CDBGPWRUPREQ asserted, CPU reads from main flash
 * fault.  The host clears only CDBGPWRUPREQ, the CPU copies one 4 KiB chunk
 * into SRAM, and the host reasserts debug power to read the buffer.
 *
 * This code never touches the FMC, option bytes, or flash write registers.
 *
 */

.syntax unified
.cpu cortex-m3
.thumb

.section .text
.global _start
.global _fault

/* Vector table at 0x20000000.  Stack top is below the 4 KiB buffer. */
.word 0x20001000
.word _start
.rept 14
.word _fault
.endr

.thumb_func
_start:
    cpsid i
    ldr r0, =0xE000ED08
    ldr r1, =0x20000000
    str r1, [r0]          /* VTOR = SRAM vector table */
    ldr r0, =0xE000E010
    movs r1, #0
    str r1, [r0]          /* stop SysTick */
    ldr r0, =0xE000ED28
    ldr r1, =0xFFFFFFFF
    str r1, [r0]          /* clear CFSR */
    str r1, [r0, #4]      /* clear HFSR */

    ldr r0, =0x20000100
    movs r1, #0
    str r1, [r0]          /* CMD */
    str r1, [r0, #4]      /* ADDR */
    str r1, [r0, #8]      /* LEN */
    str r1, [r0, #12]     /* DONE */
    str r1, [r0, #16]     /* FAULT */

wait_cmd:
    ldr r1, [r0]
    cmp r1, #1
    bne wait_cmd

    movs r1, #0
    str r1, [r0]          /* clear CMD */
    str r1, [r0, #12]     /* clear DONE */
    str r1, [r0, #16]     /* clear FAULT */

    /*
     * Give the host time to clear CDBGPWRUPREQ. 
     * 4000000 iterations take about 3s. Not sure why its running at 8MHz
     * The host also uses an 8s clear window and retries a failed chunk.
     */
    ldr r3, =4000000
delay:
    subs r3, r3, #1
    bne delay

    ldr r1, [r0, #4]      /* source flash address */
    ldr r2, [r0, #8]      /* byte count, multiple of 4 */
    ldr r3, =0x20001000   /* destination buffer */
copy_loop:
    ldr r4, [r1] 	/* the flash read.. */
    str r4, [r3]
    adds r1, #4 	/* increase source pointer */
    adds r3, #4 	/* increase dest pointer */
    subs r2, #4 	/* decrease remaining bytes */
    bne copy_loop

    movs r1, #1
    str r1, [r0, #12]     /* DONE */
    b wait_cmd

.thumb_func
_fault:
    ldr r0, =0x20000110
    ldr r1, =0xDEADBEEF
    str r1, [r0]
fault_loop:
    b fault_loop

.ltorg
