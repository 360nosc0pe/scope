#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from peripherals.spi import *
from peripherals.had1511_adc import *

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# Frontend.

FRONTEND_DEFAULT             = 0x40     # FIXME: Understand bit-6.
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

# Configs.

mV = 1e-3
V  = 1

class AFEConfig:
    def __init__(self, adc, frontend, vga):
        self.adc      = adc
        self.frontend = frontend
        self.vga      = vga

AFEScreenDivs     = 8
AFEVPerDivConfigs = {
      5*mV: AFEConfig(adc=HAD1511_ADC_GAIN_9DB, frontend=FRONTEND_VGA_ENABLE, vga=0xb9),
     10*mV: AFEConfig(adc=HAD1511_ADC_GAIN_6DB, frontend=FRONTEND_VGA_ENABLE, vga=0xb9),
     20*mV: AFEConfig(adc=HAD1511_ADC_GAIN_4DB, frontend=FRONTEND_VGA_ENABLE, vga=0xb9),
     50*mV: AFEConfig(adc=HAD1511_ADC_GAIN_2DB, frontend=FRONTEND_VGA_ENABLE, vga=0xad),
    100*mV: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE, vga=0xad),
    200*mV: AFEConfig(adc=HAD1511_ADC_GAIN_4DB, frontend=FRONTEND_VGA_ENABLE, vga=0x27),
    500*mV: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE, vga=0x3f),
       1*V: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE, vga=0x1f),
       2*V: AFEConfig(adc=HAD1511_ADC_GAIN_4DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER, vga=0x29),
       5*V: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER, vga=0x41),
      10*V: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER, vga=0x21),
      20*V: AFEConfig(adc=HAD1511_ADC_GAIN_4DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER | FRONTEND_10_1_SECOND_DIVIDER, vga=0x28),
      50*V: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER | FRONTEND_10_1_SECOND_DIVIDER, vga=0x41),
     100*V: AFEConfig(adc=HAD1511_ADC_GAIN_0DB, frontend=FRONTEND_VGA_ENABLE | FRONTEND_10_1_FIRST_DIVIDER | FRONTEND_10_1_SECOND_DIVIDER, vga=0x20),
}

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

class FrontendDriver:
    def __init__(self, bus, spi, adc):
        self.bus  = bus
        self.spi  = spi
        self.adc  = adc
        self.frontend_values = [FRONTEND_DEFAULT for i in range(4)]

    def set_frontend(self, n, data):
        self.frontend_values[4-1-n] |= data # /!\ FIXME!
        self.spi.write(SPI_CS_FRONTEND, [0x00] + self.frontend_values)

    def set_vga(self, n, gain):
        assert 0 <= gain <= 255
        self.spi.write(SPI_CS_CH1_VGA + n, [gain])

    def set_coupling(self, coupling):
        assert coupling in ["dc", "ac"]
        frontend_value = self.frontend_values[4-1-self.adc.n] & (~FRONTEND_DC_COUPLING)
        if coupling == "dc":
            frontend_value |= FRONTEND_DC_COUPLING
        self.set_frontend(self.adc.n, frontend_value)

    def set_bwl(self, bwl):
        assert bwl in ["full", "20mhz"]
        frontend_value = self.frontend_values[4-1-self.adc.n] & (~FRONTEND_FULL_BANDWIDTH)
        if bwl == "full":
            frontend_value |= FRONTEND_FULL_BANDWIDTH
        self.set_frontend(self.adc.n, frontend_value)

    def set_range(self, req_range):
        print(f"Requesting Range to {req_range:f}V...")
        req_range_div = req_range/AFEScreenDivs
        sel_range_div = 0
        afe_config    = AFEVPerDivConfigs[100*V]
        for r, c in AFEVPerDivConfigs.items():
            if r > req_range_div:
                sel_range_div = r
                afe_config    = c
                break
        print(f"Selecting {sel_range_div:f}V/Div AFE Config...")
        afe_resolution = (sel_range_div*AFEScreenDivs)/256

        self.set_frontend(self.adc.n, afe_config.frontend)
        self.adc.set_gain(afe_config.adc)
        self.set_vga(self.adc.n, afe_config.vga)

        return afe_resolution

    def center(self, offsetdac, debug=True):
        print(f"Centering ADC Data through OffsetDAC...")
        best_offset = 0
        best_error  = 0xff
        for offset in range(0x2500, 0x2700, 8):
            offsetdac.set_ch(self.adc.n, offset)
            _min, _max = self.adc.get_range(duration=0.001)
            _mean = _min + (_max - _min)/2
            error = abs(_mean - 0xff/2)
            if error < best_error:
                best_error  = error
                best_offset = offset
                if debug:
                    print(f"OffsetDAC Best: 0x{offset:x} (ADC Min:{_min} Max: {_max} Mean: {_mean})")
        print(f"Best OffsetDAC 0x{best_offset:x}")
        offsetdac.set_ch(self.adc.n, best_offset)
