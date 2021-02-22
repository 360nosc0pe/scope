#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.cdc import MultiReg

from litex.soc.interconnect.csr import *
from litex.soc.interconnect import stream

# Video Constants ----------------------------------------------------------------------------------

hbits = 12
vbits = 12

# Video Timings ------------------------------------------------------------------------------------

video_timings = {
    "800x600@60Hz" : {
        "pix_clk"       : 40e6,
        "h_active"      : 800,
        "h_blanking"    : 256,
        "h_sync_offset" : 40,
        "h_sync_width"  : 128,
        "v_active"      : 600,
        "v_blanking"    : 28,
        "v_sync_offset" : 1,
        "v_sync_width"  : 4,
    },
}

# Video Timing Generator ---------------------------------------------------------------------------

video_timing_generator_layout = [
    # Standard synchronization signals.
    ("hsync", 1),
    ("vsync", 1),
    ("de",    1),

    # Optional synchronization signals.
    ("hcount", hbits),
    ("vcount", vbits),
]

class VideoTimingGenerator(Module, AutoCSR):
    def __init__(self, default_video_timings="800x600@60Hz", clock_domain="lcd"):
        vt = video_timings[default_video_timings]
        # MMAP Control/Status Registers.
        self._enable      = CSRStorage(reset=1)

        self._hres        = CSRStorage(hbits, vt["h_active"])
        self._hsync_start = CSRStorage(hbits, vt["h_active"] + vt["h_sync_offset"])
        self._hsync_end   = CSRStorage(hbits, vt["h_active"] + vt["h_sync_offset"] + vt["h_sync_width"])
        self._hscan       = CSRStorage(hbits, vt["h_active"] + vt["h_blanking"])

        self._vres        = CSRStorage(vbits, vt["v_active"])
        self._vsync_start = CSRStorage(vbits, vt["v_active"] + vt["v_sync_offset"])
        self._vsync_end   = CSRStorage(vbits, vt["v_active"] + vt["v_sync_offset"] + vt["v_sync_width"])
        self._vscan       = CSRStorage(vbits, vt["v_active"] + vt["v_blanking"])

        # Video Timing Source
        self.source = source = stream.Endpoint(video_timing_generator_layout)
        source.ready.reset = 1 # Set default Ready value to 1.

        # # #

        # Resynchronize Enable to Video clock domain.
        self.enable = enable = Signal()
        self.specials += MultiReg(self._enable.storage, enable, clock_domain)

        # Resynchronize Horizontal Timings to Video clock domain.
        self.hres        = hres        = Signal(hbits)
        self.hsync_start = hsync_start = Signal(hbits)
        self.hsync_end   = hsync_end   = Signal(hbits)
        self.hscan       = hscan       = Signal(hbits)
        self.specials += MultiReg(self._hres.storage,        hres,        clock_domain)
        self.specials += MultiReg(self._hsync_start.storage, hsync_start, clock_domain)
        self.specials += MultiReg(self._hsync_end.storage,   hsync_end,   clock_domain)
        self.specials += MultiReg(self._hscan.storage,       hscan,       clock_domain)

        # Resynchronize Vertical Timings to Video clock domain.
        self.vres        = vres        = Signal(vbits)
        self.vsync_start = vsync_start = Signal(vbits)
        self.vsync_end   = vsync_end   = Signal(vbits)
        self.vscan       = vscan       = Signal(vbits)
        self.specials += MultiReg(self._vres.storage,        vres,        clock_domain)
        self.specials += MultiReg(self._vsync_start.storage, vsync_start, clock_domain)
        self.specials += MultiReg(self._vsync_end.storage,   vsync_end,   clock_domain)
        self.specials += MultiReg(self._vscan.storage,       vscan,       clock_domain)

        # Generate timings.
        hactive = Signal()
        vactive = Signal()
        self.submodules.fsm = fsm = ClockDomainsRenamer(clock_domain)(FSM(reset_state="IDLE"))
        fsm.act("IDLE",
            NextValue(hactive, 0),
            NextValue(vactive, 0),
            NextValue(source.hcount, 0),
            NextValue(source.vcount, 0),
            If(enable,
                NextState("RUN")
            )
        )
        self.comb += [
            source.de.eq(hactive & vactive), # DE when both HActive and VActive.
            source.first.eq((source.hcount ==     0) & (source.vcount ==     0)),
            source.last.eq( (source.hcount == hscan) & (source.vcount == vscan)),
        ]
        fsm.act("RUN",
            source.valid.eq(1),
            If(source.ready,
                # Increment HCount.
                NextValue(source.hcount, source.hcount + 1),
                # Generate HActive / HSync.
                If(source.hcount == 0,           NextValue(hactive,      1)), # Start of HActive.
                If(source.hcount == hres,        NextValue(hactive,      0)), # End of HActive.
                If(source.hcount == hsync_start, NextValue(source.hsync, 1)), # Start of HSync.
                If(source.hcount == hsync_end,   NextValue(source.hsync, 0)), # End of HSync.
                # End of HScan.
                If(source.hcount == hscan,
                    # Reset HCount.
                    NextValue(source.hcount, 0),
                    # Increment VCount.
                    NextValue(source.vcount, source.vcount + 1),
                    # Generate VActive / VSync.
                    If(source.vcount == 0,           NextValue(vactive,      1)), # Start of VActive.
                    If(source.vcount == vres,        NextValue(vactive,      0)), # End of HActive.
                    If(source.vcount == vsync_start, NextValue(source.vsync, 1)), # Start of VSync.
                    If(source.vcount == vsync_end,   NextValue(source.vsync, 0)), # End of VSync.
                    # End of VScan.
                    If(source.vcount == vscan,
                        # Reset VCount.
                        NextValue(source.vcount, 0),
                    )
                )
            )
        )

# Patterns -----------------------------------------------------------------------------------------

class ColorBarsPattern(Module):
    """Color Bars Pattern"""
    def __init__(self, vtg, clock_domain="lcd"):
        self.enable = Signal(reset=1)
        self.source = source = stream.Endpoint([("r", 8), ("g", 8), ("b", 8)])

        # # #

        _sync = getattr(self.sync, clock_domain)

        # Control Path
        pix = Signal(hbits)
        bar = Signal(3)
        _sync += [
            source.valid.eq(self.enable),
            If(source.valid & source.ready,
                pix.eq(pix + 1),
                If(pix == (vtg.hres[3:] - 1),
                    pix.eq(0),
                    bar.eq(bar + 1)
                )
            )
        ]

        # Data Path
        color_bar = [
            # R     G     B
            [0xff, 0xff, 0xff], # White
            [0xff, 0xff, 0x00], # Yellow
            [0x00, 0xff, 0xff], # Cyan
            [0x00, 0xff, 0x00], # Green
            [0xff, 0x00, 0xff], # Purple
            [0xff, 0x00, 0x00], # Red
            [0x00, 0x00, 0xff], # Blue
            [0x00, 0x00, 0x00], # Black
        ]
        cases = {}
        for i in range(8):
            cases[i] = [
                source.r.eq(color_bar[i][0]),
                source.g.eq(color_bar[i][1]),
                source.b.eq(color_bar[i][2])
            ]
        _sync += Case(bar, cases)
