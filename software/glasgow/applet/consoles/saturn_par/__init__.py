from abc import ABCMeta, abstractmethod, abstractproperty
import os.path
import logging
import argparse
import struct
import asyncio
import hashlib
import gzip
import io
from amaranth import *
from amaranth.lib import data
from amaranth.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....gateware.clockgen import *
from ....protocol.vgm import *
from ... import *


class ProActionReplayBus(Elaboratable):
    def __init__(self, pads):
        self.pads = pads

        self.di = Signal(8)
        self.do = Signal(8)

        self.par_stb = Signal()
        self.par_ack = Signal()


    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.pads.par_stb_t.o.eq(self.par_stb),
            self.pads.par_stb_t.oe.eq(1),
            self.par_ack.eq(self.pads.par_ack_t.i),
            self.pads.d_t.oe.eq(~self.par_ack),
            self.pads.d_t.o.eq(self.do)
        ]

        with m.If(self.par_ack):
            m.d.sync += [
                self.di.eq(self.pads.d_t.i),
            ]    
        
        return m


class ProActionReplaySubtarget(Elaboratable):
    def __init__(self, pads, in_fifo, out_fifo):
        self.in_fifo = in_fifo
        self.out_fifo = out_fifo

        self.par_bus = ProActionReplayBus(pads)

    def elaborate(self, platform):
        m = Module()

        m.submodules.par_bus = self.par_bus

        with m.FSM() as fsm:
            with m.State("IDLE"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += self.par_bus.do.eq(self.out_fifo.r_data)
                    m.next = "STB-DELAY"
            with m.State("STB-DELAY"):
                m.next = "WAIT-FOR-ACK"
            with m.State("WAIT-FOR-ACK"):
                m.d.comb += self.par_bus.par_stb.eq(1)
                with m.If(self.par_bus.par_ack):
                    m.next = "WAIT-FOR-DATA"
            with m.State("WAIT-FOR-DATA"):
                with m.If(~self.par_bus.par_ack & self.in_fifo.w_rdy):
                    m.d.comb += [
                        self.in_fifo.w_en.eq(1),
                        self.in_fifo.w_data.eq(self.par_bus.di),
                    ]
                    m.next = "IDLE"

        return m


class SaturnProActionReplayApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "Sega Saturn Pro Action Replay tool"
    description = """
    TODO
    """

    __pin_sets = ("d")
    __pins = ("par_stb", "par_ack")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "d", width=8, default=True)
        access.add_pin_argument(parser, "par_stb", default=True)
        access.add_pin_argument(parser, "par_ack", default=True)


    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(ProActionReplaySubtarget(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
        ))
        return subtarget

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)


    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            write_buffer_size=128)

        # binfile = open('SL.BIN', 'rb')
        # binfile.seek(0, 2)
        # binlen = binfile.tell()
        # binfile.seek(0)

        binfile = open('satdump.bin', 'wb')

        await iface.write(b"IN")
        res = await iface.read(2)
        print(bytes(res))

        await iface.write(struct.pack(">BLLL", 0x01, 0, 0x06002000, 0x1000))
        res = await iface.read(13)
        print(bytes(res))

        zero_chunk = b'\x00'

        for i in range(0x1000):
            await iface.write(zero_chunk)
            binfile.write(await iface.read(1))

        binfile.close()

        await iface.write(struct.pack(">LLBB", 0, 0, 0, 0))
        res = await iface.read(10)
        print(bytes(res))


# -------------------------------------------------------------------------------------------------

# class AudioYamahaOPxAppletTestCase(GlasgowAppletTestCase, applet=AudioYamahaOPxApplet):
#     @synthesis_test
#     def test_build_opl2(self):
#         self.assertBuilds(args=["--device", "OPL2"])

#     @synthesis_test
#     def test_build_opl3(self):
#         self.assertBuilds(args=["--device", "OPL3"])

#     @synthesis_test
#     def test_build_opm(self):
#         self.assertBuilds(args=["--device", "OPM"])
