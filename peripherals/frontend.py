#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from peripherals.spi import *

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

    def auto_setup(self, offsetdac, div, debug=True): # FIXME: Very dumb Auto-Setup test, mostly to verify Frontend/Gains are behaving correctly, improve.
        print("Setting Frontend/Gain to default values...")
        frontend_value = FRONTEND_FULL_BANDWIDTH | FRONTEND_VGA_ENABLE | FRONTEND_DC_COUPLING
        assert div in ["100", "10", "1"]
        if div == "100":
            frontend_value |= FRONTEND_10_1_FIRST_DIVIDER | FRONTEND_10_1_SECOND_DIVIDER
        if div == "10":
            frontend_value |= FRONTEND_10_1_FIRST_DIVIDER
        self.set_frontend(0, frontend_value)
        self.adcs[0].set_reg(0x2b, 0x00)                  # 1X ADC Gain.
        self.set_vga(0, VGA_LOW_RANGE | 0x40) # Low VGA Gain to see Data but avoid saturation.

        # Do 2 OffsetDAC/VGA calibration loops:
        # - A First loop to find the rough OffsetDAC/Gain values.
        # - A Second loop to refine them.
        for loop in range(2):
            print(f"Centering ADC Data through OffsetDAC (loop {loop})...")
            best_offset = 0
            best_error  = 0xff
            for offset in range(0x2400, 0x2800, 1):
                offsetdac.set_ch(0, offset)
                _min, _max = self.adcs[0].get_range(duration=0.001)
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
                self.set_vga(0, VGA_HIGH_RANGE | gain)
                _min, _max = self.adcs[0].get_range(duration=0.001)
                _dynamic = (_max - _min)
                if (_min > sat_margin) and (_max < (0xff - sat_margin)):
                    if (_dynamic > best_dynamic):
                        best_gain    = gain
                        best_dynamic = _dynamic
                        if debug:
                            print(f"VGA Best: 0x{best_gain:x} (ADC Min:{_min} Max: {_max} Diff: {_dynamic})")
            print(f"Best VGA Gain: 0x{best_gain:x}")
            self.set_vga(0, VGA_HIGH_RANGE | best_gain)
