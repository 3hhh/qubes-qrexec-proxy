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
from plugins import QrexecProxyPlugin
from plugins import connect_noblock
from plugins import discard_noblock

class QrexecProxyPlugin_byte_limit(QrexecProxyPlugin):
    '''
    A plugin to limit the number of bytes sent in one direction or another. Additional data will be read, but discarded.

    Configuration parameters:
    `src2dst_limit`: Number of bytes that may be sent from the qrexec source to the qrexec destination. -1 = infinite
    `dst2src_limit`: Number of bytes that may be sent from the qrexec destination to the qrexec source. -1 = infinite
    '''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config=config)
        try:
            self.src2dst_limit = int(self.config['src2dst_limit'])
            self.dst2src_limit = int(self.config['dst2src_limit'])
        except (KeyError, ValueError) as e:
            raise RuntimeError('Please configure the src2dst_limit and dst2src_limit bytes in the config.json.') from e

    async def connect_then_discard(self, src, dst, size):
        await connect_noblock(src, dst, size=size, close=False)
        self.logger.debug(f'closing {dst}')
        dst.close()
        await discard_noblock(src)

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await asyncio.gather(
            self.connect_then_discard(src_r, dst_w, self.src2dst_limit),
            self.connect_then_discard(dst_r, src_w, self.dst2src_limit))
