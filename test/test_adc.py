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

import matplotlib.pyplot as plt

from litex import RemoteClient

sys.path.append("..")
from peripherals.spi import *

from peripherals.spi         import *
from peripherals.offset_dac  import *
from peripherals.frontend    import *
from peripherals.trigger     import *
from peripherals.adf4360_pll import *
from peripherals.had1511_adc import *
from peripherals.dma_upload import *

# ADC Test -----------------------------------------------------------------------------------------

def adc_test(port,
    # ADC Parameters.
    adc_channels, adc_samples, adc_downsampling, adc_mode,
    # AFE Parameters.
    afe_range, afe_coupling, afe_bwl, afe_center,
    # Dump Parameters.
    dump="",
    # Plot Parmeters.
    plot=False):

    for adc_channel in adc_channels:
        assert adc_channel in [0, 1, 2, 3]
    bus = RemoteClient(port=port)
    bus.open()

    # SPI (Common)
    # ------------
    spi = SPIDriver(bus)

    # ADF4360 PLL Init
    # ----------------

    print("ADF4360 PLL Init...")
    pll = ADF4360PLLDriver(bus, spi)
    pll.init()

    # HAD1511 ADC Init
    # ----------------

    print("HAD1511 ADC Init...")
    adc = HAD1511ADCDriver(bus, spi, n=adc_channels[0])
    adc.reset()
    adc.downsampling.write(adc_downsampling)
    adc.data_mode()
    if adc_mode == "ramp":
        adc.enable_ramp_pattern()

    # Analog Front-End (AFE) Init...
    # ------------------------------

    print("Analog Front-End (AFE) Init...")

    print("- OffsetDAC Init...")

    offsetdac = OffsetDACDriver(bus, spi)
    offsetdac.init()


    print("- Frontend Init...")
    frontend = FrontendDriver(bus, spi, adc)
    frontend.set_coupling(afe_coupling)
    frontend.set_bwl(afe_bwl)
    afe_resolution = frontend.set_range(afe_range)
    if afe_center:
        frontend.center(offsetdac)

    # Trigger
    # -------

    trigger = TriggerDriver(bus)
    trigger.reset()

    # HAD1511 DMA Init
    # ----------------
    adc_dma = HAD1511DMADriver(bus, n=adc_channels[0])
    adc_dma.reset()

    # ADC Statistics / Capture
    # ------------------------

    print("ADC Statistics...")
    adc_min, adc_max = adc.get_range()
    adc_samplerate   = adc.get_samplerate()
    print(f"- Min: {adc_min}")
    print(f"- Max: {adc_max}")
    print(f"- Dynamic: {adc_max - adc_min}")
    print(f"- Samplerate: ~{adc_samplerate/1e6}MSa/s ({adc_samplerate*8/1e9}Gb/s)")

    print("ADC Data Capture (to DRAM)...")
    adc_dma.start(base=0x0000_0000, length=adc_samples)
    trigger.enable()
    adc_dma.wait()

    print("ADC Data Retrieve (from DRAM)...")
    dma_upload = DMAUploadDriver(bus)
    adc_data   = dma_upload.run(base=0x0000_0000, length=adc_samples)
    if len(adc_data) > adc_samples:
        adc_data = adc_data[:adc_samples]

    # Dump
    # ----

    if dump != "":
        # Note: Requires export LC_NUMERIC=en_US.utf-8 with GLScopeClient.
        f = open(dump, "w")
        f.write("Time, ADC\n")
        for n, d in enumerate(adc_data):
            line = f"{n/adc_samplerate:1.15f}, {d*afe_resolution:f}\n"
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
    parser = argparse.ArgumentParser(description="ADC test utility.")
    parser.add_argument("--port",              default="1234",           help="Host bind port.")
    # ADC Parameters.
    parser.add_argument("--adc-channels",     default="0",       type=str, help="ADC Channels: 0 (default), 1, 2, 3 or combinations (01, 23).")
    parser.add_argument("--adc-samples",      default=1000,      type=int, help="ADC Capture Samples (default=1000).")
    parser.add_argument("--adc-downsampling", default=1,         type=int, help="ADC DownSampling Ratio (default=1).")
    parser.add_argument("--adc-mode",         default="capture",           help="ADC Mode: capture (default), ramp.")

    # AFE Parameters.
    parser.add_argument("--afe-range",      default=10,          type=float, help="Analog Front-End Dynamic Range: 5mV to 800V (default=10V).")
    parser.add_argument("--afe-coupling",   default="dc",                    help="Analog Front-End Coupling: dc (default) or ac.")
    parser.add_argument("--afe-bwl",        default="full",                  help="Analog Front-End Bandwidth Limitation: full (default) or 20mhz")
    parser.add_argument("--afe-center",     action="store_true",             help="Center Signal with Offset DAC.")

    # Dump Parameters.
    parser.add_argument("--dump", default="", help="Dump captured data to specified CSV file.")

    # Plot Parameters.
    parser.add_argument("--plot", action="store_true", help="Plot captured data.")

    args = parser.parse_args()

    port = int(args.port, 0)

    adc_test(port=port,
        # ADC.
        adc_channels     = [int(c, 0) for c in args.adc_channels],
        adc_samples      = args.adc_samples,
        adc_downsampling = args.adc_downsampling,
        adc_mode         = args.adc_mode,
        # AFE.
        afe_range        = args.afe_range,
        afe_coupling     = args.afe_coupling,
        afe_bwl          = args.afe_bwl,
        afe_center       = args.afe_center,
        # Dump.
        dump             = args.dump,
        # Plot.
        plot             = args.plot
    )

if __name__ == "__main__":
    main()
