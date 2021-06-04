#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# ADC test utility.

import time
import sys
import argparse
import socket
import matplotlib.pyplot as plt

from litex import RemoteClient

sys.path.append("..")
from peripherals.spi import *

from peripherals.spi import *
from peripherals.offset_dac import *
from peripherals.frontend import *
from peripherals.adf4360 import *
from peripherals.had1511 import *

# ADC Test -----------------------------------------------------------------------------------------

def adc_test(port, channel, length, downsampling, div, auto_setup, ramp=False, upload_mode="udp", csv="", plot=False): # FIXME: Add more parameters.
    assert channel == 1 # FIXME
    bus = RemoteClient(port=port)
    bus.open()

    spi = SPIDriver(bus)

    # PLL Init
    # --------

    print("PLL Init...")
    pll = ADF4360Driver(bus, spi)
    pll.init(
        control_value   = 0x403120,
        r_counter_value = 0x0007d1,
        n_counter_value = 0x04e142,
    )

    # ADC Init
    # --------

    print("ADC Init...")
    adc0 = HAD1511Driver(bus, spi, n=0)
    adc0.reset()
    adc0.downsampling.write(downsampling)
    if ramp:
        adc0.ramp()
    else:
        adc0.data_mode()

    # Offset DAC / Frontend Init
    # --------------------------

    print("OffsetDAC Init...")
    offsetdac = OffsetDACDriver(bus, spi)
    offsetdac.init()


    print("Frontend Init...")
    frontend = FrontendDriver(bus, spi, [adc0, None])

    if auto_setup:
        def ch1_auto_setup(debug=True): # FIXME: Very dumb Auto-Setup test, mostly to verify Frontend/Gains are behaving correctly, improve.
            print("Setting CH1 Frontend/Gain to default values...")
            frontend_value = FRONTEND_FULL_BANDWIDTH | FRONTEND_VGA_ENABLE | FRONTEND_DC_COUPLING
            assert div in ["100:1", "10:1", "1:1"]
            if div == "100:1":
                frontend_value |= FRONTEND_10_1_FIRST_DIVIDER | FRONTEND_10_1_SECOND_DIVIDER
            if div == "10:1":
                frontend_value |= FRONTEND_10_1_FIRST_DIVIDER
            frontend.set_frontend(0, frontend_value)
            adc0.set_reg(0x2b, 0x00)                  # 1X ADC Gain.
            frontend.set_vga(0, VGA_LOW_RANGE | 0x40) # Low VGA Gain to see Data but avoid saturation.

            # Do 2 OffsetDAC/VGA calibration loops:
            # - A First loop to find the rough OffsetDAC/Gain values.
            # - A Second loop to refine them.
            for loop in range(2):
                print(f"Centering ADC Data through OffsetDAC (loop {loop})...")
                best_offset = 0
                best_error  = 0xff
                for offset in range(0x2400, 0x2800, 1):
                    offsetdac.set_ch(0, offset)
                    _min, _max = adc0.get_range(duration=0.001)
                    _mean = _min + (_max - _min)/2
                    error = abs(_mean - 0xff/2)
                    if error < best_error:
                        best_error  = error
                        best_offset = offset
                        if debug:
                            print(f"OffsetDAC Best: 0x{offset:x} (ADC Min:{_min} Max: {_max} Mean: {_mean})")
                print(f"Best OffsetDAC 0x{best_offset:x}")
                offsetdac.set_ch(0, best_offset)

                print(f"Adjusting ADC Dynamic with through VGA (loop {loop})...")
                sat_margin   = 0x10
                best_gain    = 0
                best_dynamic = 0
                for gain in range(0x00, 0x80, 1):
                    frontend.set_vga(0, VGA_HIGH_RANGE | gain)
                    _min, _max = adc0.get_range(duration=0.001)
                    _dynamic = (_max - _min)
                    if (_min > sat_margin) and (_max < (0xff - sat_margin)):
                        if (_dynamic > best_dynamic):
                            best_gain    = gain
                            best_dynamic = _dynamic
                            if debug:
                                print(f"VGA Best: 0x{best_gain:x} (ADC Min:{_min} Max: {_max} Diff: {_dynamic})")
                print(f"Best VGA Gain: 0x{best_gain:x}")
                frontend.set_vga(0, VGA_HIGH_RANGE | best_gain)

        ch1_auto_setup()


    # ADC Statistics / Capture
    # ------------------------

    print("ADC Statistics...")
    adc0_min, adc0_max = adc0.get_range()
    adc0_samplerate    = adc0.get_samplerate()
    print(f"- Min: {adc0_min}")
    print(f"- Max: {adc0_max}")
    print(f"- Samplerate: ~{adc0_samplerate/1e6}MSa/s ({adc0_samplerate*8/1e9}Gb/s)")

    print("ADC Data Capture (to DRAM)...")
    adc0.capture(base=0x0000_0000, length=length)

    print("ADC Data Retrieve (from DRAM)...")
    adc_data = []

    def udp_data_retrieve(length):
        offset   = 0
        sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("192.168.1.100", 2000))
        while length > 0:
            bus.regs.dma_reader_enable.write(0)
            bus.regs.dma_reader_base.write(0x0000_0000 + offset)
            bus.regs.dma_reader_length.write(1024)
            bus.regs.dma_reader_enable.write(1)
            data, _ = sock.recvfrom(1024)
            for b in data:
                adc_data.append(b)
            length -= len(data)
            offset += len(data)

    def etherbone_data_retrieve(length):
        for i in range(length//4):
            word = bus.read(bus.mems.main_ram.base + 4*i)
            adc_data.append((word >> 0)  & 0xff)
            adc_data.append((word >> 8)  & 0xff)
            adc_data.append((word >> 16) & 0xff)
            adc_data.append((word >> 24) & 0xff)

    if upload_mode == "udp":
        udp_data_retrieve(length)
    elif upload_mode == "etherbone":
        etherbone_data_retrieve(length)
    else:
        raise ValueError

    if len(adc_data) > length:
        adc_data = adc_data[:length]


    # CSV Export
    # ----------

    if csv != "":
        # Note: Requires export LC_NUMERIC=en_US.utf-8 with GLScopeClient.
        f = open(csv, "w")
        f.write("Time, ADC0\n")
        for n, d in enumerate(adc_data):
            line = f"{n/adc0_samplerate:1.15f}, {d:f}\n"
            f.write(line)
        f.close()

    # Plot
    # ----

    if plot:
        print("Plot...")
        plt.plot(adc_data)
        plt.show()

    bus.close()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ADC test utility")
    parser.add_argument("--port",         default="1234",           help="Host bind port")
    parser.add_argument("--channel",      default=1,      type=int, help="ADC Channel: 1 (default), 2, 3, or 4.")
    parser.add_argument("--length",       default=1000,   type=int, help="ADC Capture Length (in Samples).")
    parser.add_argument("--downsampling", default=1,      type=int, help="ADC DownSampling (in Samples).")
    parser.add_argument("--ramp",         action="store_true",      help="Set ADC to Ramp mode.")
    parser.add_argument("--div",          default="100:1",          help="Set AFE Dividers (100:1 (default), 10:1 or 1:1)")
    parser.add_argument("--auto-setup",   action="store_true",      help="Run Frontend/Gain Auto-Setup.")
    parser.add_argument("--upload-mode",  default="udp",            help="Data upload mode: udp or etherbone.")
    parser.add_argument("--csv",          default="",               help="CSV Dump file.")
    parser.add_argument("--plot",         action="store_true",      help="Plot Data.")
    args = parser.parse_args()

    port = int(args.port, 0)

    adc_test(port=port,
        channel      = args.channel,
        length       = args.length,
        downsampling = args.downsampling,
        div          = args.div,
        auto_setup   = args.auto_setup,
        ramp         = args.ramp,
        upload_mode  = args.upload_mode,
        csv          = args.csv,
        plot         = args.plot
    )

if __name__ == "__main__":
    main()
