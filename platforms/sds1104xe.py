#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Felix Domke <tmbinc@elitedvb.net>
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform, VivadoProgrammer

# IOs ----------------------------------------------------------------------------------------------

_io = [ # Documented by https://github.com/360nosc0pe project.
    # Leds
    ("user_led", 0, Pins("G16"), IOStandard("LVCMOS33")),

    # Beeper
    ("beeper", 0, Pins("W17"), IOStandard("LVCMOS33")),

    # Led Frontpanel
    ("led_frontpanel", 0,
        Subsignal("rclk", Pins("N22")),
        Subsignal("clk",  Pins("R20")),
        Subsignal("mosi", Pins("P22")),
        Subsignal("oe",   Pins("R21")),
        IOStandard("LVCMOS33"),
    ),

    # Button Frontpanel
    ("btn_frontpanel", 0,
        Subsignal("clk",  Pins("H18")),
        Subsignal("clr",  Pins("G19")),
        Subsignal("miso", Pins("G17")),
        IOStandard("LVCMOS33")
    ),

    # LCD
    ("lcd", 0,
        Subsignal("clk",   Pins("D20")),
        Subsignal("vsync", Pins("A21")),
        Subsignal("hsync", Pins("A22")),
        Subsignal("r", Pins("G22 F22 F21 F19 F18 F17")),
        Subsignal("g", Pins("F16 E21 E20 E19 E18 E16")),
        Subsignal("b",  Pins("D22 D21 C22 C20 B22 B21")),
        IOStandard("LVCMOS33"),
    ),

    # MII Ethernet
    ("eth_clocks", 0,
        Subsignal("tx", Pins("B19")),
        Subsignal("rx", Pins("C17")),
        IOStandard("LVCMOS33"),
    ),
    ("eth", 0,
        Subsignal("rst_n",   Pins("R6"), IOStandard("LVCMOS25")),
        Subsignal("mdio",    Pins("E15")),
        Subsignal("mdc",     Pins("D15")),
        Subsignal("rx_dv",   Pins("A16")),
        Subsignal("rx_er",   Pins("C15")),
        Subsignal("rx_data", Pins("D16 A17 B17 D17")),
        Subsignal("tx_en",   Pins("A18")),
        Subsignal("tx_data", Pins("C18 A19 C19 B20")),
        Subsignal("col",     Pins("B16")),
        Subsignal("crs",     Pins("B15")),
        IOStandard("LVCMOS33"),
    ),

    # Scope things
    ("offset_mux", 0,
        Subsignal("S",       Pins("U14 Y18 AA18")),
        Subsignal("nE",      Pins("U19")),
        IOStandard("LVCMOS15"),
    ),

    ("offset_dac", 0,
        Subsignal("SCLK",       Pins("H15")),
        Subsignal("DIN",        Pins("R15")),
        Subsignal("nSYNC",      Pins("J15")),
        IOStandard("LVCMOS15"),
    ),

    ("spi", 0,
        Subsignal("clk",  Pins("K15")),
        Subsignal("mosi", Pins("J16")),
        Subsignal("cs_n", Pins("J17 L16 L17 M17 N17 N18 M15 K20")), # PLL, ADC0, ADC1, FE, VGA1, VGA2, VGA3, VGA4
        IOStandard("LVCMOS15"),
    ),

    # ADC HAD1511 x2
    ("adc", 0,
        Subsignal("d", Pins("AA12 AB12 AA11 AB11 W11 W10 U10 U9 " # D0..D3, each P/N
                       "V10 V9 V8 W8 Y11 Y10 AB10 AB9 ")),
        Subsignal("lclk", Pins("Y9 Y8")),
        Subsignal("fclk", Pins("AA9 AA8")),
        IOStandard("LVDS_25"),
        Misc("DIFF_TERM=TRUE"),
    ),

    ("adc", 1,
        Subsignal("d", Pins("AB7 AB6 AB5 AB4 V7 W7 U6 U5 "
                        "W6 W5 V5 V4 Y4 AA4 AB2 AB1")),
        Subsignal("lclk", Pins("Y6 Y5")),
        Subsignal("fclk", Pins("AA7 AA6")),
        IOStandard("LVDS_25"),
        Misc("DIFF_TERM=TRUE"),
    ),

    # DDR3 SDRAM
    ("ddram", 0,
        Subsignal("a", Pins(
            "J21 K18 J18 R16 P16 T18 R18 T19",
            "R19 P18 P17 P15 N15"),
            IOStandard("SSTL15")),
        Subsignal("ba",    Pins("K21 J20 J22"), IOStandard("SSTL15")),
        Subsignal("ras_n", Pins("L21"), IOStandard("SSTL15")),
        Subsignal("cas_n", Pins("L22"), IOStandard("SSTL15")),
        Subsignal("we_n",  Pins("K19"), IOStandard("SSTL15")),
        #Subsignal("cs_n", Pins(""), IOStandard("SSTL15")), # Pulled low.
        #Subsignal("dm",   Pins(""), IOStandard("SSTL15")), # Pulled low.
        Subsignal("dq", Pins(
            " T21  U21  T22  U22  W20  W21 U20   V20",
            "AA22 AB22 AA21 AB21 AB19 AB20 Y19  AA19",
	        " W16  Y16  U17  V17 AA17 AB17 AA16 AB16",
	        " V14  V13  W13  Y14 AA14  Y13 AA13 AB14"),
            IOStandard("SSTL15"),
            Misc("IN_TERM=UNTUNED_SPLIT_40")),
        Subsignal("dqs_p", Pins("V22 Y20 U15 W15"),
            IOStandard("DIFF_SSTL15"),
            Misc("IN_TERM=UNTUNED_SPLIT_40")),
        Subsignal("dqs_n", Pins("W22 Y21 U16 Y15"),
            IOStandard("DIFF_SSTL15"),
            Misc("IN_TERM=UNTUNED_SPLIT_40")),
        Subsignal("clk_p",   Pins("T16"), IOStandard("DIFF_SSTL15")),
        Subsignal("clk_n",   Pins("T17"), IOStandard("DIFF_SSTL15")),
        Subsignal("cke",     Pins("M21"), IOStandard("SSTL15")),
        Subsignal("odt",     Pins("M22"), IOStandard("SSTL15")),
        Subsignal("reset_n", Pins("V18"), IOStandard("SSTL15")),
        Misc("SLEW=FAST"),
    ),
]

# Connectors ---------------------------------------------------------------------------------------

_connectors = []

# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    def __init__(self):
        XilinxPlatform.__init__(self, "xc7z020-clg484-1", _io,  _connectors, toolchain="vivado")

    def create_programmer(self):
        return VivadoProgrammer()

    def do_finalize(self, fragment):
        XilinxPlatform.do_finalize(self, fragment)
        self.add_period_constraint(self.lookup_request("eth_clocks:rx", loose=True), 1e9/25e6)
        self.add_period_constraint(self.lookup_request("eth_clocks:tx", loose=True), 1e9/25e6)
