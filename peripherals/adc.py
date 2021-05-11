#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from migen.genlib.fifo import AsyncFIFOBuffered

from migen.genlib.cdc import MultiReg
from litex.soc.interconnect.csr import *


# ADC LVDS Receiver --------------------------------------------------------------------------------

class ADCLVDSReceiver(Module, AutoCSR):
    def __init__(self, pads, n):
        assert hasattr(pads, "d")
        assert hasattr(pads, "fclk")
        assert hasattr(pads, "lclk")

        self._status  = CSRStatus(32, reset=0xadc)
        self._control = CSRStorage(32)

        # # #

        # input delay control; doesn't seem required so not hooked up.

        self.rx_delay_rst = Signal()
        self.rx_delay_inc = Signal()

        self.bitslip_do = Signal()

        N_CHANNELS = len(pads.d) // 2

        self.d_preslip = Signal(N_CHANNELS * 8)
        self.d         = Signal(N_CHANNELS * 8)
        self.fclk      = Signal(8)
        self.d_clk     = Signal()
        self.d_rst     = Signal()
        self.d_valid   = Signal() # output
        self.d_last    = Signal()
        self.d_ready   = Signal() # input

        self.fclk_preslip = Signal(8)

        # rx clock:
        # pads.lclk_p/n -> IBUFDS  -> lclk_i

        lclk_i       = Signal()
        lclk_i_bufio = Signal()

        self.clock_domains.cd_lclkdiv = ClockDomain()

        self.specials += MultiReg(self._control.storage[0], self.cd_lclkdiv.rst, "lclkdiv")

        self.specials += [
            Instance("IBUFDS",
                i_I  = pads.lclk[0],
                i_IB = pads.lclk[1],
                o_O  = lclk_i
            ),
            Instance("BUFIO", i_I=lclk_i, o_O=lclk_i_bufio),
            Instance("BUFR",  i_I=lclk_i, o_O=self.cd_lclkdiv.clk, p_BUFR_DIVIDE="4"),
        ]

        # frame clock

        for i in range(N_CHANNELS + 1):

            if i == N_CHANNELS: # fclk
                d_p = pads.fclk[0]
                d_n = pads.fclk[1]
            else:
                d_p = pads.d[i * 2 + 0]
                d_n = pads.d[i * 2 + 1]

            # pad -> IBUFDS_DIFF_OUT
            serdes_i_nodelay = Signal()
            self.specials += [
                Instance("IBUFDS_DIFF_OUT",
                    i_I  = d_p,
                    i_IB = d_n,
                    o_O  = serdes_i_nodelay
                )
            ]

            serdes_i_delayed = Signal()
            serdes_q         = Signal(8)
            self.specials += [
                Instance("IDELAYE2",
                    p_DELAY_SRC             = "IDATAIN",
                    p_SIGNAL_PATTERN        = "DATA",
                    p_CINVCTRL_SEL          = "FALSE",
                    p_HIGH_PERFORMANCE_MODE = "TRUE",
                    p_REFCLK_FREQUENCY      = 200.0,
                    p_PIPE_SEL              = "FALSE",
                    p_IDELAY_TYPE           = "VARIABLE",
                    p_IDELAY_VALUE          = 0,

                    i_C        = self.cd_lclkdiv.clk,
                    i_LD       = self.rx_delay_rst,
                    i_CE       = self.rx_delay_inc,
                    i_LDPIPEEN = 0,
                    i_INC      = 1,

                    i_IDATAIN  = serdes_i_nodelay,
                    o_DATAOUT  = serdes_i_delayed
                ),
                Instance("ISERDESE2",
                    p_DATA_WIDTH     = 8,
                    p_DATA_RATE      = "DDR",
                    p_SERDES_MODE    = "MASTER",
                    p_INTERFACE_TYPE = "NETWORKING",
                    p_NUM_CE         = 1,
                    p_IOBDELAY       = "IFD",
                    i_DDLY    = serdes_i_delayed,
                    i_CE1     = 1,
                    i_RST     = self.cd_lclkdiv.rst,
                    i_CLK     = lclk_i_bufio,
                    i_CLKB    = ~lclk_i_bufio,
                    i_CLKDIV  = self.cd_lclkdiv.clk,
                    i_BITSLIP = self.bitslip_do,
                    o_Q8      = serdes_q[0],
                    o_Q7      = serdes_q[1],
                    o_Q6      = serdes_q[2],
                    o_Q5      = serdes_q[3],
                    o_Q4      = serdes_q[4],
                    o_Q3      = serdes_q[5],
                    o_Q2      = serdes_q[6],
                    o_Q1      = serdes_q[7]
                )
            ]

            if i == N_CHANNELS:
                self.comb += self.fclk_preslip.eq(serdes_q)
            else:
                self.comb += self.d_preslip[i*8:i*8+8].eq(serdes_q)


        # async fifo
        # fclk_preslip || d_preslip (in lclkdiv clock domain) -> data clock domain

        self.clock_domains.cd_data = ClockDomain()
        self.comb += self.cd_data.clk.eq(self.d_clk)
        self.comb += self.cd_data.rst.eq(self.d_rst)

        data_fifo = AsyncFIFOBuffered((N_CHANNELS + 1) * 8, 64)
        self.submodules.fifo = ClockDomainsRenamer({"write": "lclkdiv", "read": "data"})(data_fifo)

        # data -> FIFO

        bitslip_delay = Signal(16)

        for i in range(N_CHANNELS + 1):

            # FIFO data layout:
            # low 8*N_CHANNELS bits is data,
            # upper 8 bits is FCLK
            if i == N_CHANNELS:
                src = self.fclk_preslip
            else:
                src = self.d_preslip[i*8:i*8+8]

            self.sync.lclkdiv += data_fifo.din[i*8:i*8+8].eq(src)

            # bitslip handling:
            # every once in a while (64k ticks), if the FCLK pattern doesn't match, increment bitslip.
            # (why only ever 64k? just to make debugging easier. could be reduced or even removed.)
            if i == N_CHANNELS:
                self.sync.lclkdiv += [
                    bitslip_delay.eq(bitslip_delay + 1),
                    self.bitslip_do.eq(((src != 0x0F) & (src != 0x33) & (src != 0x55)) & (bitslip_delay == 0)),
                ]

        self.last_counter = Signal(max=(2**14 - 1))

        self.sync += [
            If(self.d_valid & self.d_ready,
                If(self.last_counter == (2**14 - 1),
                    self.last_counter.eq(0)
                ).Else(
                    self.last_counter.eq(self.last_counter + 1)
                )
            )
        ]

        self.comb += [
            data_fifo.we.eq(1),
            data_fifo.re.eq(self.d_ready),
            self.d.eq(data_fifo.dout[:N_CHANNELS*8]),
            self.fclk.eq(data_fifo.dout[N_CHANNELS*8:N_CHANNELS*8+8]),
            self.d_valid.eq(data_fifo.readable),
            self.d_last.eq(self.last_counter == (2**14 - 1))
        ]
