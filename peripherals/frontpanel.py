#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from enum import IntEnum

from migen import *

from litex.soc.interconnect.csr import *
from litex.soc.cores.spi import SPIMaster

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

class FP_LEDS(IntEnum):
    INTENSITY_ADJUST = (1 <<  0)
    CHANNEL_1        = (1 <<  1)
    CHANNEL_2        = (1 <<  2)
    CHANNEL_3        = (1 <<  3)
    CHANNEL_4        = (1 <<  4)
    DIGITAL          = (1 <<  5)
    CURSORS          = (1 <<  6)
    MEASURE          = (1 <<  7)
    MATH             = (1 <<  8)
    REF              = (1 <<  9)
    ROLL             = (1 << 10)
    SEARCH           = (1 << 11)
    DECODE           = (1 << 12)
    HISTORY          = (1 << 13)
    TRIGGER_AUTO     = (1 << 14)
    TRIGGER_NORMAL   = (1 << 15)
    TRIGGER_SINGLE   = (1 << 16)
    RUN_STOP_GREEN   = (1 << 17)
    RUN_STOP_RED     = (1 << 18)

class FP_BTNS(IntEnum):
    MENU_ON_OFF      = (1 << 56)
    MENU_1           = (1 << 48)
    MENU_2           = (1 << 40)
    MENU_3           = (1 << 32)
    MENU_4           = (1 << 24)
    MENU_5           = (1 << 16)
    MENU_6           = (1 <<  8)
    PRINT            = (1 <<  0)
    CHANNEL_1        = (1 << 60)
    CHANNEL_2        = (1 << 59)
    CHANNEL_3        = (1 << 58)
    CHANNEL_4        = (1 << 57)
    DIGITAL          = (1 << 52)
    CURSORS          = (1 << 51)
    ACQUIRE          = (1 << 35)
    SAVE_RECALL      = (1 << 33)
    MEASURE          = (1 << 50)
    DISPLAY_PERSIST  = (1 << 34)
    UTILITY          = (1 << 28)
    NAVIGATE         = (1 << 49)
    PREVIOUS         = (1 << 44)
    STOP             = (1 << 43)
    NEXT             = (1 << 42)
    MATH             = (1 << 41)
    REF              = (1 << 36)
    ROLL             = (1 << 27)
    SEARCH           = (1 << 19)
    TRIGGER_SETUP    = (1 << 11)
    TRIGGER_AUTO     = (1 << 10)
    TRIGGER_NORMAL   = (1 <<  9)
    TRIGGER_SINGLE   = (1 <<  4)
    CLEAR_SWEEPS     = (1 << 26)
    DECODE           = (1 << 25)
    HISTORY          = (1 << 20)
    RUN_STOP         = (1 << 18)
    AUTOSETUP        = (1 << 17)
    DEFAULT          = (1 << 12)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# Frontpanel Leds ----------------------------------------------------------------------------------

class FrontpanelLeds(Module, AutoCSR):
    def __init__(self, pads, sys_clk_freq):
        self.value = CSRStorage(19)

        # # #

        # SPI Master.
        pads.miso = Signal() # Add fake MISO pad.
        self.submodules.spi = spi = SPIMaster(pads,
            data_width   = 19,
            sys_clk_freq = sys_clk_freq,
            spi_clk_freq = 100e3,
            with_csr     = False
        )

        # Enable shift register to drive LEDs (otherwise they are all-on).
        self.comb += pads.oe.eq(0)

        # SPI Control.
        self.sync += If(spi.done, spi.mosi.eq(self.value.storage)) # Update SPI MOSI when Xfer done.
        self.comb += spi.length.eq(19)
        self.sync += spi.start.eq(spi.done) # Continous SPI Xfers.

# Frontpanel Buttons -------------------------------------------------------------------------------

class FrontpanelButtons(Module, AutoCSR):
    def __init__(self, pads, sys_clk_freq):
        self.value = CSRStatus(64)

        # # #

        # SPI Master.
        pads.mosi = Signal() # Add fake MOSI pad.
        self.submodules.spi = spi = SPIMaster(pads,
            data_width   = 64,
            sys_clk_freq = sys_clk_freq,
            spi_clk_freq = 100e3,
            with_csr     = False
        )

        # SPI Control.
        self.sync += If(spi.done, self.value.status.eq(spi.miso)) # Update Value when SPI Xfer done.
        self.comb += spi.length.eq(64)
        self.sync += spi.start.eq(spi.done) # Continous SPI Xfers.


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.
