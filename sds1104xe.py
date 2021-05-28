#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import os
import argparse

from migen import *

from litex.build.generic_platform import *

from litex_boards.platforms import sds1104xe

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.spi import SPIMaster
from litex.soc.cores.video import VideoVGAPHY
from litex.soc.interconnect import stream

from litedram.modules import MT41K64M16
from litedram.phy import s7ddrphy
from litedram.frontend.dma import LiteDRAMDMAWriter, LiteDRAMDMAReader

from liteeth.common import convert_ip
from liteeth.phy.mii import LiteEthPHYMII
from liteeth.frontend.stream import LiteEthStream2UDPTX

from peripherals.offset_dac import OffsetDAC
from peripherals.adc import HMCAD1511

from peripherals.frontpanel import FrontpanelLeds, FrontpanelButtons

from litescope import LiteScopeAnalyzer

# Scope IOs ----------------------------------------------------------------------------------------

scope_ios = [
    # Offset DAC
    ("offset_dac", 0,
        # DAC.
        Subsignal("sclk",   Pins("H15")),
        Subsignal("din",    Pins("R15")),
        Subsignal("sync_n", Pins("J15")),
        # Mux.
        Subsignal("s",   Pins("U14 Y18 AA18")),
        Subsignal("e_n", Pins("U19")),
        IOStandard("LVCMOS15"),
    ),

    # SPI
    ("spi", 0,
        Subsignal("clk",  Pins("K15")),
        Subsignal("mosi", Pins("J16")),
        Subsignal("cs_n", Pins("J17 L16 L17 M17 N17 N18 M15 K20")), # PLL, ADC0, ADC1, FE, VGA1, VGA2, VGA3, VGA4
        IOStandard("LVCMOS15"),
    ),

    # ADCs (2X HMCAD1511).
    ("adc", 0,
        Subsignal("lclk_p", Pins("Y9")),  # Bitclock.
        Subsignal("lclk_n", Pins("Y8")),
        Subsignal("fclk_p", Pins("AA9")), # Frameclock.
        Subsignal("fclk_n", Pins("AA8")),
        Subsignal("d_p", Pins("AA12 AA11 W11 U10 V10 V8 Y11 AB10")), # Data.
        Subsignal("d_n", Pins("AB12 AB11 W10  U9  V9 W8 Y10  AB9")),
        IOStandard("LVDS_25"),
        Misc("DIFF_TERM=TRUE"),
    ),
    ("adc", 1,
        Subsignal("lclk_p", Pins("Y6")),  # Bitclock.
        Subsignal("lclk_n", Pins("Y5")),
        Subsignal("fclk_p", Pins("AA7")), # Frameclock.
        Subsignal("fclk_n", Pins("AA6")),
        Subsignal("d_p", Pins("AB7 AB5 V7 U6 W6 V5  Y4 AB2")), # Data.
        Subsignal("d_n", Pins("AB6 AB4 W7 U5 W5 V4 AA4 AB1")),
        IOStandard("LVDS_25"),
        Misc("DIFF_TERM=TRUE"),
    ),
]

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq, with_ethernet=False):
        self.rst = Signal()
        self.clock_domains.cd_sys       = ClockDomain()
        self.clock_domains.cd_sys4x     = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_idelay    = ClockDomain()
        self.clock_domains.cd_lcd       = ClockDomain()

        # # #

        # Clk / Rst
        clk25 = ClockSignal("eth_tx") if with_ethernet else platform.request("eth_clocks").rx

        # PLL
        self.submodules.pll = pll = S7PLL(speedgrade=-1)
        pll.register_clkin(clk25, 25e6)
        pll.create_clkout(self.cd_sys,       sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay,    200e6)
        pll.create_clkout(self.cd_lcd,       33.3e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin) # Ignore sys_clk to pll.clkin path created by SoC's rst.

        self.submodules.idelayctrl = S7IDELAYCTRL(self.cd_idelay)


# ScopeSoC -----------------------------------------------------------------------------------------

class ScopeSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(100e6), scope_ip="192.168.1.50", host_ip="192.168.1.100", host_udp_port=2000, with_analyzer=False):
        # Platform ---------------------------------------------------------------------------------
        platform = sds1104xe.Platform()
        platform.add_extension(scope_ios)

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident               = "ScopeSoC on Siglent SDS1104X-E",
            ident_version       = True,
            uart_name           = "crossover",
            cpu_type            = "vexriscv",
            cpu_variant         = "lite", # CPU only used to initialize DDR3 for now, Lite is enough.
            integrated_rom_size = 0x10000,
        )
        self.uart.add_auto_tx_flush(sys_clk_freq=sys_clk_freq, timeout=1, interval=128)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        self.submodules.ddrphy = s7ddrphy.A7DDRPHY(platform.request("ddram"),
            memtype        = "DDR3",
            nphases        = 4,
            sys_clk_freq   = sys_clk_freq)
        self.add_sdram("sdram",
            phy              = self.ddrphy,
            module           = MT41K64M16(sys_clk_freq, "1:4"),
            l2_cache_size    = 1024,
            l2_cache_reverse = False,
        )

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq, with_ethernet=True)

        # Etherbone --------------------------------------------------------------------------------
        self.submodules.ethphy = LiteEthPHYMII(
            clock_pads = self.platform.request("eth_clocks"),
            pads       = self.platform.request("eth"))
        self.add_etherbone(phy=self.ethphy, ip_address=scope_ip)

        # Frontpanel Leds --------------------------------------------------------------------------
        self.submodules.fpleds = FrontpanelLeds(platform.request("led_frontpanel"), sys_clk_freq)

        # Frontpanel Buttons -----------------------------------------------------------------------
        self.submodules.fpbtns = FrontpanelButtons(platform.request("btn_frontpanel"), sys_clk_freq)

        # LCD --------------------------------------------------------------------------------------
        video_timings = ("800x480@60Hz", {
            "pix_clk"       : 33.3e6,
            "h_active"      : 800,
            "h_blanking"    : 256,
            "h_sync_offset" : 210,
            "h_sync_width"  : 1,
            "v_active"      : 480,
            "v_blanking"    : 45,
            "v_sync_offset" : 22,
            "v_sync_width"  : 1,
        })
        self.submodules.lcdphy = VideoVGAPHY(platform.request("lcd"), clock_domain="lcd")
        #self.add_video_colorbars(phy=self.lcdphy, timings=video_timings, clock_domain="lcd")
        self.add_video_terminal(phy=self.lcdphy, timings=video_timings, clock_domain="lcd")

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
        #                          │  HMC │      └─────┘      │  HMC │
        #                       ┌─►│AD1511│◄──┐            ┌─►│AD1511│◄──┐
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
        self.submodules.offset_dac = OffsetDAC(platform.request("offset_dac"),
            sys_clk_freq = sys_clk_freq,
            spi_clk_freq = int(250e3)
        )

        # ADC + Frontends
        # ---------------

        # SPI.
        pads = self.platform.request("spi")
        pads.miso = Signal()
        self.submodules.spi = SPIMaster(pads, 48, self.sys_clk_freq, 8e6)

        # ADCs + DMAs.
        for i in range(2):
            adc  = HMCAD1511(self.platform.request("adc", i), sys_clk_freq)
            port = self.sdram.crossbar.get_port()
            conv = stream.Converter(64, port.data_width)
            dma  = LiteDRAMDMAWriter(self.sdram.crossbar.get_port(), fifo_depth=16, with_csr=True)
            setattr(self.submodules, f"adc{i}",      adc)
            setattr(self.submodules, f"adc{i}_conv", conv)
            setattr(self.submodules, f"adc{i}_dma",  dma)
            self.submodules += stream.Pipeline(adc, conv, dma)

        # Upload -----------------------------------------------------------------------------------
        # DMA Reader
        # ----------
        dram_port = self.sdram.crossbar.get_port()
        self.submodules.dma_reader      = LiteDRAMDMAReader(dram_port, fifo_depth=16, with_csr=True)
        self.submodules.dma_reader_conv = stream.Converter(dram_port.data_width, 8)

        # UDP Streamer
        # ------------
        udp_port       = self.ethcore.udp.crossbar.get_port(host_udp_port, dw=8)
        udp_streamer   = LiteEthStream2UDPTX(
            ip_address = convert_ip(host_ip),
            udp_port   = host_udp_port,
            fifo_depth = 1024,
            send_level = 1024
        )

        self.submodules.udp_cdc      = stream.ClockDomainCrossing([("data", 8)], "sys", "eth_rx")
        self.submodules.udp_streamer = ClockDomainsRenamer("eth_rx")(udp_streamer)

        # DMA -> UDP Pipeline
        # -------------------
        self.submodules += stream.Pipeline(
            self.dma_reader,
            self.dma_reader_conv,
            self.udp_cdc,
            self.udp_streamer,
            udp_port
        )

        # Analyzer ---------------------------------------------------------------------------------

        if with_analyzer:
            analyzer_signals = [
                self.dma_reader_conv.source,
                self.udp_cdc.source,
                self.udp_streamer.sink
            ]
            self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals,
                depth        = 1024,
                clock_domain = "sys",
                csr_csv      = "software/analyzer.csv"
            )

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Experiments with a SDS1104X-E Scope and LiteX.")
    parser.add_argument("--build",         action="store_true",               help="Build bitstream.")
    parser.add_argument("--load",          action="store_true",               help="Load bitstream.")
    parser.add_argument("--scope-ip",      default="192.168.1.50",  type=str, help="Scope IP address.")
    parser.add_argument("--host-ip",       default="192.168.1.100", type=str, help="Host  IP address.")
    parser.add_argument("--host-udp-port", default=2000,            type=int, help="Host UDP port.")
    parser.add_argument("--with-analyzer", action="store_true",               help="Enable Logic Analyzer.")
    args = parser.parse_args()

    soc = ScopeSoC(
        scope_ip      = args.scope_ip,
        host_ip       = args.host_ip,
        host_udp_port = args.host_udp_port,
        with_analyzer = args.with_analyzer
    )

    builder = Builder(soc, csr_csv="software/csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"), device=1)

if __name__ == "__main__":
    main()
