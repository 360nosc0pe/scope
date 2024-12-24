#!/usr/bin/env python3

#
# This file is part of LiteICLink.
#
# Copyright (c) 2017-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import sys
import argparse

from migen import *

import sqrl_acorn_platform as sqrl_acorn

from litex.build.generic_platform import *

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.code_8b10b import K

from liteiclink.serdes.gtp_7series import GTPQuadPLL, GTP

# IOs ----------------------------------------------------------------------------------------------

_transceiver_io = [
    # PCIe 0.
    ("pcie_tx", 0,
        Subsignal("p", Pins("D7")),
        Subsignal("n", Pins("C7"))
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins("D9")),
        Subsignal("n", Pins("C9"))
    ),
    # SFP 0.
    ("sfp0_tx", 0, # Inverted on Acorn and on Baseboard.
        Subsignal("p", Pins("D5")),
        Subsignal("n", Pins("C5"))
    ),
    ("sfp0_rx", 0, # Inverted on Acorn.
        Subsignal("p", Pins("D11")),
        Subsignal("n", Pins("C11"))
    ),
    # SFP 1.
    ("sfp1_tx", 0, # Inverted on Acorn and on Baseboard.
        Subsignal("p", Pins("B4")),
        Subsignal("n", Pins("A4"))
    ),
    ("sfp1_rx", 0, # Inverted on Acorn.
        Subsignal("p", Pins("B8")),
        Subsignal("n", Pins("C8"))
    ),
    # SATA.
    ("sata_tx", 0, # Inverted on Acorn.
        Subsignal("p", Pins("B6")),
        Subsignal("n", Pins("A5"))
    ),
    ("sata_rx", 0, # Inverted on Acorn.
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10"))
    ),
]

# CRG ----------------------------------------------------------------------------------------------

class CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.clock_domains.cd_sys       = ClockDomain()

        # Clk/Rst
        clk200 = platform.request("clk200")

        # PLL
        self.submodules.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)

# GTPTestSoC ---------------------------------------------------------------------------------------

class GTPTestSoC(SoCMini):
    def __init__(self, platform, connector="pcie", linerate=2.5e9):
        assert connector in ["pcie", "sfp0", "sfp1", "sata"]
        sys_clk_freq = int(100e6)

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq, ident="LiteSATA bench on Acorn CLE 215+")

        # UARTBone ---------------------------------------------------------------------------------
        self.add_uartbone()

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = CRG(platform, sys_clk_freq)

        # GTP RefClk -------------------------------------------------------------------------------
        refclk_freq = 125e6
        self.clock_domains.cd_refclk = ClockDomain()
        self.crg.pll.create_clkout(self.cd_refclk, refclk_freq, margin=0)
        platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")

        # GTP PLL ----------------------------------------------------------------------------------
        pll = GTPQuadPLL(self.cd_refclk.clk, refclk_freq, linerate)
        print(pll)
        self.submodules += pll

        # GTP --------------------------------------------------------------------------------------
        tx_pads = platform.request(connector + "_tx")
        rx_pads = platform.request(connector + "_rx")
        self.submodules.serdes0 = serdes0 = GTP(pll, tx_pads, rx_pads, sys_clk_freq,
            tx_buffer_enable = True,
            rx_buffer_enable = True,
            clock_aligner    = False,
            rx_polarity      = 0, # FIXME for SFPs / SATA.
            tx_polarity      = 0, # FIXME foe SFPs / SATA.
        )
        serdes0.add_stream_endpoints()
        serdes0.add_controls()
        serdes0.add_clock_cycles()

        platform.add_period_constraint(serdes0.cd_tx.clk, 1e9/serdes0.tx_clk_freq)
        platform.add_period_constraint(serdes0.cd_rx.clk, 1e9/serdes0.rx_clk_freq)
        self.platform.add_false_path_constraints(self.crg.cd_sys.clk, serdes0.cd_tx.clk, serdes0.cd_rx.clk)

        # Test -------------------------------------------------------------------------------------
        counter = Signal(32)
        self.sync.tx += counter.eq(counter + 1)

        ## K28.5 and slow counter --> TX
        #self.comb += [
        #    serdes0.sink.valid.eq(1),
        #    serdes0.sink.ctrl.eq(0b1),
        #    serdes0.sink.data[:8].eq(K(28, 5)),
        #    serdes0.sink.data[8:].eq(counter[26:]),
        #]

        # RX (slow counter) --> Leds
        self.comb += platform.request("user_led", 3).eq(serdes0.source.data[0])

        # Leds -------------------------------------------------------------------------------------
        sys_counter = Signal(32)
        self.sync.sys += sys_counter.eq(sys_counter + 1)
        self.comb += platform.request("user_led", 0).eq(sys_counter[26])

        tx_counter = Signal(32)
        self.sync.tx += tx_counter.eq(tx_counter + 1)
        self.comb += platform.request("user_led", 1).eq(tx_counter[26])

        rx_counter = Signal(32)
        self.sync.rx += rx_counter.eq(rx_counter + 1)
        self.comb += platform.request("user_led", 2).eq(rx_counter[26])

        # RX Analyzer ------------------------------------------------------------------------------
        from litescope import LiteScopeAnalyzer
        self.submodules.analyzer = LiteScopeAnalyzer([serdes0.source],
            depth        = 1024,
            clock_domain = "rx",
            samplerate   = sys_clk_freq,
            csr_csv      = "analyzer.csv"
        )

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteICLink transceiver example on Acorn CLE 215+.")
    parser.add_argument("--build",     action="store_true", help="Build bitstream.")
    parser.add_argument("--load",      action="store_true", help="Load bitstream (to SRAM).")
    parser.add_argument("--connector", default="sata",      help="Connector: pcie, sfp0, sfp1 or sata")
    parser.add_argument("--linerate",  default="1.25e9",    help="Linerate (default: 1.25e9).")
    args = parser.parse_args()

    platform = sqrl_acorn.Platform()
    platform.add_extension(_transceiver_io)
    soc = GTPTestSoC(platform,
        connector = args.connector,
        linerate  = float(args.linerate),
    )
    builder = Builder(soc, csr_csv="csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))

if __name__ == "__main__":
    main()
