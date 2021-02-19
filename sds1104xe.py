#!/usr/bin/env python3

#
# This file is part of LiteX-Boards.
#
# Copyright (c) 2020 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# Build/Use ----------------------------------------------------------------------------------------
# Build/Load bitstream:
# ./sds1104xe.py --with-etherbone --uart-name=crossover --csr-csv=csr.csv --build --load
#
# Test Ethernet:
# ping 192.168.1.50
#
# Test Console:
# litex_server --udp
# litex_term crossover
# --------------------------------------------------------------------------------------------------

import os
import argparse

from migen import *

from platforms import sds1104xe
from litex.build.xilinx.vivado import vivado_build_args, vivado_build_argdict

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.soc_sdram import *
from litex.soc.integration.builder import *
from litex.soc.cores.spi import SPIMaster

from litedram.modules import MT41K64M16
from litedram.phy import s7ddrphy

from liteeth.phy.mii import LiteEthPHYMII

from peripherals.offsetdac import OffsetDac
from peripherals.adc import LvdsReceiver
from litescope import LiteScopeAnalyzer

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.clock_domains.cd_sys       = ClockDomain()
        self.clock_domains.cd_sys4x     = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_idelay    = ClockDomain()

        # # #

        self.submodules.pll = pll = S7PLL(speedgrade=-1)
        pll.register_clkin(ClockSignal("eth_tx"), 25e6)
        pll.create_clkout(self.cd_sys,       sys_clk_freq)
        pll.create_clkout(self.cd_sys4x,     4*sys_clk_freq)
        pll.create_clkout(self.cd_sys4x_dqs, 4*sys_clk_freq, phase=90)
        pll.create_clkout(self.cd_idelay,    200e6)
        platform.add_false_path_constraints(self.cd_sys.clk, pll.clkin) # Ignore sys_clk to pll.clkin path created by SoC's rst.

        self.submodules.idelayctrl = S7IDELAYCTRL(self.cd_idelay)

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    def __init__(self, sys_clk_freq=int(100e6), with_etherbone=False, eth_ip="192.168.1.50", **kwargs):
        platform = sds1104xe.Platform()

        # SoCCore ----------------------------------------------------------------------------------
        if kwargs["uart_name"] == "serial":
            kwargs["uart_name"] = "crossover" # Defaults to Crossover UART.
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident          = "LiteX SoC on Siglent SDS1104X-E",
            ident_version  = True,
            **kwargs)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # DDR3 SDRAM -------------------------------------------------------------------------------
        if not self.integrated_main_ram_size:
            self.submodules.ddrphy = s7ddrphy.A7DDRPHY(platform.request("ddram"),
                memtype        = "DDR3",
                nphases        = 4,
                sys_clk_freq   = sys_clk_freq)
            self.add_csr("ddrphy")
            self.add_sdram("sdram",
                phy                     = self.ddrphy,
                module                  = MT41K64M16(sys_clk_freq, "1:4"),
                origin                  = self.mem_map["main_ram"],
                size                    = kwargs.get("max_sdram_size", 0x40000000),
                l2_cache_size           = kwargs.get("l2_size", 8192),
                l2_cache_min_data_width = kwargs.get("min_l2_data_width", 128),
                l2_cache_reverse        = True
            )

        # Etherbone --------------------------------------------------------------------------------
        if with_etherbone:
            self.submodules.ethphy = LiteEthPHYMII(
                clock_pads = self.platform.request("eth_clocks"),
                pads       = self.platform.request("eth"))
            self.add_csr("ethphy")
            self.add_etherbone(phy=self.ethphy, ip_address=eth_ip)

        # Add scope hardware

        # Offset DAC/MUX
        self.submodules.offset_dac = OffsetDac(platform.request("offsetdac"), platform.request("offsetmux"))
        self.add_csr("offset_dac")

        # SPI for
        #  - CS0: PLL
        #  - CS1: ADC0
        #  - CS2: ADC1
        #  - CS3: Frontend (shift register)
        #  - CS4..7: Variable Gain Amplifier CH1..CH4
        #
        # set SPI length to 40 bit max, so it can cover the full FE shift register.

        #
        # FE bits are:
        # - 01 ?
        # - 02 First divider, 10:1, active high
        # - 04 Second divider, 10:1, active high
        # - 08 AC coupling, low = AC, high = DC
        # - 10 PGA enable, active high
        # - 20 BW limit, low = 20MHz, high = full
        # - 40 ?
        # - 80 ?
        #
        # So to set reasonable defaults (1V range), use:
        #
        # (double-check SPI CSR base address)
        # mem_write 0x82005018 8
        # mem_write 0x82005008 0x00
        # mem_write 0x8200500C 0x78787878  # CH4, CH3, CH2, CH1
        # mem_write 0x82005000 0x2801
        #

        # PLL:
        #
        # Use these settings:
        # 40 31 20 # CONTROL
        # 04 E1 42 # NCOUNTER
        # 00 07 D1 # RCOUNTER
        #

        # ADC:
        # Needs a slighly more complicated setup.
        # https://github.com/360nosc0pe/software/blob/master/cheapscope/cheapscope.py has some example code.

        #
        # Total channel gain:
        # Each channel has two 10:1 dividers, a VGA and an ADC gain.
        # The dividers are configured in the FE bits.
        # Each VGA is on its own chip-select, see AD8370 spec.
        # The two ADCs are on separate chip selects. +0, +2, +4, +6, +9 dB can be selected.
        #

        pads = self.platform.request("spi")
        pads.miso = Signal()
        self.submodules.spi = SPIMaster(pads, 6*8, self.sys_clk_freq, 8e6)
        self.add_csr("spi")

        # The ADC LVDS Interface
        LVDS_ADC = [
            ("d_p", 8, DIR_M_TO_S),
            ("d_n", 8, DIR_M_TO_S),
            ("fclk_p", 1, DIR_M_TO_S),
            ("fclk_n", 1, DIR_M_TO_S),
            ("lclk_p", 1, DIR_M_TO_S),
            ("lclk_n", 1, DIR_M_TO_S),
        ]

        self.submodules.adcif0 = LvdsReceiver(self.platform.request("adc", 0), 0)
        self.add_csr("adcif0")

        self.submodules.adcif1 = LvdsReceiver(self.platform.request("adc", 1), 1)
        self.add_csr("adcif1")


        # Litescope

        analyzer_signals = [
            self.adcif0.fclk,
            self.adcif0.d,
            self.adcif0.d_valid,
            self.adcif0.d_last,
            self.adcif0.d_ready,
        ]

        self.comb += self.adcif0.d_ready.eq(1)
        self.comb += self.adcif1.d_ready.eq(1)

        self.comb += self.adcif0.d_clk.eq(self.crg.cd_sys.clk)
        self.comb += self.adcif0.d_rst.eq(self.crg.cd_sys.rst)

        self.comb += self.adcif1.d_clk.eq(self.crg.cd_sys.clk)
        self.comb += self.adcif1.d_rst.eq(self.crg.cd_sys.rst)

        self.submodules.analyzer = LiteScopeAnalyzer(analyzer_signals,
            depth        = 1024,
            clock_domain = "sys",
            csr_csv      = "analyzer.csv")
        self.add_csr("analyzer")

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX SoC on SDS1104X-E")
    parser.add_argument("--build",          action="store_true",              help="Build bitstream")
    parser.add_argument("--load",           action="store_true",              help="Load bitstream")
    parser.add_argument("--sys-clk-freq",   default=100e6,                    help="System clock frequency (default: 100MHz)")
    parser.add_argument("--with-etherbone", action="store_true",              help="Enable Etherbone support")
    parser.add_argument("--eth-ip",         default="192.168.1.50", type=str, help="Ethernet/Etherbone IP address")
    builder_args(parser)
    soc_sdram_args(parser)
    vivado_build_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(
        sys_clk_freq   = int(float(args.sys_clk_freq)),
        with_etherbone = args.with_etherbone,
        eth_ip         = args.eth_ip,
        **soc_sdram_argdict(args)
    )

    builder = Builder(soc, **builder_argdict(args))
    builder.build(**vivado_build_argdict(args), run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"), device=1)

if __name__ == "__main__":
    main()
