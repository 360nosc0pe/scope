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

from litex.gen import *

from litex.build.generic_platform import *

from litex_boards.platforms import siglent_sds1104xe

from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.interconnect import stream

from litex.soc.cores.clock  import S7PLL, S7IDELAYCTRL
from litex.soc.cores.spi    import SPIMaster
from litex.soc.cores.video  import VideoVGAPHY

from litedram.modules      import MT41K64M16
from litedram.phy          import s7ddrphy
from litedram.frontend.dma import LiteDRAMDMAWriter

from liteeth.phy.mii import LiteEthPHYMII

from peripherals.frontpanel  import FrontpanelLeds, FrontpanelButtons, FP_BTNS
from peripherals.offset_dac  import OffsetDAC
from peripherals.had1511_adc import HAD1511ADC
from peripherals.trigger     import Trigger
from peripherals.dma_upload  import DMAUpload

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

    # SBUS.
    ("sbus_dat", 0,
        Subsignal("tx_p", Pins("N19")), # 4.
        Subsignal("tx_n", Pins("N20")), # 7.
        IOStandard("LVDS_25"),
    ),
    ("sbus", 0,
        Subsignal("d0_p", Pins("N19"), IOStandard("LVCMOS15")), # 4.
        Subsignal("d0_n", Pins("N20"), IOStandard("LVCMOS15")), # 7.
        Subsignal("d1_p", Pins("H19"), IOStandard("LVCMOS33")), # 16.
        Subsignal("d1_n", Pins("H20"), IOStandard("LVCMOS33")), # 15.
        Subsignal("c0",   Pins("G15"), IOStandard("LVCMOS33")), # 17.
        Subsignal("c1",   Pins("G20"), IOStandard("LVCMOS33")), # 18.
        Subsignal("c2",   Pins("H17"), IOStandard("LVCMOS33")), # 19.
    ),
]

# CRG ----------------------------------------------------------------------------------------------

class _CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq, with_ethernet=False):
        self.rst = Signal()
        self.cd_sys       = ClockDomain()
        self.cd_sys4x     = ClockDomain(reset_less=True)
        self.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.cd_idelay    = ClockDomain()
        self.cd_lcd       = ClockDomain()

        # # #

        # Clk / Rst.
        clk25 = ClockSignal("eth_tx") if with_ethernet else platform.request("eth_clocks").rx

        # PLL.
        self.pll = pll = S7PLL(speedgrade=-1)
        pll.register_clkin(clk25, 25e6)
        pll.create_clkout(self.cd_sys,       sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay,    200e6)
        pll.create_clkout(self.cd_lcd,       33.3e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin) # Ignore sys_clk to pll.clkin path created by SoC's rst.

        # Idelay Ctrl.
        self.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

# ScopeSoC -----------------------------------------------------------------------------------------

class ScopeSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(100e6), scope_ip="192.168.1.50", host_ip="192.168.1.100", host_udp_port=2000, with_analyzer=False, with_sbus=False):
        # Platform ---------------------------------------------------------------------------------
        platform = siglent_sds1104xe.Platform()
        platform.add_extension(scope_ios)

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident               = "ScopeSoC on Siglent SDS1104X-E",
            ident_version       = True,
            uart_name           = "crossover",
            #cpu_type=None,
            cpu_type            = "vexriscv",
            cpu_variant         = "lite", # CPU only used to initialize DDR3 for now, Lite is enough.
            integrated_rom_size = 0x10000,
        )
        self.uart.add_auto_tx_flush(sys_clk_freq=sys_clk_freq, timeout=1, interval=128)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        self.ddrphy = s7ddrphy.A7DDRPHY(platform.request("ddram"),
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
        self.crg = _CRG(platform, sys_clk_freq, with_ethernet=True)

        # Etherbone --------------------------------------------------------------------------------
        self.ethphy = LiteEthPHYMII(
            clock_pads = self.platform.request("eth_clocks"),
            pads       = self.platform.request("eth"))
        self.add_etherbone(phy=self.ethphy, ip_address=scope_ip)

        # Frontpanel Leds --------------------------------------------------------------------------
        self.fpleds = FrontpanelLeds(platform.request("led_frontpanel"), sys_clk_freq)

        # Frontpanel Buttons -----------------------------------------------------------------------
        self.fpbtns = FrontpanelButtons(platform.request("btn_frontpanel"), sys_clk_freq)

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
        self.lcdphy = VideoVGAPHY(platform.request("lcd"), clock_domain="lcd")
        self.lcdphy_mux = stream.Multiplexer(self.lcdphy.sink.description, n=2)
        self.add_video_framebuffer(phy=self.lcdphy_mux.sink0, timings=video_timings, clock_domain="lcd")
        self.add_video_terminal(   phy=self.lcdphy_mux.sink1, timings=video_timings, clock_domain="lcd")
        self.comb += self.lcdphy_mux.source.connect(self.lcdphy.sink)
        menu_on_off   = Signal()
        menu_on_off_d = Signal()
        self.sync += menu_on_off.eq((self.fpbtns.value & FP_BTNS.MENU_ON_OFF.value) != 0)
        self.sync += menu_on_off_d.eq(menu_on_off)
        self.sync += If(menu_on_off & ~menu_on_off_d, self.lcdphy_mux.sel.eq(~self.lcdphy_mux.sel))

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
            adc  = HAD1511ADC(self.platform.request("adc", i), sys_clk_freq, polarity=1)
            gate = stream.Gate([("data", 64)], sink_ready_when_disabled=True)
            port = self.sdram.crossbar.get_port()
            conv = stream.Converter(64, port.data_width)
            dma  = LiteDRAMDMAWriter(self.sdram.crossbar.get_port(), fifo_depth=16, with_csr=True)
            self.add_module(name=f"adc{i}",      module=adc)
            self.add_module(name=f"adc{i}_gate", module=gate)
            self.add_module(name=f"adc{i}_conv", module=conv)
            self.add_module(name=f"adc{i}_dma",  module=dma)
            self.submodules += stream.Pipeline(adc, gate, conv, dma)
            self.comb += gate.enable.eq(self.trigger.enable)

        # DMA Upload -------------------------------------------------------------------------------
        self.dma_upload = DMAUpload(
            dram_port = self.sdram.crossbar.get_port(),
            udp_port  = self.ethcore_etherbone.udp.crossbar.get_port(host_udp_port, dw=8),
            dst_ip       = host_ip,
            dst_udp_port = host_udp_port
        )

        # SBUS -------------------------------------------------------------------------------------

        if with_sbus:

            from liteiclink.serwb.s7serdes import _S7SerdesTX

            self.cd_serdes   = ClockDomain()
            self.cd_serdes4x = ClockDomain()

            # SerDes PLL.
            self.serdes_pll = serdes_pll = S7PLL(speedgrade=-1)
            serdes_pll.register_clkin(ClockSignal("sys"), sys_clk_freq)
            serdes_pll.create_clkout(self.cd_serdes,   625.00e6, margin=0)
            serdes_pll.create_clkout(self.cd_serdes4x, 156.25e6, margin=0)

            # SerDes.
            sbus_serdes = _S7SerdesTX(pads=platform.request("sbus_dat"))
            sbus_serdes = ClockDomainsRenamer({
                "sys"   : "serdes",
                "sys4x" : "serdes4x",
            })(sbus_serdes)
            self.add_module(name="sbus_serdes", module=sbus_serdes)

            # Generate Comma.
            self.comb += sbus_serdes.comma.eq(1)


#            sbus_pads  = platform.request("sbus")
#            sbus_count = Signal(32)
#            self.sync += sbus_count.eq(sbus_count + 1)
#            self.sync += [
#                sbus_pads.d0_p.eq(sbus_count[ 8]),
#                sbus_pads.d0_n.eq(sbus_count[ 9]),
#                sbus_pads.d1_p.eq(sbus_count[10]),
#                sbus_pads.d1_n.eq(sbus_count[11]),
#                sbus_pads.c0.eq(sbus_count[12]),
#                sbus_pads.c1.eq(sbus_count[13]),
#                sbus_pads.c2.eq(sbus_count[14]),
#            ]

            analyzer_signals = [
                sbus_serdes.datapath.encoder.sink,
                sbus_serdes.datapath.converter.sink,
                sbus_serdes.datapath.converter.source,
            ]
            self.analyzer = LiteScopeAnalyzer(analyzer_signals,
                depth        = 1024,
                clock_domain = "serdes4x",
                csr_csv      = "test/analyzer.csv"
            )

        # Analyzer ---------------------------------------------------------------------------------
        if with_analyzer:
            analyzer_signals = [
                self.dma_reader_conv.source,
                self.udp_cdc.source,
                self.udp_streamer.sink
            ]
            self.analyzer = LiteScopeAnalyzer(analyzer_signals,
                depth        = 1024,
                clock_domain = "sys",
                csr_csv      = "test/analyzer.csv"
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

    builder = Builder(soc, csr_csv="test/csr.csv")
    builder.build(run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"), device=1)

if __name__ == "__main__":
    main()
