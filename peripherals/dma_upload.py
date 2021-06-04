#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import socket

from peripherals.spi import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect import stream

from litedram.frontend.dma import LiteDRAMDMAReader

from liteeth.common import convert_ip
from liteeth.frontend.stream import LiteEthStream2UDPTX

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

class DMAUpload(Module, AutoCSR):
    def __init__(self, dram_port, udp_port, dst_ip, dst_udp_port):
        # DMA Reader
        # ----------
        self.submodules.dma_reader      = LiteDRAMDMAReader(dram_port, fifo_depth=16, with_csr=True)
        self.submodules.dma_reader_conv = stream.Converter(dram_port.data_width, 8)

        # UDP Streamer
        # ------------
        udp_streamer   = LiteEthStream2UDPTX(
            ip_address = convert_ip(dst_ip),
            udp_port   = dst_udp_port,
            fifo_depth = 1024,
            send_level = 1024
        )

        self.submodules.udp_cdc      = stream.ClockDomainCrossing([("data", 8)], "sys", "eth_rx")
        self.submodules.udp_streamer = ClockDomainsRenamer("eth_rx")(udp_streamer)

        # DMA -> UDP Pipeline
        # -------------------
        self.submodules += stream.Pipeline(
            self.dma_reader,
            self.dma_reader_conv,
            self.udp_cdc,
            self.udp_streamer,
            udp_port
        )

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #
#                                  S O F T W A R E                                                 #
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ #

def udp_data_retrieve(bus, base, length):
    dma_data = []
    offset   = 0
    sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("192.168.1.100", 2000))
    while length > 0:
        bus.regs.dma_upload_dma_reader_enable.write(0)
        bus.regs.dma_upload_dma_reader_base.write(base + offset)
        bus.regs.dma_upload_dma_reader_length.write(1024)
        bus.regs.dma_upload_dma_reader_enable.write(1)
        data, _ = sock.recvfrom(1024)
        for b in data:
            dma_data.append(b)
        length -= len(data)
        offset += len(data)
    return dma_data

def etherbone_data_retrieve(bus, base, length):
    dma_data = []
    for i in range(length//4):
        word = bus.read(bus.mems.main_ram.base + base + 4*i)
        dma_data.append((word >> 0)  & 0xff)
        dma_data.append((word >> 8)  & 0xff)
        dma_data.append((word >> 16) & 0xff)
        dma_data.append((word >> 24) & 0xff)
    return dma_data
