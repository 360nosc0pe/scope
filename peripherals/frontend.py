#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

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

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

class FrontendDriver:
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
