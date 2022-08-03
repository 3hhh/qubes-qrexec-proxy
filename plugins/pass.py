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

class QrexecProxyPlugin_pass(QrexecProxyPlugin):
    ''' A plugin that just passes all data on. Useful for debugging only. '''

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await asyncio.gather(
            connect_noblock(src_r, dst_w),
            connect_noblock(dst_r, src_w))
