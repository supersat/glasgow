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

from ....support.arepl import *
from ....gateware.pads import *
from ....gateware.clockgen import *
from ....protocol.vgm import *
from ... import *


class ProActionReplayBus(Elaboratable):
    def __init__(self, pads):
        self.pads = pads

        self.di = Signal(8)
        self.resycned_di = Signal(8)
        self.do = Signal(8)

        self.par_stb = Signal()
        self.par_ack = Signal()


    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.pads.par_stb_t.o.eq(self.par_stb),
            self.pads.par_stb_t.oe.eq(1),
            self.pads.d_t.oe.eq(~self.par_ack),
            self.pads.d_t.o.eq(self.do)
        ]

        m.submodules += [
            FFSynchronizer(self.pads.par_ack_t.i, self.par_ack),
            FFSynchronizer(self.pads.d_t.i, self.resycned_di)
        ]
        
        with m.If(self.par_ack):
            m.d.sync += [
                self.di.eq(self.resycned_di),
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
                    m.next = "STB-DELAY-0"
            with m.State("STB-DELAY-0"):
                m.next = "STB-DELAY-1"
            with m.State("STB-DELAY-1"):
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


class SaturnProActionReplayInterface:
    def __init__(self, lower):
        self.lower = lower

    async def _sync(self):
        await self.lower.write(b"IN")
        res = await self.lower.read(2)
        assert res == b"DO"

    async def _begin_dump_mem(self, start_addr, length):
        await self.lower.write(struct.pack(">BL", 0x01, 0))
        res = await self.lower.read(5)
        # If the Pro Action Replay is in the menu, it will reject the memory dump request
        assert res != struct.pack(">L", 0x200000)
        await self.lower.write(struct.pack(">LL", start_addr, length))
        await self.lower.read(8)
        
    async def _end_dump_mem(self):
        await self.lower.write(struct.pack(">BLLBB", 0, 0, 0, 0, 0))
        res = await self.lower.read(11)
        assert res[-2:] == b"OK"
        return res[0]

    async def _read_bulk_bytes(self, length):
        zero_chunk = b'\x00' * length
        await self.lower.write(zero_chunk)
        return await self.lower.read(length)

    async def _begin_mem_upload(self,start_addr, length, execute):
        await self.lower.write(struct.pack(">BLLB", 0x09, start_addr, length, 1 if execute else 0))
        res = await self.lower.read(10)

    async def _write_bulk_bytes(self, bytes):
        await self.lower.write(bytes)
        return await self.lower.read(len(bytes))

    async def dump_mem(self, address, length):
        await self._sync()
        await self._begin_dump_mem(address, length)
        buf = b""
        while length > 0:
            if length > 128:
                dump_len = 128
            else:
                dump_len = length
            buf += await self._read_bulk_bytes(dump_len)
            length -= dump_len
        chksum = await self._end_dump_mem()
        assert chksum == sum(buf) & 0xff
        return buf
    
    async def upload_executable(self, address, data, execute):
        length = len(data)
        await self._sync()
        await self._begin_mem_upload(address, length, execute)
        idx = 0
        while idx < length:
            if length - idx > 128:
                xfer_len = 128
            else:
                xfer_len = length - idx
            self.logger.info(f"Writing {xfer_len} bytes at {idx}")
            await self._write_bulk_bytes(data[idx:idx + xfer_len])
            idx += xfer_len
    
    

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
        return iface
   
    async def repl(self, device, args, iface):
        iface = SaturnProActionReplayInterface(iface)
        self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
        await AsyncInteractiveConsole(locals={"device":device, "iface":iface, "args":args},
            run_callback=device.demultiplexer.flush).interact()

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
