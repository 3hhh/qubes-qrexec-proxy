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

class QrexecProxyPlugin_timeout(QrexecProxyPlugin):
    '''
    This plugin causes connections to end once a time limit is reached.

    Logs will usually show a `TimeoutError` or a `BrokenPipeError`.

    Please note that a timeout alone won't stop a compromised VM from opening further qrexec connections. You might want
    to consider using other plugins to stop it from doing that.

    Configuration parameters:
    `src2dst_timeout`: Number of seconds before the timeout hits in for the source to destination direction. -1 = infinite
    `dst2src_timeout`: Number of seconds before the timeout hits in for the destination to source direction. -1 = infinite
    '''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config=config)
        try:
            self.src2dst_timeout = float(self.config['src2dst_timeout'])
            self.dst2src_timeout = float(self.config['dst2src_timeout'])
        except (KeyError, ValueError) as e:
            raise RuntimeError('Please configure the src2dst_timeout and dst2src_timeout seconds in the config.json.') from e

        if self.src2dst_timeout < 0:
            self.src2dst_timeout = None
        if self.dst2src_timeout < 0:
            self.dst2src_timeout = None

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await asyncio.gather(
            asyncio.wait_for(connect_noblock(src_r, dst_w), self.src2dst_timeout),
            asyncio.wait_for(connect_noblock(dst_r, src_w), self.dst2src_timeout))
        #if this throws an Exception, qrexec-proxy will cancel everything
