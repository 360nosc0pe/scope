#!/usr/bin/env python3

import time
import sys
sys.path.append("../")

from peripherals.lcd import video_timings

from litex import RemoteClient

bus = RemoteClient()
bus.open()

bus.regs.vtg_enable.write(0)

vt = video_timings["800x480@60Hz"]

bus.regs.vtg_hres.write(        vt["h_active"])
bus.regs.vtg_hsync_start.write( vt["h_active"] + vt["h_sync_offset"])
bus.regs.vtg_hsync_end.write(   vt["h_active"] + vt["h_sync_offset"] + vt["h_sync_width"])
bus.regs.vtg_hscan.write(       vt["h_active"] + vt["h_blanking"])

bus.regs.vtg_vres.write(        vt["v_active"])
bus.regs.vtg_vsync_start.write( vt["v_active"] + vt["v_sync_offset"])
bus.regs.vtg_vsync_end.write(   vt["v_active"] + vt["v_sync_offset"] + vt["v_sync_width"])
bus.regs.vtg_vscan.write(       vt["v_active"] + vt["v_blanking"])

bus.regs.vtg_enable.write(1)

bus.close()
