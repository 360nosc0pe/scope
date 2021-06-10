#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.soc.interconnect import stream

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E S C R I P T I O N                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# []     : 64-bit word.
# n0..n7 : Bytes composing the 64-bit word.

# 1 Channel
# ---------
# Input = [a0..a7], [b0..b7], [c0..c7], [d0..d7], ...:
# Ratio = 1,  Output: Identity.
# Ratio = 2,  Output: [a0, a2, a4, a6, b0, b2, b4, b6]
# Ratio = 4,  Output: [a0, a4, b0, b4, c0, c4, d0, d4]
# Ratio = 8,  Output: [a0, b0, c0, d0, e0, f0, h0, i0]
# Ratio = 16, Output: [a0, c0, e0, h0, ...]

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                               D E F I N I T I O N S                                              #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  G A T E W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# DownSampling -------------------------------------------------------------------------------------

class DownSamplingStage1(Module):
    def __init__(self, ratio):
        self.sink   = sink   = stream.Endpoint([("data", 64)])
        self.source = source = stream.Endpoint([("data", 64)])

        # # #

        # Recopy Ready/Data.
        self.comb += sink.ready.eq(source.ready)
        self.comb += source.data.eq(sink.data)

        # Throttle Valid.
        count = Signal(16)
        self.sync += [
            If(ratio < 1,
                count.eq(0)
            ).Elif(sink.valid & sink.ready,
                count.eq(count + 1),
                If(count == (ratio - 1),
                    count.eq(0)
                )
            )
        ]
        self.comb += source.valid.eq(sink.valid & (count == 0))

class DownSamplingStage2(Module):
    def __init__(self, ratio):
        self.sink   = sink   = stream.Endpoint([("data", 64)])
        self.source = source = stream.Endpoint([("data", 64)])

        # # #

        # Data-Width Converters.
        _32to64 = stream.Converter(32, 64)
        _16to64 = stream.Converter(16, 64)
        _8to64  = stream.Converter(8,  64)
        self.submodules += _32to64, _16to64, _8to64

        # Data-Path.
        self.comb += [
            # 1:1 Ratio.
            If(ratio <= 1,
                sink.connect(source)
            # 1:2 Ratio.
            ).Elif(ratio <= 2,
                sink.connect(_32to64.sink, keep={"valid", "ready"}),
                _32to64.sink.data[ 0: 8].eq(sink.data[ 0:8]),
                _32to64.sink.data[ 8:16].eq(sink.data[16:24]),
                _32to64.sink.data[16:24].eq(sink.data[32:40]),
                _32to64.sink.data[24:32].eq(sink.data[48:56]),
                _32to64.source.connect(source)
            # 1:4 Ratio.
            ).Elif(ratio <= 4,
                sink.connect(_16to64.sink, keep={"valid", "ready"}),
                _16to64.sink.data[0: 8].eq(sink.data[ 0:8]),
                _16to64.sink.data[8:16].eq(sink.data[32:48]),
                _16to64.source.connect(source)
            # >= 1:8 Ratio.
            ).Else(
                sink.connect(_8to64.sink, keep={"valid", "ready"}),
                _8to64.sink.data[0:8].eq(sink.data[ 0:8]),
                _8to64.source.connect(source)
            )
        ]

class DownSampling(Module):
    def __init__(self, ratio=None):
        self.ratio  = ratio if ratio is not None else Signal(16)
        self.sink   = sink   = stream.Endpoint([("data", 64)])
        self.source = source = stream.Endpoint([("data", 64)])

        # # #

        stage1 = DownSamplingStage1(ratio=self.ratio[3:])
        stage2 = DownSamplingStage2(ratio=self.ratio)
        self.submodules += stage1, stage2

        self.submodules += stream.Pipeline(sink, stage1, stage2, source)

# Simulation ---------------------------------------------------------------------------------------

from litex.gen.sim import run_simulation

if __name__ == '__main__':
    def data_generator(dut, ratio, data_in):
        yield dut.ratio.eq(ratio)
        yield
        for data in data_in:
            yield dut.sink.valid.eq(1)
            yield dut.sink.data.eq(data)
            while (yield dut.sink.ready) == 0:
                yield
            yield

    def data_checker(dut, data_out):
        yield dut.source.ready.eq(1)
        yield
        for data in data_out:
            while (yield dut.source.valid) == 0:
                yield
            if (yield dut.source.data) != data:
                dut.errors += 1
                print(f"Mismatch: {(yield dut.source.data):x} vs {data:x}")
            yield

    test_configs = [
        {
            "ratio"   : 1,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
            ],
        },
        {
            "ratio"   : 2,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0xeeccaa8866442200, 0xeeccaa8866442200,
                0xeeccaa8866442200, 0xeeccaa8866442200,
            ]
        },
        {
            "ratio"   : 4,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0xcc884400cc884400, 0xcc884400cc884400,
            ]
        },
        {
            "ratio"   : 8,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221100, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0x8800880088008800,
            ]
        },
        {
            "ratio"   : 16,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221101, 0xffeeddccbbaa9988,
                0x7766554433221102, 0xffeeddccbbaa9988,
                0x7766554433221103, 0xffeeddccbbaa9988,
                0x7766554433221104, 0xffeeddccbbaa9988,
                0x7766554433221105, 0xffeeddccbbaa9988,
                0x7766554433221106, 0xffeeddccbbaa9988,
                0x7766554433221107, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0x0706050403020100,
            ]
        },
        {
            "ratio"   : 32,
            "data_in" : [
                0x7766554433221100, 0xffeeddccbbaa9988,
                0x7766554433221101, 0xffeeddccbbaa9988,
                0x7766554433221102, 0xffeeddccbbaa9988,
                0x7766554433221103, 0xffeeddccbbaa9988,
                0x7766554433221104, 0xffeeddccbbaa9988,
                0x7766554433221105, 0xffeeddccbbaa9988,
                0x7766554433221106, 0xffeeddccbbaa9988,
                0x7766554433221107, 0xffeeddccbbaa9988,
                0x7766554433221108, 0xffeeddccbbaa9988,
                0x7766554433221109, 0xffeeddccbbaa9988,
                0x776655443322110a, 0xffeeddccbbaa9988,
                0x776655443322110b, 0xffeeddccbbaa9988,
                0x776655443322110c, 0xffeeddccbbaa9988,
                0x776655443322110d, 0xffeeddccbbaa9988,
                0x776655443322110e, 0xffeeddccbbaa9988,
                0x776655443322110f, 0xffeeddccbbaa9988,
            ],
            "data_out" : [
                0x0e0c0a0806040200,
            ]
        },
    ]
    for config in test_configs:
        dut        = DownSampling()
        dut.errors = 0
        generator  = data_generator(dut,
            ratio    = config["ratio"],
            data_in  = config["data_in"],
        )
        checker = data_checker(dut,
            data_out = config["data_out"],
        )
        run_simulation(dut, [generator, checker], vcd_name="downsampling.vcd")
        assert dut.errors == 0

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

# N/A.
