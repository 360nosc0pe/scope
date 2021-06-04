#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import time

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from migen.genlib.misc import WaitTimer

from litex.soc.interconnect.csr import *
from litex.soc.interconnect import stream

from peripherals.spi import *
from peripherals.down_sampling import DownSampling

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

ADC_CONTROL_FRAME_RST = (1 << 0)
ADC_CONTROL_DELAY_RST = (1 << 1)
ADC_CONTROL_DELAY_INC = (1 << 2)
ADC_CONTROL_STAT_RST  = (1 << 3)

ADC_RANGE_STAT_MIN    = (1 << 0)
ADC_RANGE_STAT_MAX    = (1 << 8)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# Layouts ------------------------------------------------------------------------------------------

hmcad1511_phy_layout = ["fclk_p", "fclk_n", "lclk_p", "lclk_n", "d_p", "d_n"]

# HAD1511 ------------------------------------------------------------------------------------------

class HAD1511(Module, AutoCSR):
    def __init__(self, pads, sys_clk_freq, clock_domain="sys"):
        # Parameters.
        nchannels = len(pads.d_p)
        for name in hmcad1511_phy_layout:
            assert hasattr(pads, name)

        # ADC stream.
        self.source = source = stream.Endpoint([("data", nchannels*8)])

        # Control/Status.
        self._control      = CSRStorage(fields=[
            CSRField("frame_rst", offset=0, size=1, pulse=True, description="Frame clock reset."),
            CSRField("delay_rst", offset=1, size=1, pulse=True, description="Sampling delay reset."),
            CSRField("delay_inc", offset=2, size=1, pulse=True, description="Sampling delay increment."),
            CSRField("stat_rst",  offset=3, size=1, pulse=True, description="Statistics reset.")
        ])
        self._status       = CSRStatus() # Unused (for now).
        self._downsampling = CSRStorage(32, description="ADC Downsampling ratio.")
        self._range        = CSRStatus(fields=[
            CSRField("min", size=8, offset=0, description="ADC Min value since last stat_rst."),
            CSRField("max", size=8, offset=8, description="ADC Max value since last stat_rst."),
        ])
        self._count        = CSRStatus(32, description="ADC samples count since last stat_rst.")

        # # #

        # Clocking.
        # ---------

        self.clock_domains.cd_adc       = ClockDomain() # ADC Bitclock.
        self.clock_domains.cd_adc_frame = ClockDomain() # ADC Frameclock (freq : ADC Bitclock/8).
        adc_clk = Signal()
        self.specials += Instance("IBUFDS",
            i_I  = pads.lclk_p,
            i_IB = pads.lclk_n,
            o_O  = adc_clk
        )
        self.specials += Instance("BUFIO",
            i_I = adc_clk,
            o_O = ClockSignal("adc")
        )
        self.specials += Instance("BUFR",
            p_BUFR_DIVIDE = "4",
            i_I = adc_clk,
            o_O = ClockSignal("adc_frame")
        )
        self.specials += AsyncResetSynchronizer(self.cd_adc_frame, self._control.fields.frame_rst)

        # LVDS Reception & Deserialization.
        # ---------------------------------

        bitslip = Signal()

        # Receive & Deserialize Frame clock to use it as a delimiter for the data.
        fclk_no_delay = Signal()
        fclk_delayed  = Signal()
        fclk          = Signal(8)
        self.specials += [
            Instance("IBUFDS",
                i_I  = pads.fclk_p,
                i_IB = pads.fclk_n,
                o_O  = fclk_no_delay
            ),
            Instance("IDELAYE2",
                p_DELAY_SRC             = "IDATAIN",
                p_SIGNAL_PATTERN        = "DATA",
                p_CINVCTRL_SEL          = "FALSE",
                p_HIGH_PERFORMANCE_MODE = "TRUE",
                p_REFCLK_FREQUENCY      = 200.0,
                p_PIPE_SEL              = "FALSE",
                p_IDELAY_TYPE           = "VARIABLE",
                p_IDELAY_VALUE          = 0,

                i_C        = ClockSignal("sys"),
                i_LD       = self._control.fields.delay_rst,
                i_CE       = self._control.fields.delay_inc,
                i_LDPIPEEN = 0,
                i_INC      = 1,

                i_IDATAIN  = fclk_no_delay,
                o_DATAOUT  = fclk_delayed
            ),
            Instance("ISERDESE2",
                p_DATA_WIDTH     = 8,
                p_DATA_RATE      = "DDR",
                p_SERDES_MODE    = "MASTER",
                p_INTERFACE_TYPE = "NETWORKING",
                p_NUM_CE         = 1,
                p_IOBDELAY       = "IFD",
                i_DDLY    = fclk_delayed,
                i_CE1     = 1,
                i_RST     =  ResetSignal("adc_frame"),
                i_CLK     =  ClockSignal("adc"),
                i_CLKB    = ~ClockSignal("adc"),
                i_CLKDIV  =  ClockSignal("adc_frame"),
                i_BITSLIP = bitslip,
                 **{f"o_Q{n+1}": fclk[8-1-n] for n in range(8)},
            )
        ]

        # Check Frame clock synchronization and increment bitslip every 1 ms when not synchronized.
        fclk_timer = WaitTimer(int(1e-3*sys_clk_freq))
        fclk_timer = ClockDomainsRenamer("adc_frame")(fclk_timer)
        self.submodules += fclk_timer
        self.sync.adc_frame += [
            bitslip.eq(0),
            fclk_timer.wait.eq(~fclk_timer.done),
            If(fclk_timer.done,
                If((fclk != 0xf) & (fclk != 0x33) & (fclk != 0x55),
                    bitslip.eq(1)
                )
            )
        ]

        # Receive & Deserialize Data.
        self.adc_source = adc_source = stream.Endpoint([("data", nchannels*8)])
        self.comb += adc_source.valid.eq(1)
        for i in range(nchannels):
            d_no_delay = Signal()
            d_delayed  = Signal()
            d          = Signal(8)
            self.specials += [
                Instance("IBUFDS",
                    i_I  = pads.d_p[i],
                    i_IB = pads.d_n[i],
                    o_O  = d_no_delay
                ),
                Instance("IDELAYE2",
                    p_DELAY_SRC             = "IDATAIN",
                    p_SIGNAL_PATTERN        = "DATA",
                    p_CINVCTRL_SEL          = "FALSE",
                    p_HIGH_PERFORMANCE_MODE = "TRUE",
                    p_REFCLK_FREQUENCY      = 200.0,
                    p_PIPE_SEL              = "FALSE",
                    p_IDELAY_TYPE           = "VARIABLE",
                    p_IDELAY_VALUE          = 0,

                    i_C        = ClockSignal("sys"),
                    i_LD       = self._control.fields.delay_rst,
                    i_CE       = self._control.fields.delay_inc,
                    i_LDPIPEEN = 0,
                    i_INC      = 1,

                    i_IDATAIN  = d_no_delay,
                    o_DATAOUT  = d_delayed
                ),
                Instance("ISERDESE2",
                    p_DATA_WIDTH     = 8,
                    p_DATA_RATE      = "DDR",
                    p_SERDES_MODE    = "MASTER",
                    p_INTERFACE_TYPE = "NETWORKING",
                    p_NUM_CE         = 1,
                    p_IOBDELAY       = "IFD",
                    i_DDLY    = d_delayed,
                    i_CE1     = 1,
                    i_RST     =  ResetSignal("adc_frame"),
                    i_CLK     =  ClockSignal("adc"),
                    i_CLKB    = ~ClockSignal("adc"),
                    i_CLKDIV  =  ClockSignal("adc_frame"),
                    i_BITSLIP = bitslip,
                     **{f"o_Q{n+1}": d[8-1-n] for n in range(8)},
                )
            ]
            self.comb += adc_source.data[8*i:8*(i+1)].eq(d)

        # Clock Domain Crossing.
        # ----------------------

        self.submodules.cdc = stream.ClockDomainCrossing(
            layout  = [("data", nchannels*8)],
            cd_from = "adc_frame",
            cd_to   = clock_domain
        )
        self.comb += self.adc_source.connect(self.cdc.sink)

        # DownSampling.
        # -------------

        self.submodules.downsampling = DownSampling(ratio=self._downsampling.storage)
        self.comb += self.cdc.source.connect(self.downsampling.sink)
        self.comb += self.downsampling.source.connect(source)
        self.comb += self.downsampling.source.ready.eq(1) # No backpressure allowed.

        # Statistics.
        # -----------

        # Min/Max Range.
        adc_min   = self._range.fields.min
        adc_max   = self._range.fields.max
        adc_value = source.data[:8]
        self.sync += [
            # On a valid cycle:
            If(source.valid,
                # Compute Min.
                If(adc_value >= adc_max,
                    adc_max.eq(adc_value)
                ),
                # Compute Max.
                If(adc_value <= adc_min,
                    adc_min.eq(adc_value)
                )
            ),
            # Clear Min/Max.
            If(self._control.fields.stat_rst,
                adc_min.eq(0xff),
                adc_max.eq(0x00)
            ),
        ]

        # Samples Count.
        adc_count = self._count.status
        self.sync += [
            # On a valid cycle:
            If(source.valid,
                If(adc_count != (2**32-nchannels),
                    adc_count.eq(adc_count + nchannels)
                )
            ),
            # Clear Count.
            If(self._control.fields.stat_rst,
                adc_count.eq(0),
            ),
        ]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

class HAD1511Driver:
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
