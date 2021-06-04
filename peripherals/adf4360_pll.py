#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from peripherals.spi import *

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# ADF4360 Register Field ---------------------------------------------------------------------------

class ADF4360RegField:
    def __init__(self, offset, size=1, value=0, values={}):
        self.offset = offset
        self.size   = size
        self.value  = value
        self.values = values

# ADF4360 Register ---------------------------------------------------------------------------------

class ADF4360Reg:
    def __init__(self):
        self.value = 0

    def encode(self):
        self.value = 0
        for k, v in self.__dict__.items():
            if isinstance(v, ADF4360RegField):
                self.value |= (int(v.value) & (2**v.size-1)) << v.offset
        return self.value

    def decode(self, value):
        for k, v in self.__dict__.items():
            if isinstance(v, ADF4360RegField):
                v.value = (int(value) >> v.offset) & (2**v.size-1)


    def __repr__(self):
        r = f"{self.__class__.__name__}:\n"
        align_len = 0
        for k, v in self.__dict__.items():
            if isinstance(v, ADF4360RegField):
                if len(k) > align_len:
                    align_len = len(k)
        for k, v in self.__dict__.items():
            r += f"  {k}{' '*(align_len-len(k))} : "
            try:
                r += f"{v.values[v.value]}\n"
            except:
                if v.size >= 4:
                    r += f"0x{v.value:x}\n"
                else:
                    r += f"0b{v.value:b}\n"
        r += "\n"
        return r


# ADF4360 Control Register -------------------------------------------------------------------------

class ADF4360Control(ADF4360Reg):
    def __init__(self, value=0x000000):
        self.CONTROL = ADF4360RegField(offset=0,  size=2)
        self.CORE_POWER_LEVEL        = ADF4360RegField(offset=2,  size=2,
            values={
                0b00: "5mA",
                0b01: "10mA",
                0b10: "15mA",
                0b11: "20mA",
            }
        )
        self.COUNTER_RESET           = ADF4360RegField(offset=4,  size=1,
            values={
                0b0 : "Normal Operation",
                0b1 : "Counters held in reset",
            }
        )
        self.MUXOUT_CONTROL          = ADF4360RegField(offset=5,  size=3,
            values={
                0b000 : "Tri-state Output",
                0b001 : "Digital Lock Detect",
                0b010 : "N Divider Output",
                0b011 : "DVDD",
                0b100 : "R Divider Output",
                0b101 : "N-Channel Open-Drain Lock Detect",
                0b110 : "Serial Data Output",
                0b111 : "DGND",
            }
        )
        self.PHASE_DETECTOR_POLARITY = ADF4360RegField(offset=8,  size=1,
            values={
                0b0 : "Negative",
                0b1 : "Positive",
        })
        self.CP_TRISTATE             = ADF4360RegField(offset=9,  size=1,
            values={
                0b0 : "Normal",
                0b1 : "Tristate",
            }
        )
        self.CP_GAIN                 = ADF4360RegField(offset=10, size=1,
            values={
                0b0 : "CURRENT_SETTING_1",
                0b1 : "CURRENT_SETTING_2",
            }
        )
        self.MUTE_TIL_LOCK_DETECT    = ADF4360RegField(offset=11, size=1,
            values={
                0b0 : "DISABLED",
                0b1 : "ENABLE",
            }
        )
        self.OUTPUT_POWER_LEVEL      = ADF4360RegField(offset=12, size=2,
            values={
                0b00 :  "3.5mA",
                0b01 :  "5.0mA",
                0b10 :  "7.5mA",
                0b11 : "11.0mA",
            }
        )
        self.CURRENT_SETTING_1       = ADF4360RegField(offset=14, size=3,
            values={
                0b000 : "0.31mA",
                0b001 : "0.62mA",
                0b010 : "0.93mA",
                0b011 : "1.25mA",
                0b100 : "1.56mA",
                0b101 : "1.87mA",
                0b110 : "2.18mA",
                0b111 : "2.50mA",
            }
        )
        self.CURRENT_SETTING_2       = ADF4360RegField(offset=17, size=3,
            values={
                0b000 : "0.31mA",
                0b001 : "0.62mA",
                0b010 : "0.93mA",
                0b011 : "1.25mA",
                0b100 : "1.56mA",
                0b101 : "1.87mA",
                0b110 : "2.18mA",
                0b111 : "2.50mA",
            }
        )
        self.POWER_DOWN              = ADF4360RegField(offset=20, size=2)
        self.PRESCALER_VALUE         = ADF4360RegField(offset=22, size=2,
            values={
                0b00 : "8/9",
                0b01 : "16/17",
                0b10 : "32/33",
                0b11 : "32/33",
            }
        )
        self.decode(value)

# ADF4360 R Counter Register -----------------------------------------------------------------------

class ADF4360RCounter(ADF4360Reg):
    def __init__(self, value=0x000001):
        self.CONTROL                   = ADF4360RegField(offset=0,  size=2)
        self.R_COUNTER                 = ADF4360RegField(offset=2,  size=14)
        self.ANTI_BACKLASH_PULSE_WIDTH = ADF4360RegField(offset=16, size=2,
            values={
                0b00 : "3.0ns",
                0b01 : "1.3ns",
                0b10 : "6.0ns",
                0b11 : "3.0ns",
            }
        )
        self.LOCK_DETECT_PRECISION     = ADF4360RegField(offset=18, size=1)
        self.TEST_MODE_BIT             = ADF4360RegField(offset=19, size=1)
        self.BAND_SELECT_CLOCK_DIV     = ADF4360RegField(offset=20, size=2,
            values={
                0b00 : "1",
                0b01 : "2",
                0b10 : "3",
                0b11 : "4",
            }
        )
        self.decode(value)

# ADF4360 N Counter Register -----------------------------------------------------------------------

class ADF4360NCounter(ADF4360Reg):
    def __init__(self, value=0x000002):
        self.CONTROL            = ADF4360RegField(offset=0,  size=2)
        self.A_COUNTER          = ADF4360RegField(offset=2,  size=5)
        self.B_COUNTER          = ADF4360RegField(offset=8,  size=13)
        self.CP_GAIN            = ADF4360RegField(offset=21, size=1,
            values={
                0b0 : "CURRENT_SETTING_1",
                0b1 : "CURRENT_SETTING_2",
            }
        )
        self.DIVIDE_BY_2        = ADF4360RegField(offset=22, size=1,
            values={
                0b0 : "Fundamental Output",
                0b1 : "Divide by 2",
            }
        )
        self.DIVIDE_BY_2_SELECT = ADF4360RegField(offset=23, size=1,
            values={
                0b0 : "Fundamental Output Selected",
                0b1 : "Divide by 2 Selected",
            }
        )
        self.decode(value)

# ADF4360 PLL --------------------------------------------------------------------------------------

class ADF4360PLLDriver:
    def __init__(self, bus, spi):
        self.bus = bus
        self.spi = spi

    def init(self, control_value=0x403120, r_counter_value=0x0007d1, n_counter_value=0x04e142):
        control   = ADF4360Control( value=control_value)
        r_counter = ADF4360RCounter(value=r_counter_value)
        n_counter = ADF4360NCounter(value=n_counter_value)
        print(control)
        print(r_counter)
        print(n_counter)

        self.write(r_counter.encode())
        self.write(control.encode())
        self.write(n_counter.encode())

    def write(self, value):
        self.spi.write(SPI_CS_PLL, [(value >> 8*i) & 0xff for i in reversed(range(3))])
