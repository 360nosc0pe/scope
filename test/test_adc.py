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

from peripherals.spi         import *
from peripherals.offset_dac  import *
from peripherals.frontend    import *
from peripherals.frontpanel  import *
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
    # Trigger Parameters.
    trig_offset,
    # Dump Parameters.
    dump="",
    # Plot Parameters.
    plot=False,
    # GLScopeClient Parameters
    glscopeclient=False,
    ):

    adc_channels_configs = [
        [0], [1], [2], [3], # 1 Channel.
        [0,   1], [2,   3], # 2 Channels.
        [0,   1,   2,   3], # 4 Channels.
    ]
    assert adc_channels in adc_channels_configs
    bus = RemoteClient(port=port)
    bus.open()

    # SPI (Common)
    # ------------
    spi = SPIDriver(bus)

    # Leds
    # ----
    leds = 0
    for n in adc_channels:
        leds |= FP_LEDS[f"CHANNEL_{n+1:d}"].value
    leds |= FP_LEDS["TRIGGER_AUTO"]
    leds |= FP_LEDS["RUN_STOP_GREEN"]
    bus.regs.fpleds_value.write(leds)

    # ADF4360 PLL Init
    # ----------------

    print("ADF4360 PLL Init...")
    pll = ADF4360PLLDriver(bus, spi)
    pll.init()

    # HAD1511 ADC Init
    # ----------------

    print("HAD1511 ADCs Init...")
    adcs = {}
    for n in adc_channels:
        if n%2 == 0:
            adc = HAD1511ADCDriver(bus, spi, n=n//2)
            adc.reset()
            adc.downsampling.write(adc_downsampling)
            adc.data_mode(n={1: [n], 2: [0, 1], 4: [0, 1]}[len(adc_channels)])
            if adc_mode == "ramp":
                adc.enable_ramp_pattern()
            adcs[n//2] = adc

    # Analog Front-End (AFE) Init...
    # ------------------------------

    print("Analog Front-End (AFE) Init...")

    print("- OffsetDAC Init...")

    offsetdac = OffsetDACDriver(bus, spi)
    offsetdac.init()


    print("- Frontend Init...")
    frontend = FrontendDriver(bus, spi, offsetdac, adcs)
    for n in adc_channels:
        frontend.set_coupling(n, afe_coupling)
        frontend.set_bwl(n, afe_bwl)
        afe_resolution = frontend.set_range(n, afe_range)
        if afe_center:
            frontend.center(n, offsetdac)

    # Trigger
    # -------

    trigger = TriggerDriver(bus)
    trigger.reset()

    # HAD1511 DMAs Init
    # -----------------
    adc_dmas = {}
    for n in adc_channels:
        if n%2 == 0:
            adc_dma = HAD1511DMADriver(bus, n=n//2)
            adc_dma.reset()
        adc_dmas[n//2] = adc_dma

    # ADC Statistics / Capture
    # ------------------------
    for n in adc_channels:
        print(f"ADC{n} Statistics...")
        adc_min, adc_max = adcs[n//2].get_range(n=n%2)
        adc_samplerate   = adcs[n//2].get_samplerate()/len(adc_channels)
        print(f"- Min: {adc_min}")
        print(f"- Max: {adc_max}")
        print(f"- Dynamic: {abs(adc_max - adc_min)}")
        print(f"- Samplerate: ~{adc_samplerate/1e6}MSa/s ({adc_samplerate*8/1e9}Gb/s)")


    # ADC Capture/DMA.

    if glscopeclient:
        waveform_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        waveform_sock.bind(("localhost", 50101))
        waveform_sock.listen(1)

        print("Waiting GLScopeClient connection...")
        waveform_client, _ = waveform_sock.accept()

    while True:
        if not glscopeclient:
            print("ADC Data Capture (to DRAM)...")
        adc_dma_bases = {
            0: 0x0000_0000,
            1: 0x0400_0000,
        }
        for n, adc_dma in adc_dmas.items():
            adc_dma.start(base=adc_dma_bases[n], length=2*len(adc_channels)*adc_samples) # FIXME X2 (For glscopeclient_trigger)
        trigger.enable()
        for n, adc_dma in adc_dmas.items():
            adc_dma.wait()

        if not glscopeclient:
            print("ADC Data Retrieve (from DRAM)...")
        dma_upload = DMAUploadDriver(bus)
        adc_data = []
        for n in adc_dmas.keys():
            adc_dump = dma_upload.run(base=adc_dma_bases[n], length=2*adc_samples) # FIXME X2 (For glscopeclient_trigger)
            if glscopeclient:
                for i in range(adc_samples):
                    if (adc_dump[i] < trig_offset) and (adc_dump[i+1] > trig_offset):
                        adc_dump = adc_dump[i:]
                        break
            if len(adc_dump) > min(len(adc_channels), 2)*adc_samples:
                adc_dump = adc_dump[:min(len(adc_channels), 2)*adc_samples]
            for m in range(min(len(adc_channels), 2)):
                offset = 4*m
                adc_data_m = []
                while (offset+4) <= len(adc_dump):
                    adc_data_m += adc_dump[offset:offset+4]
                    offset += 8
                adc_data.append(adc_data_m)

        if glscopeclient:
            waveform_client.send(bytes(adc_data[0]))
        else:
            break

    if glscopeclient:
        waveform_sock.close()

    # Dump
    # ----

    if dump != "":
        f = open(dump, "w")
        f.write("Time")
        for n in adc_channels:
            f.write(f", ADC{n:d}")
        f.write("\n")
        for i in range(len(adc_data[0])):
            line = f"{i/adc_samplerate:1.15f}"
            for n in range(len(adc_channels)):
                line += f" ,{adc_data[n][i]*afe_resolution:f}"
            line += "\n"
            f.write(line)
        f.close()

    # Plot
    # ----

    if plot:
        print("Plot...")
        for n in range(len(adc_channels)):
            plt.plot(adc_data[n])
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

    # Trigger Parameters.
    parser.add_argument("--trig-offset",    default="0",                     help="Trigger Offset (0-255).")

    # Dump Parameters.
    parser.add_argument("--dump", default="", help="Dump captured data to specified CSV file.")

    # Plot Parameters.
    parser.add_argument("--plot", action="store_true", help="Plot captured data.")

    # GLScopeClient Parameters.
    parser.add_argument("--glscopeclient", action="store_true", help="GLScopeClient mode.")


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
        # Trigger.
        trig_offset      = int(args.trig_offset, 0),
        # Dump.
        dump             = args.dump,
        # Plot.
        plot             = args.plot,
        # GLScopeCLient
        glscopeclient    = args.glscopeclient
    )

if __name__ == "__main__":
    main()
