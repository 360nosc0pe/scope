#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# ADC test utility.

import time
import matplotlib.pyplot as plt

from litex import RemoteClient

bus = RemoteClient()
bus.open()

def spi_write(cs, data):
    bus.regs.spi_cs.write(1 << cs)
    d = int.from_bytes(data, byteorder = 'big')
    d <<= ((6 - len(data))*8)
    bus.regs.spi_mosi.write(d)
    bus.regs.spi_control.write(0x01 | ((len(data) * 8) << 8))

class Clock:
    def init(self):
        self.set(b"\x40\x31\x20") # CONTROL
        self.set(b"\x04\xE1\x42") # NCOUNTER
        self.set(b"\x00\x07\xD1") # RCOUNTER

    def set(self, x):
        spi_write(0, x)

class OffsetDAC:
    def init(self):
        bus.regs.offset_dac_control.write(1)

    def set_ch(self, ch, val):
        getattr(bus.regs, f"offset_dac_ch{ch+1}").write(val)

# frontend init
class Frontend:
    def __init__(self, adc0, adc1, offsetdac):
        self.adcs = [adc0, adc1]
        self.offsetdac = offsetdac

    def set_adc_reg(self, adc, reg, value):
        self.adcs[adc].set_reg(reg, value)

    def set_frontend(self, data):
        spi_write(3, data)

    def set_vga(self, ch, gain):
        spi_write(4 + ch, [gain])

    def set_ch1_1v(self):
        self.set_frontend(bytes([0, 0x7A, 0x7A, 0x7A, 0x7E]))
        self.set_vga(0, 0x1F)
        self.set_adc_reg(0, 0x2B, 00)

    def set_ch1_100mv(self):
        self.set_frontend(bytes([0, 0x7A, 0x7A, 0x7A, 0x78]))
        self.set_vga(0, 0xad)
        self.set_adc_reg(0, 0x2B, 00)

class ADC:
    def __init__(self, ch):
        self.ch = ch

    def reset(self):
        bus.regs.adc0_control.write(1)
        bus.regs.adc0_control.write(0)
        bus.regs.adc1_control.write(1)
        bus.regs.adc1_control.write(0)

    def data_mode(self):
        self.set_reg(0, 0x0001)
        time.sleep(.1)
        self.set_reg(0xF, 0x200)
        time.sleep(.1)
        self.set_reg(0x31, 0x0001)
#        self.set_reg(0x53, 0x0000)
#        self.set_reg(0x31, 0x0008)
#        self.set_reg(0x53, 0x0004)

        self.set_reg(0x0F, 0x0000)
        self.set_reg(0x30, 0x0008)
        self.set_reg(0x3A, 0x0202)
        self.set_reg(0x3B, 0x0202)
        self.set_reg(0x33, 0x0001)
        self.set_reg(0x2B, 0x0222)
        self.set_reg(0x2A, 0x2222)
        self.set_reg(0x25, 0x0000)
        self.set_reg(0x31, 0x0001) # clk_divide = /1, single channel interleaving ADC1..4

    def set_reg(self, reg, value):
        spi_write(1 + self.ch, [reg, (value >> 8) & 0xFF, (value & 0xFF)])

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


class ADCDMA:
    def __init__(self):
        bus.regs.adc0_dma_enable.write(0)

    def run(self, base, length):
        bus.regs.adc0_dma_base.write(base)
        bus.regs.adc0_dma_length.write(length)
        bus.regs.adc0_dma_enable.write(1)
        while not (bus.regs.adc0_dma_done.read() & 0x1):
            pass
        bus.regs.adc0_dma_enable.write(0)

adc_dma_length = 0x10000

print("Clock Init...")
clock = Clock()
clock.init()

print("OffsetDAC Init...")
offsetdac = OffsetDAC()
offsetdac.init()
offsetdac.set_ch(0, 0x2600)

print("ADC Init...")
adc0 = ADC(0)
adc0.reset()
#adc0.data_mode()
adc0.ramp()

print("Frontend Init...")
frontend = Frontend(adc0, None, offsetdac)
frontend.set_ch1_1v()

print("ADC Data Capture (to DRAM)...")
adc0_dma = ADCDMA()
adc0_dma.run(base=0x0000_0000, length=adc_dma_length)

print("ADC Data Retrieve (from DRAM)...")

adc_data = []
for i in range(adc_dma_length//4):
    word = bus.read(bus.mems.main_ram.base + 4*i)
    adc_data.append((word >> 0)  & 0xff)
    adc_data.append((word >> 8)  & 0xff)
    adc_data.append((word >> 16) & 0xff)
    adc_data.append((word >> 24) & 0xff)

print("Plot...")

plt.plot(adc_data)
plt.show()

bus.close()
