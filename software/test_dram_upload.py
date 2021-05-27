#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# DRAM Upload test utility.

import time
import socket

from litex import RemoteClient

bus = RemoteClient()
bus.open()

class DRAMUpload:
    chunk_length = 1024
    def run(self, base, length, filename="data.bin"):
        with open(filename, "wb") as f:
            # Create Socket and listen.
            sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("192.168.1.100", 2000))

            # Upload Data in chunks.
            offset = 0
            while length > 0:
                bus.regs.dma_reader_enable.write(0)
                bus.regs.dma_reader_base.write(base + offset)
                bus.regs.dma_reader_length.write(self.chunk_length)
                bus.regs.dma_reader_enable.write(1)
                data, _ = sock.recvfrom(1024)
                f.write(data)
                length -= self.chunk_length
                offset += self.chunk_length

dram_upload = DRAMUpload()
data = dram_upload.run(base=0x0000_0000, length=0x100000)

bus.close()
