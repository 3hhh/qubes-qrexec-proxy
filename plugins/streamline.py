#!/usr/bin/env python3
# vim: fileencoding=utf-8
#
# Copyright (C) 2022
#                   David Hobach <tripleh@hackingthe.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import asyncio
import io
import os
import sys
import secrets

#import the plugin base class
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(1, PLUGIN_DIR)
from plugins import QrexecProxyPlugin
from plugins import read_full_noblock
from plugins import write_noblock
from plugins import flush_noblock

class QrexecProxyPlugin_streamline(QrexecProxyPlugin):
    '''
    Plugin to streamline data.

    Streamlining means that all incoming data is read to a buffer and only written once that buffer is full.
    The sender is blocked in the meantime. A random delay may be added before incoming data is written or read.

    The purpose of this is to make certain types of backpressure side channel attacks in one-way scenarios
    harder: E.g. assuming two compromised VMs A and B and a one-way qrexec channel between A --> B, B can
    easily use its capability to block the incoming data stream as a side channel to transmit data to A
    (e.g use 0.1s blocks as 0 and 0.2s blocks as 1).

    This plugin cannot fully mitigate that kind of attack, but it can limit the achievable data rates.
    Of course, this comes at the cost of lower data rates on the primary A --> B data stream.

    Configuration parameters:
    `buf_size`:    Buffer size in bytes (default: 1024*1024*10 = 10MB).
    `delay_read`:  Maximum time in seconds to wait before reading data from the sender.
                   The actual time may be between 0 and that maximum. Default: 0.5s
    `delay_write`: Maximum time in seconds to wait before sending data to the receiver.
                   The actual time may be between 0 and that maximum. Default: 0.5s
    '''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config=config)
        self.buf_size = int(self.config.get('buf_size', 1024*1024*10))
        self.delay_read = float(self.config.get('delay_read', 0.5))
        self.delay_write = float(self.config.get('delay_write', 0.5))

    async def sleep(self, max_delay: float):
        if max_delay == 0:
            return
        delay = secrets.randbelow(int(max_delay * 1000)) / 1000
        self.logger.debug(f'delay: {delay}, max: {max_delay}')
        await asyncio.sleep(delay)

    async def connect_streamline(self, reader, writer):
        try:
            i = 0
            while True:
                if i > 0:
                    await self.sleep(self.delay_read)
                buf = await read_full_noblock(reader, size=self.buf_size)
                if len(buf) == 0: #EOF & nothing to write
                    break
                await self.sleep(self.delay_write)
                await write_noblock(writer, buf, flush=False)
                if len(buf) < self.buf_size: #EOF
                    break
                i = i + 1
        finally:
            await flush_noblock(writer)
            self.logger.debug(f'closing {reader} {writer}')
            reader.close()
            writer.close()

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await asyncio.gather(
            self.connect_streamline(src_r, dst_w),
            self.connect_streamline(dst_r, src_w))
