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
