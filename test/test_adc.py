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

    # SPI (Common)
    # ------------
    spi = SPIDriver(bus)

    # ADF4360 PLL Init
    # ----------------

    print("ADF4360 PLL Init...")
    pll = ADF4360Driver(bus, spi)
    pll.init(
        control_value   = 0x403120,
        r_counter_value = 0x0007d1,
        n_counter_value = 0x04e142,
    )

    # HAD1511 ADC Init
    # ----------------

    print("HAD1511 ADC Init...")
    adc0 = HAD1511Driver(bus, spi, n=0)
    adc0.reset()
    adc0.downsampling.write(downsampling)
    adc0.data_mode() if not ramp else adc.ramp()

    # Analog Front-End (AFE) Init...
    # ------------------------------

    print("Analog Front-End (AFE) Init...")

    print("- OffsetDAC Init...")

    offsetdac = OffsetDACDriver(bus, spi)
    offsetdac.init()


    print("- Frontend Init...")
    frontend = FrontendDriver(bus, spi, [adc0, None])
    if auto_setup:
        frontend.auto_setup(offsetdac=offsetdac, div=div)

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
