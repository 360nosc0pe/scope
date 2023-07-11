#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2020-2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import os
import argparse

from migen import *

from litex.gen import *

from litex.build.generic_platform import *
from litex.build.sim import SimPlatform
from litex.build.sim.config import SimConfig

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.spi import SPIMaster
from litex.soc.interconnect import stream

from litedram.common import PhySettings
from litedram.modules import MT41K64M16
from litedram.phy.model import SDRAMPHYModel
from litedram.frontend.dma import LiteDRAMDMAWriter

from liteeth.phy.model import LiteEthPHYModel

from peripherals.frontpanel import FrontpanelLeds, FrontpanelButtons, FP_BTNS
from peripherals.offset_dac import OffsetDAC
from peripherals.had1511_adc import HAD1511ADC
from peripherals.trigger import Trigger
from peripherals.dma_upload import DMAUpload

from litescope import LiteScopeAnalyzer

# Scope IOs ----------------------------------------------------------------------------------------

scope_ios = [
    # Clk / Rst.
    ("sys_clk",   0, Pins(1)),
    ("sys_rst",   0, Pins(1)),

    # Offset DAC
    ("offset_dac", 0,
        # DAC.
        Subsignal("sclk",   Pins(1)),
        Subsignal("din",    Pins(1)),
        Subsignal("sync_n", Pins(1)),
        # Mux.
        Subsignal("s",   Pins(3)),
        Subsignal("e_n", Pins(1)),
    ),

    # SPI
    ("spi", 0,
        Subsignal("clk",  Pins(1)),
        Subsignal("mosi", Pins(1)),
        Subsignal("cs_n", Pins(8)), # PLL, ADC0, ADC1, FE, VGA1, VGA2, VGA3, VGA4
    ),

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
        SimPlatform.__init__(self, "SIM", scope_ios)

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
        self.uart.add_auto_tx_flush(sys_clk_freq=int(1e6), timeout=1e-1, interval=2)
        self.add_constant("CONFIG_DISABLE_DELAYS")

        # CRG --------------------------------------------------------------------------------------
        self.crg = CRG(platform.request("sys_clk"))
        self.cd_adc_frame = ClockDomain()
        adc_frame_counter = Signal(16)
        self.sync += adc_frame_counter.eq(adc_frame_counter + 1)
        self.comb += self.cd_adc_frame.clk.eq(adc_frame_counter[1])

        # DDR3 SDRAM --------------------------------------------------------------------------------
        from litex.tools.litex_sim import get_sdram_phy_settings
        dram_module  = MT41K64M16(sys_clk_freq, "1:4")
        phy_settings = get_sdram_phy_settings(
            memtype    = "DDR3",
            data_width = 32,
            clk_freq   = sys_clk_freq,
        )
        self.ddrphy = SDRAMPHYModel(
            module    = dram_module,
            settings  = phy_settings,
            clk_freq  = sys_clk_freq,
        )
        self.add_sdram("sdram",
            phy              = self.ddrphy,
            module           = dram_module,
            l2_cache_size    = 1024,
            l2_cache_reverse = False,
        )
        self.add_constant("SDRAM_TEST_DISABLE") # Disable SDRAM test for simulation speedup.

        # Etherbone --------------------------------------------------------------------------------
        self.ethphy = LiteEthPHYModel(self.platform.request("eth"))
        self.add_etherbone(phy=self.ethphy, ip_address=scope_ip)
        # Frontpanel Leds --------------------------------------------------------------------------
        fpleds_pads = Record([("cs_n", 1), ("clk", 1), ("mosi", 1), ("oe", 1)])
        self.fpleds = FrontpanelLeds(fpleds_pads, sys_clk_freq)

        # Frontpanel Buttons -----------------------------------------------------------------------
        fpbtns_pads = Record([("cs_n", 1), ("clk", 1), ("miso", 1)])
        self.fpbtns = FrontpanelButtons(fpbtns_pads, sys_clk_freq)

        # Scope ------------------------------------------------------------------------------------
        #
        # Description
        # -----------
        # The SDS1104X-E is equipped with 2 x 1GSa/s HMCAD1511 8-bit ADDs and has 4 independent
        # frontends for each channel:
        #                                          SPI
        #                                (PLL/ADC/Frontends config)
        #                                           ▲
        #                                           │
        #                                       ┌───┴───┐
        #                           LVDS(8-bit) │       │ LVDS (8-bit)
        #                             ┌────────►│ FPGA  │◄────────┐
        #                             │         │       │         │
        #                             │         └───────┘         │
        #                             │                           │
        #                          ┌──┴───┐      ┌─────┐      ┌───┴──┐
        #                          │ ADC0 │◄─────┤ PLL ├─────►│ ADC1 │
        #                          │   H  │      └─────┘      │   H  │
        #                       ┌─►│AD1511│◄──┐  ADF4360   ┌─►│AD1511│◄──┐
        #                       │  └──────┘   │            │  └──────┘   │
        #                       │             │            │             │
        #                  ┌────┴────┐   ┌────┴────┐  ┌────┴────┐   ┌────┴────┐
        #                  │Frontend0│   │Frontend1│  │Frontend2│   │Frontend3│
        #                  └────┬────┘   └────┬────┘  └────┬────┘   └────┬────┘
        #                       │             │            │             │
        #                       │             │            │             │
        #                      BNC0          BNC1         BNC2          BNC3
        #
        # Each ADC is connected to 2 frontends, allowing up to 1GSa/s when selecting only 1 channel
        # and up to 500MSa/s with the 2 channels.
        # A common PLL is used to generate the reference clocks of the ADCs.
        # A common SPI bus is used for the control, with separate CS pins for each chip/part:
        # - CS0: PLL.
        # - CS1: ADC0.
        # - CS2: ADC1.
        # - CS3: Frontend (40-bit shift register).
        # - CS4..7: Variable Gain Amplifier CH1..CH4.
        #
        # Frontends
        # ---------
        # Each frontend is composed of 2 x 10:1 dividers, AC coupling, BW limitation features, a
        # a AD8370 Variable Gain Amplifier (VGA) and a AD4932 ADC Driver:
        #
        #                      ┌──────────────────┐  ┌──────┐  ┌────────┐
        #                      │ 2 x 10:1 Dividers│  │  VGA │  │  ADC   │
        #                 BNC─►│ AC/DC coupling   ├─►│      ├─►│ Driver ├─►To ADC
        #                      │ BW limitation    │  │AD8370│  │ AD4932 │
        #                      └──────────────────┘  └──────┘  └────────┘
        #
        # Frontends are controlled through a 40-bit shift register (8-bit shift register for each
        # channel + 1 ? shift register) (over the SPI bus), with the following bit mapping for
        # each channel:
        # - bit 0: ?
        # - bit 1: First  10:1 divider, active high.
        # - bit 2: Second 10:1 divider, active high.
        # - bit 3: AC coupling, low = AC, high = DC.
        # - bit 4: PGA enable, active high.
        # - bit 5: BW limit, low = 20MHz, high = full.
        # - bit 6: ?
        # - bit 7: ?
        # To set reasonable defaults (1V range) 0x78 can be used.
        # FIXME: Understand unknown bits.
        # FIXME: Understand why 40 total bit instead of 32-bit (4x8-bit).
        #
        # PLL
        # ---
        # Use these settings:
        #  - 40 31 20 # CONTROL
        #  - 04 E1 42 # NCOUNTER
        #  - 00 07 D1 # RCOUNTER
        #  FIXME: Document.
        #
        # ADC
        # ---
        # Needs a slighly more complicated setup.
        # https://github.com/360nosc0pe/software/blob/master/cheapscope/cheapscope.py has some example code.
        #
        # Total channel gain:
        # Each channel has two 10:1 dividers, a VGA and an ADC gain.
        # The dividers are configured in the FE bits.
        # Each VGA is on its own chip-select, see AD8370 spec.
        # The two ADCs are on separate chip selects. +0, +2, +4, +6, +9 dB can be selected.

        # Offset DAC/MUX
        # --------------
        self.offset_dac = OffsetDAC(platform.request("offset_dac"),
            sys_clk_freq = sys_clk_freq,
            spi_clk_freq = int(250e3)
        )

        # ADC + Frontends
        # ---------------

        # SPI.
        pads = self.platform.request("spi")
        pads.miso = Signal()
        self.spi = SPIMaster(pads, 48, self.sys_clk_freq, 8e6)

        # Trigger.
        self.trigger = Trigger()

        # ADCs + DMAs.
        for i in range(2):
            adc  = HAD1511ADC(None, sys_clk_freq, polarity=1)
            gate = stream.Gate([("data", 64)], sink_ready_when_disabled=True)
            port = self.sdram.crossbar.get_port()
            conv = stream.Converter(64, port.data_width)
            dma  = LiteDRAMDMAWriter(self.sdram.crossbar.get_port(), fifo_depth=16, with_csr=True)
            setattr(self.submodules, f"adc{i}",       adc)
            setattr(self.submodules, f"adc{i}_gate", gate)
            setattr(self.submodules, f"adc{i}_conv", conv)
            setattr(self.submodules, f"adc{i}_dma",   dma)
            self.submodules += stream.Pipeline(adc, gate, conv, dma)
            self.comb += gate.enable.eq(self.trigger.enable)

        # DMA Upload -------------------------------------------------------------------------------
        self.dma_upload = DMAUpload(
            dram_port = self.sdram.crossbar.get_port(),
            udp_port  = self.ethcore_etherbone.udp.crossbar.get_port(host_udp_port, dw=8),
            dst_ip       = host_ip,
            dst_udp_port = host_udp_port
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
    sim_config.add_clocker("sys_clk", freq_hz=100e6)
    sim_config.add_module("ethernet", "eth", args={"interface": "tap0", "ip": "192.168.1.100"})

    # Build
    # -----
    soc = ScopeSoC(
        scope_ip      = args.scope_ip,
        host_ip       = args.host_ip,
        host_udp_port = args.host_udp_port,
        with_analyzer = args.with_analyzer
    )
    builder = Builder(soc, csr_csv="test/csr.csv")
    vns = builder.build(
        sim_config  = sim_config,
        trace       = args.trace,
        trace_start = int(args.trace_start),
        trace_end   = int(args.trace_end)
    )

if __name__ == "__main__":
    main()
