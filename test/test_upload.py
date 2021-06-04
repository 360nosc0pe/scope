#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# DRAM Upload test utility.

import time
import sys
import argparse

from litex import RemoteClient

sys.path.append("..")
from peripherals.dma_upload import *

# Upload Test --------------------------------------------------------------------------------------

def upload_test(port, base, length):

    bus = RemoteClient(port=port)
    bus.open()

    class MemUpload:
        def __init__(self, bus, chunk_length=1024):
            self.bus          = bus
            self.chunk_length = chunk_length

        def fill(self, base, data):
            for i in range(len(data)//4):
                word = int.from_bytes(bytes(data[4*i:4*(i+1)]), "little")
                self.bus.write(bus.mems.main_ram.base + base + 4*i, word)

        def upload(self, base, length):
            return udp_data_retrieve(bus, base, length)

    reference = [i%256 for i in range(length)]

    mem_upload = MemUpload(bus)

    print("Filling Memory with Reference (over Etherbone)...")
    mem_upload.fill(base, reference)

    print("Uploading Memory data (over UDP)...")
    data = mem_upload.upload(base, length)

    print("Checking Uploaded data against Reference...")
    print("Success") if (set(data) == set(reference)) else print("Fail")

    #print(data)
    #print(reference)

    bus.close()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Upload test utility")
    parser.add_argument("--port",        default="1234",           help="Host bind port")
    parser.add_argument("--base",        default=0,      type=int, help="Upload Test base (in DRAM).")
    parser.add_argument("--length",      default=1024,   type=int, help="Upload Test length (in bytes).")
    args = parser.parse_args()

    port = int(args.port, 0)

    upload_test(port=port,
        base   = args.base,
        length = args.length
    )

if __name__ == "__main__":
    main()
