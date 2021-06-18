#!/usr/bin/env python3

#
# This file is part of 360nosc0pe/scope project.
#
# Copyright (c) 2021 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

# SCPI Server proof of concept, tested with ./glscopeclient --debug myscope:aklabs:lan:127.0.0.1

import os
import sys
import math
import time
import socket
import argparse
import threading

# SCPI Server --------------------------------------------------------------------------------------

class SCPIServer:
    def __init__(self, bind_ip="localhost", control_port=5025, control_only=False, waveform_port=50101):
        self.bind_ip       = bind_ip
        self.control_port  = control_port
        self.control_only  = control_only
        self.waveform_port = waveform_port

    def open(self):
        print(f"Opening Server {self.bind_ip}:c{self.control_port:d}:w{self.waveform_port:d}...")
        self.control_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_sock.bind((self.bind_ip, self.control_port))
        self.control_sock.listen(1)

        if not self.control_only:
            self.waveform_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.waveform_sock.bind((self.bind_ip, self.waveform_port))
            self.waveform_sock.listen(1)

    def close(self):
        print("Closing Server...")
        self.control_sock.close()
        del self.control_sock
        if not self.control_only:
            self.waveform_sock.close()
            del self.waveform_sock

    def _control_thread(self):
        while True:
            client, addr = self.control_sock.accept()
            print(f"Control: Connected with {addr[0]}:{str(addr[1])}")
            try:
                while True:
                    data = client.recv(1024).decode("UTF-8")
                    #print(data)
                    if "IDN?" in data:
                        client.send(bytes("360nosc0pe,SDS1104X-E,0001,0.1\n", "UTF-8"))
                    if "GAIN?" in data:
                        client.send(bytes("1\n", "UTF-8"))
                    if "OFFS?" in data:
                        client.send(bytes("0\n", "UTF-8"))
            finally:
                print("Control: Disconnect")
                client.close()

    def _waveform_thread(self):
        while True:
            client, addr = self.waveform_sock.accept()
            print(f"Waveform: Connected with {addr[0]}:{str(addr[1])}")
            try:
                while True:
                    client.send(bytes([int(128+128*math.sin(4*i*2*3.1415/16384)) for i in range(16384-16)]))
            finally:
                print("Waveform: Disconnect")
                client.close()

    def start(self):
        self.control_thread = threading.Thread(target=self._control_thread)
        self.control_thread.setDaemon(True)
        self.control_thread.start()

        if not self.control_only:
            self.waveform_thread = threading.Thread(target=self._waveform_thread)
            self.waveform_thread.setDaemon(True)
            self.waveform_thread.start()

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SCPI Server test.")
    parser.add_argument("--bind-ip",       default="localhost", help="Host bind address.")
    parser.add_argument("--control-port",  default=5025,        help="Host bind Control port.")
    parser.add_argument("--control-only",  action="store_true", help="Only enable Control port.")
    parser.add_argument("--waveform-port", default=50101,       help="Host bind Waveform port.")
    args = parser.parse_args()

    server = SCPIServer(
        bind_ip       = args.bind_ip,
        control_port  = int(args.control_port),
        control_only  = args.control_only,
        waveform_port = int(args.waveform_port)
    )
    server.open()
    server.start()
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
