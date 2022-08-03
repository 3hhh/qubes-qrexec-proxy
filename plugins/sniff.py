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
import base64

#import the plugin base class
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(1, PLUGIN_DIR)
from plugins import QrexecProxyPlugin
from plugins import read_noblock
from plugins import write_noblock
from plugins import flush_noblock
from plugins import READ_BUF_SIZE

class QrexecProxyPlugin_sniff(QrexecProxyPlugin):
    '''
    Passively sniffes all qrexec traffic and logs it via the qrexec-proxy logger (usually to the systemd journal).

    Configuration parameters:
    `decode`:   How to print the binary data in the logs. Available: hex|base64|string (default: base64)
                WARNING: Decoding to strings may
                    a) allow the sending VM to exploit potential security vulnerabilities in the Python decoder or
                       the systemd journal.
                    b) be incomplete or faulty as not all data was read yet.
                    c) result in useless garbage for binary data.
    `encoding`: String encoding to use (default: utf-8), if `decode` == 'string'.
    '''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config=config)
        self.decode = self.config.get('decode', 'base64')
        self.encoding = self.config.get('encoding', 'utf-8')
        if self.decode == 'base64':
            self.decode_func = self.decode_base64
        elif self.decode == 'hex':
            self.decode_func = self.decode_hex
        elif self.decode == 'string' or self.decode == 'str':
            self.decode_func = self.decode_str
        else:
            raise RuntimeError(f'Unsupported decode parameter value: {self.decode}')

    def decode_base64(self, buf):
        return base64.b64encode(buf).decode(encoding='ascii')

    def decode_hex(self, buf):
        return buf.hex()

    def decode_str(self, buf):
        return buf.decode(encoding=self.encoding, errors='backslashreplace')

    def log(self, buf_str: str, src2dst: bool):
        meta = self.meta
        if src2dst:
            src = meta['src']
            dst = meta['dst']
        else:
            src = meta['dst']
            dst = meta['src']

        self.logger.info('(data:%s:%s) %s -> %s: %s' % (
            meta['chain'],
            meta['qrexec'],
            src,
            dst,
            buf_str ))

    async def connect_sniff(self, reader, writer, src2dst: bool):
        try:
            while True:
                buf = await read_noblock(reader, size=READ_BUF_SIZE)

                if len(buf) == 0: #EOF
                    break

                buf_str = self.decode_func(buf)
                self.log(buf_str, src2dst)
                await write_noblock(writer, buf, flush=False)
        finally:
            await flush_noblock(writer)
            self.logger.debug(f'closing {reader} {writer}')
            reader.close()
            writer.close()

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await asyncio.gather(
            self.connect_sniff(src_r, dst_w, True),
            self.connect_sniff(dst_r, src_w, False))
