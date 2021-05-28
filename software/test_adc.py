#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# ADC test utility.

import time
import socket
import matplotlib.pyplot as plt

from litex import RemoteClient

# Constants ----------------------------------------------------------------------------------------

# SPI.

SPI_CONTROL_START  = (1 << 0)
SPI_CONTROL_LENGTH = (1 << 8)
SPI_STATUS_DONE    = (1 << 0)

SPI_CS_PLL      = 0
SPI_CS_ADC0     = 1
SPI_CS_ADC1     = 2
SPI_CS_FRONTEND = 3
SPI_CS_CH1_VGA  = 4
SPI_CS_CH2_VGA  = 5
SPI_CS_CH3_VGA  = 6
SPI_CS_CH4_VGA  = 7

# ADC.

ADC_CONTROL_FRAME_RST = (1 << 0)
ADC_CONTROL_DELAY_RST = (1 << 1)
ADC_CONTROL_DELAY_INC = (1 << 2)
ADC_CONTROL_STAT_RST  = (1 << 3)

ADC_RANGE_STAT_MIN    = (1 << 0)
ADC_RANGE_STAT_MAX    = (1 << 8)


# Peripherals --------------------------------------------------------------------------------------

# SPI.

class SPI:
    def __init__(self, bus):
        self.bus = bus

    def write(self, cs, data):
        assert len(data) <= 6
        # Convert data to bytes (if not already).
        data = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        # Set Chip Select.
        bus.regs.spi_cs.write((1 << cs))
        # Prepare MOSI data.
        mosi_bits = len(data)*8
        mosi_data = int.from_bytes(data, byteorder="big")
        mosi_data <<= (48 - mosi_bits)
        bus.regs.spi_mosi.write(mosi_data)
        # Start SPI Xfer.
        bus.regs.spi_control.write(mosi_bits*SPI_CONTROL_LENGTH | SPI_CONTROL_START)
        # Wait SPI Xfer to be done.
        while not (bus.regs.spi_status.read() & SPI_STATUS_DONE):
            pass

# PLL.

class PLL:
    def __init__(self, bus, spi):
        self.bus = bus
        self.spi = spi

    def init(self):
        self.set_reg(0x40, 0x3120) # Control
        self.set_reg(0x04, 0xe143) # N-Counter
        self.set_reg(0x00, 0x0700) # R-Counter.

    def set_reg(self, reg, value):
        self.spi.write(SPI_CS_PLL, [reg, (value >> 8) & 0xff, value & 0xff])

# Offset DAC.

class OffsetDAC:
    def __init__(self, bus, spi):
        self.bus = bus
        self.spi = spi

    def init(self):
        bus.regs.offset_dac_control.write(1)

    def set_ch(self, n, value):
        getattr(bus.regs, f"offset_dac_ch{n+1}").write(value)

# Frontend.

class Frontend:
    def __init__(self, bus, spi, adcs):
        self.bus  = bus
        self.spi  = spi
        self.adcs = adcs

    def set_frontend(self, data):
        self.spi.write(SPI_CS_FRONTEND, data)

    def set_vga(self, n, gain):
        assert 0 <= gain <= 255
        self.spi.write(SPI_CS_CH1_VGA + n, [gain])

    def set_ch1_1v(self):
        self.set_frontend([0, 0x7a, 0x7a, 0x7a, 0x7e])
        self.set_vga(0, 0x1f)
        self.adcs[0].set_reg(0x2b, 00)

    def set_ch1_100mv(self):
        self.set_frontend([0, 0x7a, 0x7a, 0x7a, 0x78])
        self.set_vga(0, 0xad)
        self.adcs[0].set_reg(0x2b, 00)

# ADC.

class ADC:
    def __init__(self, bus, spi, n):
        self.bus     = bus
        self.spi     = spi
        self.n       = n
        self.control = getattr(bus.regs, f"adc{n}_control")
        self.range   = getattr(bus.regs, f"adc{n}_range")
        self.count   = getattr(bus.regs, f"adc{n}_count")

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
        self.set_reg(0x2B, 0x0222)
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
        self.bus.regs.adc0_dma_length.write(length)
        self.bus.regs.adc0_dma_enable.write(1)
        while not (self.bus.regs.adc0_dma_done.read() & 0x1):
            pass

# Test ---------------------------------------------------------------------------------------------

adc_dma_length = 0x1000

bus = RemoteClient()
bus.open()

spi = SPI(bus)

print("PLL Init...")
pll = PLL(bus, spi)
pll.init()

print("OffsetDAC Init...")
offsetdac = OffsetDAC(bus, spi)
offsetdac.init()
offsetdac.set_ch(0, 0x2600)

print("ADC Init...")
adc0 = ADC(bus, spi, n=0)
adc0.reset()
adc0.data_mode()
#adc0.ramp()

print("Frontend Init...")
frontend = Frontend(bus, spi, [adc0, None])
frontend.set_ch1_100mv()

print("ADC Statistics...")
adc0_min, adc0_max = adc0.get_range()
adc0_samplerate    = adc0.get_samplerate()
print(f"- Min: {adc0_min}")
print(f"- Max: {adc0_max}")
print(f"- Samplerate: ~{adc0_samplerate/1e6}MSa/s ({adc0_samplerate*8/1e9}Gb/s)")

print("ADC Data Capture (to DRAM)...")
adc0.capture(base=0x0000_0000, length=adc_dma_length)

print("ADC Data Retrieve (from DRAM)...")
adc_data = []

def udp_data_retrieve():
    length   = adc_dma_length
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

def etherbone_data_retrieve():
    for i in range(adc_dma_length//4):
        word = bus.read(bus.mems.main_ram.base + 4*i)
        adc_data.append((word >> 0)  & 0xff)
        adc_data.append((word >> 8)  & 0xff)
        adc_data.append((word >> 16) & 0xff)
        adc_data.append((word >> 24) & 0xff)

udp_data_retrieve()
#etherbone_data_retrieve()

print("Plot...")
plt.plot(adc_data)
plt.show()

bus.close()
