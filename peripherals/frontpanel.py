#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.soc.interconnect.csr import *
from litex.soc.cores.spi import SPIMaster

# Frontpanel Leds ----------------------------------------------------------------------------------

FP_LED_INTENSITY_ADJUST = (1 <<  0)
FP_LED_CHANNEL_1        = (1 <<  1)
FP_LED_CHANNEL_2        = (1 <<  2)
FP_LED_CHANNEL_3        = (1 <<  3)
FP_LED_CHANNEL_4        = (1 <<  4)
FP_LED_DIGITAL          = (1 <<  5)
FP_LED_CURSORS          = (1 <<  6)
FP_LED_MEASURE          = (1 <<  7)
FP_LED_MATH             = (1 <<  8)
FP_LED_REF              = (1 <<  9)
FP_LED_ROLL             = (1 << 10)
FP_LED_SEARCH           = (1 << 11)
FP_LED_DECODE           = (1 << 12)
FP_LED_HISTORY          = (1 << 13)
FP_LED_AUTO             = (1 << 14)
FP_LED_NORMAL           = (1 << 15)
FP_LED_SINGLE           = (1 << 16)
FP_LED_RUN_STOP_GREEN   = (1 << 17)
FP_LED_RUN_STOP_RED     = (1 << 18)

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
