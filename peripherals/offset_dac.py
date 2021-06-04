#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.misc import WaitTimer

from litex.soc.interconnect.csr import *

from litex.soc.cores.spi import SPIMaster

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#
#                                       74HC4051
#                                       ┌───────┐
#            ┌─────────┐   ┌────────┐   │       ├──► Y0  (Unused)
#            │         │   │        │   │       ├──► Y1  (Unused)
#            │  FPGA   ├──►│  DAC   ├──►│Z      │
#            │         │SPI│        │ V │       ├──► Y2  (Unused)
#            └──┬─────┬┘   └────────┘   │   M   ├──► Y3  (Unused)
#               │     │                 │   U   │
#               │     └────────────────►│S  X   ├──► Y4  Reference offset for CH1's VGA.
#               │                       │       ├──► Y5  Reference offset for CH2's VGA.
#               └──────────────────────►│/E     │
#                                       │       ├──► Y6  Reference offset for CH3's VGA.
#                                       │       ├──► Y7  Reference offset for CH4's VGA.
#                                       └───────┘
#
# Global
# ------
#   To generate the reference offsets for the 4 channels, a single DAC is used and connected to a
#   74HC4051 (8-channel analog multiplexer/demultiplexer).
#
#   The DAC output is connected to the Z pin of the 74HC4051, is connnected to the output selected
#   by S if /E is low, otherwise the output holds the previous connected value.
#
# DAC
# ---
#   The data is transferred (MSB-first) on falling edge of SCLK while nSYNC is low and the data is
#   updated on the 24th bit with the following protocol:
#     | 6 bits | 2 bits  | 16 bits |
#     | XXXXXX | PD1,PD0 |  data   |
#   Where PD bits define DAC mode:
#       0 - normal
#       1 - 1k to GND
#       2 - 100k to GND
#       3 - Hi-Z
#
# Original behaviour:
# -------------------
#   DAC SCLK is constantly running, /E is deactivated during the DAC transition for 2 cycles and
#   selected channel is also updated during this transition.
#
# Original timings:
# -----------------
# SCLK freq:       250KHz.
# /E high pulse:   ~8.1us.
# Repetition rate: 9.8kHz => 1/25.5 of SPI SCLK freq.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# Layouts ------------------------------------------------------------------------------------------

offset_dac_layout = [
    # DAC.
    ("sclk",   1),
    ("din",    1),
    ("sync_n", 1),
    # Mux.
    ("s",   3),
    ("e_n", 1),
]

# Offset DAC ---------------------------------------------------------------------------------------

class OffsetDAC(Module, AutoCSR):
    def __init__(self, pads=None, sys_clk_freq=int(100e6), spi_clk_freq=int(250e3), default_enable=0):
        pads = pads if pads is not None else Record(offset_dac_layout)
        pads.e_n.reset = 1 # Disable Mux update by default.
        # Control/Status.
        self._control = CSRStorage(fields=[
            CSRField("enable", offset=0, size=1, reset=default_enable, description="Enable OffsetDAC operation."),
            CSRField("mode",   offset=4, size=2, description="DAC mode", values=[
                ("``0b00``", "Normal operation."),
                ("``0b01``", "1k to GND."),
                ("``0b10``", "100k to GND."),
                ("``0b11``", "Hi-Z."),
            ]),
        ])
        self._status  = CSRStatus() # Unused

        # Channel Offsets.
        self._ch1 = CSRStorage(16, reset=0x8000)
        self._ch2 = CSRStorage(16, reset=0x8000)
        self._ch3 = CSRStorage(16, reset=0x8000)
        self._ch4 = CSRStorage(16, reset=0x8000)

        # # #

        # SPI Master -------------------------------------------------------------------------------
        spi = SPIMaster(
            pads         = None,
            data_width   = 24,
            sys_clk_freq = sys_clk_freq,
            spi_clk_freq = spi_clk_freq,
            with_csr     = False
        )
        self.submodules += spi
        self.comb += [
            pads.sclk.eq(~spi.pads.clk),
            pads.sync_n.eq(spi.pads.cs_n),
            pads.din.eq(spi.pads.mosi),
        ]

        # Control FSM ------------------------------------------------------------------------------
        run     = Signal()
        channel = Signal(2)
        offset  = Signal(16)
        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            NextValue(run, 0),
            If(self._control.fields.enable,
                NextValue(channel, 0),
                NextState("DAC-UPDATE")
            )
        )
        self.comb += Case(channel, {
            0 : offset.eq(self._ch1.storage),
            1 : offset.eq(self._ch2.storage),
            2 : offset.eq(self._ch3.storage),
            3 : offset.eq(self._ch4.storage),
        })
        fsm.act("DAC-UPDATE",
            NextValue(run, 1),
            spi.start.eq(~run),
            spi.length.eq(24),
            spi.mosi[18:24].eq(0b000000),                  # Unused.
            spi.mosi[16:18].eq(self._control.fields.mode), # Operating mode.
            spi.mosi[:16].eq(offset),                      # Data.
            If(run & spi.done,
                NextValue(run, 0),
                NextState("MUX-UPDATE")
            )
        )
        mux_timer = WaitTimer(int(sys_clk_freq*8e-6))
        self.submodules += mux_timer
        fsm.act("MUX-UPDATE",
            mux_timer.wait.eq(1),
            pads.s.eq(channel + 4), # +4 : See mapping in description.
            pads.e_n.eq(0),
            If(mux_timer.done,
                NextState("CHANNEL-INCR")
            )
        )
        fsm.act("CHANNEL-INCR",
            NextValue(channel, channel + 1),
            NextState("DAC-UPDATE"),
            If(channel == (4-1),
                NextState("IDLE")
            )
        )

# Simulation ---------------------------------------------------------------------------------------

from litex.gen.sim import run_simulation

if __name__ == '__main__':
    def testbench_offsetdac(dut):
        for _ in range(25 * 8 * 1000):
            yield

    print("Running OffsetDAC simulation...")
    t = OffsetDAC(default_enable=1)
    run_simulation(t, testbench_offsetdac(t), vcd_name="offset_dac.vcd")

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.
