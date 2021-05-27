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

test_length = 0x10000

class DRAMUpload:
    def run(self, base, length):
        for i in range(16):
            bus.write(0x4000_0000 + 4*i, i)
        #print(f"{bus.read(0x4000_0000):x}")
        bus.regs.dma_reader_enable.write(0)
        bus.regs.dma_reader_base.write(base)
        bus.regs.dma_reader_length.write(length)
        bus.regs.dma_reader_enable.write(1)
        #while not (bus.regs.dma_reader_done.read() & 0x1):
        #    print(bus.regs.dma_reader_offset.read())
        #bus.regs.dma_reader_enable.write(0)

print("Start DRAM upload ...")
dram_upload = DRAMUpload()
dram_upload.run(base=0x0000_0000, length=0x10000)

print("Receive UDP data to data.bin...")
data_length = 0
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("192.168.1.100", 2000))
f = open("data.bin", "wb")
while data_length < test_length:
    print(f"{data_length}/{test_length}\r", end="")
    data, addr = sock.recvfrom(1024)
    f.write(data)
    data_length += len(data)
print("Done"+" "*16)

bus.close()
