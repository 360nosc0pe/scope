#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# SPI Constants ------------------------------------------------------------------------------------

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


# SPI ----------------------------------------------------------------------------------------------

class SPI:
    def __init__(self, bus):
        self.bus = bus

    def write(self, cs, data):
        assert len(data) <= 6
        # Convert data to bytes (if not already).
        data = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        # Set Chip Select.
        self.bus.regs.spi_cs.write((1 << cs))
        # Prepare MOSI data.
        mosi_bits = len(data)*8
        mosi_data = int.from_bytes(data, byteorder="big")
        mosi_data <<= (48 - mosi_bits)
        self.bus.regs.spi_mosi.write(mosi_data)
        # Start SPI Xfer.
        self.bus.regs.spi_control.write(mosi_bits*SPI_CONTROL_LENGTH | SPI_CONTROL_START)
        # Wait SPI Xfer to be done.
        while not (self.bus.regs.spi_status.read() & SPI_STATUS_DONE):
            pass
