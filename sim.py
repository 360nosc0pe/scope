#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import argparse

from migen import *

from litex.build.generic_platform import *
from litex.build.sim import SimPlatform
from litex.build.sim.config import SimConfig

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.interconnect import stream

from litedram.common import PhySettings
from litedram.modules import MT41K64M16
from litedram.phy.model import SDRAMPHYModel
from litedram.frontend.dma import LiteDRAMDMAWriter, LiteDRAMDMAReader

from liteeth.common import convert_ip
from liteeth.phy.model import LiteEthPHYModel
from liteeth.frontend.stream import LiteEthStream2UDPTX

# IOs ----------------------------------------------------------------------------------------------

_io = [
    # Clk / Rst.
    ("sys_clk", 0, Pins(1)),
    ("sys_rst", 0, Pins(1)),

    # Ethernet.
    ("eth_clocks", 0,
        Subsignal("tx", Pins(1)),
        Subsignal("rx", Pins(1)),
    ),
    ("eth", 0,
        Subsignal("source_valid", Pins(1)),
        Subsignal("source_ready", Pins(1)),
        Subsignal("source_data",  Pins(8)),

        Subsignal("sink_valid",   Pins(1)),
        Subsignal("sink_ready",   Pins(1)),
        Subsignal("sink_data",    Pins(8)),
    ),
]

# Platform -----------------------------------------------------------------------------------------

class Platform(SimPlatform):
    def __init__(self):
        SimPlatform.__init__(self, "SIM", _io)

# ScopeSoC -----------------------------------------------------------------------------------------

class ScopeSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(100e6), scope_ip="192.168.1.50", host_ip="192.168.1.100", host_udp_port=2000, with_analyzer=False):
        # Platform ---------------------------------------------------------------------------------
        platform = Platform()

        # SoCore ---------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident               = "ScopeSoC on Siglent SDS1104X-E",
            ident_version       = True,
            uart_name           = "crossover",
            cpu_type            = "vexriscv",
            cpu_variant         = "lite", # CPU only used to initialize DDR3 for now, Lite is enough.
            integrated_rom_size = 0x10000,
        )
        self.add_constant("CONFIG_DISABLE_DELAYS")

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = CRG(platform.request("sys_clk"))

        # DDR3 SDRAM --------------------------------------------------------------------------------
        from litex.tools.litex_sim import get_sdram_phy_settings
        dram_module  = MT41K64M16(sys_clk_freq, "1:4")
        phy_settings = get_sdram_phy_settings(
            memtype    = "DDR3",
            data_width = 32,
            clk_freq   = int(100e6) # Use 100MHz timings.
        )
        self.submodules.ddrphy = SDRAMPHYModel(
            module    = dram_module,
            settings  = phy_settings,
            clk_freq  = int(100e6) # Use 100MHz timings.
        )
        self.add_sdram("sdram",
            phy              = self.ddrphy,
            module           = dram_module,
            l2_cache_size    = 1024,
            l2_cache_reverse = False,
        )
        self.add_constant("SDRAM_TEST_DISABLE") # Disable SDRAM test for simulation speedup.

        # Etherbone --------------------------------------------------------------------------------
        self.submodules.ethphy = LiteEthPHYModel(self.platform.request("eth"))
        self.add_etherbone(phy=self.ethphy, ip_address=scope_ip)

        # Upload -----------------------------------------------------------------------------------
        # DMA Reader
        # ----------
        dram_port = self.sdram.crossbar.get_port()
        self.submodules.dma_reader      = LiteDRAMDMAReader(dram_port, fifo_depth=128, with_csr=True)
        self.submodules.dma_reader_conv = stream.Converter(dram_port.data_width, 8)

        # UDP Streamer
        # ------------
        udp_port       = self.ethcore.udp.crossbar.get_port(host_udp_port, dw=8)
        udp_streamer   = LiteEthStream2UDPTX(
            ip_address = convert_ip(host_ip),
            udp_port   = host_udp_port,
            fifo_depth = 1024
        )
        self.submodules.udp_cdc      = stream.ClockDomainCrossing([("data", 8)], "sys", "eth_tx")
        self.submodules.udp_streamer = ClockDomainsRenamer("eth_tx")(udp_streamer)

        # DMA -> UDP Pipeline
        # -------------------
        self.submodules += stream.Pipeline(
            self.dma_reader,
            self.dma_reader_conv,
            self.udp_cdc,
            self.udp_streamer,
            udp_port
        )

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SDS1104X-E Scope Simulation.")
    parser.add_argument("--scope-ip",      default="192.168.1.50",  type=str, help="Scope IP address.")
    parser.add_argument("--host-ip",       default="192.168.1.100", type=str, help="Host  IP address.")
    parser.add_argument("--host-udp-port", default=2000,            type=int, help="Host UDP port.")
    parser.add_argument("--with-analyzer", action="store_true",               help="Enable Logic Analyzer.")
    parser.add_argument("--trace",         action="store_true",               help="Enable VCD tracing.")
    parser.add_argument("--trace-start",   default=0,                         help="Cycle to start VCD tracing.")
    parser.add_argument("--trace-end",     default=-1,                        help="Cycle to end VCD tracing.")
    args = parser.parse_args()

    # Sim Configuration
    # -----------------
    sim_config = SimConfig(default_clk="sys_clk")
    sim_config.add_module("ethernet", "eth", args={"interface": "tap0", "ip": "192.168.1.100"})

    # Build
    # -----
    soc = ScopeSoC(
        scope_ip      = args.scope_ip,
        host_ip       = args.host_ip,
        host_udp_port = args.host_udp_port,
        with_analyzer = args.with_analyzer
    )
    builder = Builder(soc, csr_csv="software/csr.csv")
    vns = builder.build(
        sim_config  = sim_config,
        trace       = args.trace,
        trace_start = int(args.trace_start),
        trace_end   = int(args.trace_end)
    )

if __name__ == "__main__":
    main()
