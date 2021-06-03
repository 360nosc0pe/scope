#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# ADC test utility.

import time
import argparse
import socket
import matplotlib.pyplot as plt

from litex import RemoteClient

from spi import *
from adf4360 import ADF4360

# Constants ----------------------------------------------------------------------------------------

# Frontend.

FRONTEND_10_1_FIRST_DIVIDER  = (1 << 1)
FRONTEND_10_1_SECOND_DIVIDER = (1 << 2)
FRONTEND_AC_COUPLING         = (0 << 3)
FRONTEND_DC_COUPLING         = (1 << 3)
FRONTEND_VGA_ENABLE          = (1 << 4)
FRONTEND_20MHZ_BANDWIDTH     = (0 << 5)
FRONTEND_FULL_BANDWIDTH      = (1 << 5)

# VGA.

VGA_LOW_RANGE  = (0 << 7)
VGA_HIGH_RANGE = (1 << 7)

# ADC.

ADC_CONTROL_FRAME_RST = (1 << 0)
ADC_CONTROL_DELAY_RST = (1 << 1)
ADC_CONTROL_DELAY_INC = (1 << 2)
ADC_CONTROL_STAT_RST  = (1 << 3)

ADC_RANGE_STAT_MIN    = (1 << 0)
ADC_RANGE_STAT_MAX    = (1 << 8)

# Peripherals --------------------------------------------------------------------------------------

# Offset DAC.

class OffsetDAC:
    def __init__(self, bus, spi):
        self.bus = bus
        self.spi = spi

    def init(self):
        self.bus.regs.offset_dac_control.write(1)

    def set_ch(self, n, value):
        getattr(self.bus.regs, f"offset_dac_ch{n+1}").write(value)

# Frontend.

class Frontend:
    def __init__(self, bus, spi, adcs):
        self.bus  = bus
        self.spi  = spi
        self.adcs = adcs
        self.frontend_values = [0x7a, 0x7a, 0x7a, 0x7a]

    def set_frontend(self, n, data):
        self.frontend_values[4-1-n] = data
        self.spi.write(SPI_CS_FRONTEND, [0x00] + self.frontend_values)

    def set_vga(self, n, gain):
        assert 0 <= gain <= 255
        self.spi.write(SPI_CS_CH1_VGA + n, [gain])

    def set_ch1_1v(self):
        self.set_frontend(0, 0x7e)
        self.set_vga(0, 0x1f)
        self.adcs[0].set_reg(0x2b, 0x00)

    def set_ch1_100mv(self):
        self.set_frontend(0, 0x78)
        self.set_vga(0, 0xad)
        self.adcs[0].set_reg(0x2b, 0x00)

# ADC.

class ADC:
    def __init__(self, bus, spi, n):
        self.bus     = bus
        self.spi     = spi
        self.n       = n
        self.control      = getattr(bus.regs, f"adc{n}_control")
        self.downsampling = getattr(bus.regs, f"adc{n}_downsampling")
        self.range        = getattr(bus.regs, f"adc{n}_range")
        self.count        = getattr(bus.regs, f"adc{n}_count")

    def reset(self):
        self.control.write(ADC_CONTROL_FRAME_RST)

    def set_reg(self, reg, value):
        self.spi.write(SPI_CS_ADC0 + self.n, [reg, (value >> 8) & 0xff, value & 0xff])

    def data_mode(self):
        self.set_reg(0, 0x0001)
        time.sleep(.1)
        self.set_reg(0xF, 0x200)
        time.sleep(.1)
        self.set_reg(0x31, 0x0001)
        #self.set_reg(0x53, 0x0000)
        #self.set_reg(0x31, 0x0008)
        #self.set_reg(0x53, 0x0004)

        self.set_reg(0x0F, 0x0000)
        self.set_reg(0x30, 0x0008)
        self.set_reg(0x3A, 0x0202)
        self.set_reg(0x3B, 0x0202)
        self.set_reg(0x33, 0x0001)
        #self.set_reg(0x2B, 0x0222)
        self.set_reg(0x2A, 0x2222)
        self.set_reg(0x25, 0x0000)
        self.set_reg(0x31, 0x0001) # clk_divide = /1, single channel interleaving ADC1..4

    def ramp(self):
        self.set_reg(0x25, 0x0040)

    def single(self, pattern):
        self.set_reg(0x25, 0x0010)
        self.set_reg(0x26, pattern)

    def dual(self, pattern0, pattern1):
        self.set_reg(0x25, 0x0020)
        self.set_reg(0x26, pattern0)
        self.set_reg(0x27, pattern1)

    def pat_deskew(self):
        self.set_reg(0x25, 0x0000)
        self.set_reg(0x45, 2)

    def pat_sync(self):
        self.set_reg(0x25, 0x0000)
        self.set_reg(0x45, 1)

    def get_range(self, duration=0.5):
        self.control.write(ADC_CONTROL_STAT_RST)
        time.sleep(duration)
        adc_min = (self.range.read() >> 0) & 0xff
        adc_max = (self.range.read() >> 8) & 0xff
        return adc_min, adc_max

    def get_samplerate(self, duration=0.5):
        self.control.write(ADC_CONTROL_STAT_RST)
        time.sleep(duration)
        adc_count = self.count.read()
        return adc_count/duration

    def capture(self, base, length):
        self.bus.regs.adc0_dma_enable.write(0)
        self.bus.regs.adc0_dma_base.write(base)
        self.bus.regs.adc0_dma_length.write(length + 1024) # FIXME: +1024.
        self.bus.regs.adc0_dma_enable.write(1)
        while not (self.bus.regs.adc0_dma_done.read() & 0x1):
            pass

# ADC Test -----------------------------------------------------------------------------------------

def adc_test(port, channel, length, downsampling, div, auto_setup, ramp=False, upload_mode="udp", csv="", plot=False): # FIXME: Add more parameters.
    assert channel == 1 # FIXME
    bus = RemoteClient(port=port)
    bus.open()

    spi = SPI(bus)

    # PLL Init
    # --------

    print("PLL Init...")
    pll = ADF4360(bus, spi)
    pll.init(
        control_value   = 0x403120,
        r_counter_value = 0x0007d1,
        n_counter_value = 0x04e142,
    )

    # ADC Init
    # --------

    print("ADC Init...")
    adc0 = ADC(bus, spi, n=0)
    adc0.reset()
    adc0.downsampling.write(downsampling)
    if ramp:
        adc0.ramp()
    else:
        adc0.data_mode()

    # Offset DAC / Frontend Init
    # --------------------------

    print("OffsetDAC Init...")
    offsetdac = OffsetDAC(bus, spi)
    offsetdac.init()


    print("Frontend Init...")
    frontend = Frontend(bus, spi, [adc0, None])

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
        f = open(csv, "w")
        f.write("Time; ADC0\n")
        for n, d in enumerate(adc_data):
            # FIXME: Use , as decimal point and ; as separator due to scopehal limitation.
            # https://github.com/azonenberg/scopehal/issues/494
            line = f"{n/adc0_samplerate}; {d:f}\n"
            line = line.replace(".", ",")
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
