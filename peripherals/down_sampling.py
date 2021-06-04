#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.soc.interconnect import stream

# DownSampling -------------------------------------------------------------------------------------

# Note: Limited to current use-case (1 ADC = 1 Channel), add genericity.

class DownSamplingStage1(Module):
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
                _32to64.sink.data[16:24].eq(sink.data[32:48]),
                _32to64.sink.data[24:32].eq(sink.data[56:64]),
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


class DownSamplingStage2(Module):
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
            If(ratio == 0,
                count.eq(0)
            ).Elif(sink.valid & sink.ready,
                count.eq(count + 1),
                If(source.valid,
                    count.eq(0)
                )
            )
        ]
        self.comb += source.valid.eq(sink.valid & (count == ratio))


class DownSampling(Module):
    def __init__(self, ratio):
        self.sink   = sink   = stream.Endpoint([("data", 64)])
        self.source = source = stream.Endpoint([("data", 64)])

        # # #

        stage1 = DownSamplingStage1(ratio=ratio)
        stage2 = DownSamplingStage2(ratio=ratio[3:])
        self.submodules += stage1, stage2

        self.submodules += stream.Pipeline(sink, stage1, stage2, source)
