```
                              ____ ____ ___                    ___
                             |_  // __// _ \___  ___  ___ ____/ _ \___  ___
                            _/_ </ _ \/ // / _ \/ _ \(_-</ __/ // / _ \/ -_)
                           /____/\___/\___/_//_/\___/___/\__/\___/ .__/\__/
                                                                /_/

                                Siglent SDS1x0xX-E FPGA bitstreams
                                     Powered by Migen & LiteX
```

![License](https://img.shields.io/badge/License-BSD%202--Clause-orange.svg)


360nosc0pe Siglent SDS 1x0xX-E FPGA bitstreams
==============================================

This repo contains a LiteX project for an open source bitstream targetting the Siglent SDS 1x0xX-E series oscilloscopes.

<p align="center"><img src="https://user-images.githubusercontent.com/1450143/120784644-9856f280-c52c-11eb-8d99-1ec916dea836.png" width="800"></p>

Supported machines:
* Siglent SDS1104X-E or SDS1204X-E (exact same hardware)

Not yet supported (but likely easy to port):
* Siglent SDS1202X-E

[> Prerequisites
----------------
- Python3, Vivado WebPACK
- Either a Vivado-compatible JTAG cable (native or XVCD), or OpenOCD.

[> Installing LiteX
-------------------
```sh
$ wget https://raw.githubusercontent.com/enjoy-digital/litex/master/litex_setup.py
$ chmod +x litex_setup.py
$ sudo ./litex_setup.py init install
```

[> Prepare the target
---------------------

Follow the instructions [here](https://github.com/360nosc0pe/siglent_hardware/tree/master/sds1104xe) to
prepare for JTAG boot mode.

[> Build and Load the bitstream
--------------------------------
```sh
$ ./sds1104xe.py --eth-ip=192.168.1.50 --build --load
```

Instead of `--load` (which uses Vivado's hardware manager), configuration with OpenOCD is also possible:
```sh
$ openocd -f interface.cfg -f target/zynq_7000.cfg  -c "init" -c "zynqpl_program zynq_pl.bs" -c "pld load 0 sds1104xe.bit" -c "exit"
```

Due to a bug, it may be necessary to re-plug the ethernet cable after the
first configuration.

[> Open LiteX server
--------------------
```sh
$ litex_server.py --udp --udp-ip 192.168.1.50
```

[> Configure scope hardware and capture samples from CH1
-----------
Command used to capture a 115.2kbps UART:
```sh
$ ./test_adc.py --adc-samples=100000 --adc-downsampling=64 --afe-divider=1 --afe-auto-setup --plot --dump=dump.csv
```
