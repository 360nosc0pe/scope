#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# DRAM Upload test utility.

import time
import argparse
import socket

from litex import RemoteClient

# DRAM Upload Test ---------------------------------------------------------------------------------

def dram_upload_test(port, base, length):

    bus = RemoteClient(port=port)
    bus.open()

    class DRAMUpload:
        def __init__(self, bus, chunk_length=1024):
            self.bus          = bus
            self.chunk_length = chunk_length

        def fill(self, base, data):
            for i in range(len(data)//4):
                word = int.from_bytes(bytes(data[4*i:4*(i+1)]), "little")
                self.bus.write(bus.mems.main_ram.base + base + 4*i, word)

        def upload(self, base, length):
            # Create Socket and listen.
            sock   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("192.168.1.100", 2000))

            # Upload Data in chunks.
            data   = []
            offset = 0
            while length > 0:
                bus.regs.dma_reader_enable.write(0)
                bus.regs.dma_reader_base.write(base + offset)
                bus.regs.dma_reader_length.write(self.chunk_length)
                bus.regs.dma_reader_enable.write(1)
                d, _ = sock.recvfrom(self.chunk_length)
                for b in d:
                    data.append(b)
                length -= self.chunk_length
                offset += self.chunk_length
            return data

    reference = [i%256 for i in range(length)]

    dram_upload = DRAMUpload(bus)

    print("Filling DRAM with Reference (over Etherbone)...")
    dram_upload.fill(base, reference)

    print("Uploading DRAM data (over UDP)...")
    data = dram_upload.upload(base, length)

    print("Checking DRAM data against Reference...")
    print("Success") if (set(data) == set(reference)) else print("Fail")

    #print(data)
    #print(reference)

    bus.close()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="DRAM Upload test utility")
    parser.add_argument("--port",        default="1234",           help="Host bind port")
    parser.add_argument("--base",        default=0,      type=int, help="Upload Test DRAM base.")
    parser.add_argument("--length",      default=1024,   type=int, help="Upload Test length (in bytes).")
    args = parser.parse_args()

    port = int(args.port, 0)

    dram_upload_test(port=port,
        base   = args.base,
        length = args.length
    )

if __name__ == "__main__":
    main()
