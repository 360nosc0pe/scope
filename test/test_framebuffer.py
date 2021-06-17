#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# Framebuffer test utility.

import time
import sys
import argparse

from PIL import Image

from litex import RemoteClient

# Framebuffer Test ---------------------------------------------------------------------------------

def framebuffer_test(port):
    bus = RemoteClient(port=port)
    bus.open()

    image  = Image.open("glscopeclient_demo.png")
    pixels = image.load()

    for y in range(480):
        for x in range(800):
            r, g, b = pixels[x, y]
            bus.write(0x40c00000 + (y*800 + x)*4, (r << 16) | (g << 8) | (b << 0))

    bus.close()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Framebuffer test utility")
    parser.add_argument("--port",        default="1234",           help="Host bind port")
    args = parser.parse_args()

    port = int(args.port, 0)

    framebuffer_test(port=port)

if __name__ == "__main__":
    main()
