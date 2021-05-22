#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# SPDX-License-Identifier: BSD-2-Clause

# Frontpanel test utility.

import sys
import time
import datetime
import argparse
sys.path.append("..")

from litex import RemoteClient

from peripherals.frontpanel import FP_LEDS, FP_BTNS

# Leds Test ----------------------------------------------------------------------------------------

def leds_test(port):
    bus = RemoteClient(port=port)
    bus.open()

    leds_value = 0

    print("Leds ON  >>...")
    for i in range(19):
        leds_value |= (1<<i)
        bus.regs.leds_value.write(leds_value)
        time.sleep(0.05)

    print("Leds OFF >>...")
    for i in range(19):
        leds_value &= ~(1<<i)
        bus.regs.leds_value.write(leds_value)
        time.sleep(0.05)

    bus.close()

# Buttons Test  ------------------------------------------------------------------------------------

def buttons_test(port):
    bus = RemoteClient(port=port)
    bus.open()


    leds_value = 0
    bus.regs.leds_value.write(leds_value)

    print("Scanning buttons...")
    while True:
        # Scan buttons.
        old_value = bus.regs.btns_value.read()
        new_value = old_value
        while new_value == old_value:
            new_value = bus.regs.btns_value.read()
            time.sleep(0.1)

        # Find buttons.
        i = 0
        xor_value = (old_value ^ new_value)
        while xor_value & 0x1 != 0x1:
            xor_value >>= 1
            i += 1

        # Find it in FP_BTNS.
        for fp_btn in FP_BTNS:
            if fp_btn.value == (1 << i):
                print(f"{fp_btn.name} pressed.")
                break

        # If button has an associated led, toggle it.
        for fp_led in FP_LEDS:
            if fp_led.name == fp_btn.name:
                leds_value ^= fp_led.value
                bus.regs.leds_value.write(leds_value)

        time.sleep(0.1)

    bus.close()

# Video Terminal Test ------------------------------------------------------------------------------

def video_terminal_test(port):
    bus = RemoteClient(port=port)
    bus.open()

    def video_terminal_print(bus, s):
        # Write to SoC's UART.
        for c in s:
            # Flush SoC's Xover UART.
            while not bus.regs.uart_xover_rxempty.read():
                bus.regs.uart_xover_rxtx.read()
            bus.regs.uart_rxtx.write(ord(c))
            time.sleep(0.0001)

    banner = """
   ____ ____ ___                    ___
  |_  // __// _ \\___  ___  ___ ____/ _ \\___  ___
 _/_ </ _ \\/ // / _ \\/ _ \\(_-</ __/ // / _ \\/ -_)
/____/\\___/\\___/_//_/\\___/___/\\__/\\___/ .__/\\__/
                                     /_/
    \r"""
    video_terminal_print(bus, banner)

    msg = "Hello World from ScopeSoC on Siglent SDS1104X-E :)\n\r"
    video_terminal_print(bus, msg)

    while True:
        msg = datetime.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")
        msg += "\n\r"
        video_terminal_print(bus, msg)
        time.sleep(0.5)

    bus.close()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Frontpanel test utility")
    parser.add_argument("--port",     default="1234",      help="Host bind port")
    parser.add_argument("--leds",     action="store_true", help="Test leds")
    parser.add_argument("--buttons",  action="store_true", help="Test buttons")
    parser.add_argument("--terminal", action="store_true", help="Test Video Terminal")
    args = parser.parse_args()

    port = int(args.port, 0)

    if args.leds:
        leds_test(port=port)

    if args.buttons:
        buttons_test(port=port)

    if args.terminal:
        video_terminal_test(port=port)

if __name__ == "__main__":
    main()
