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
import sys
from plugins import QrexecSourcePlugin
from plugins import QrexecDestinationPlugin
from plugins import connect_noblock
from plugins import open_single_pipe

class QrexecSourcePlugin_default(QrexecSourcePlugin):
    '''
    The implicit default source plugin.

    Reads from `sys.stdin` and writes to `sys.stdout`,
    i.e. the default `qrexec` communication channels.
    '''

    async def communicate_src(self, src_r: io.IOBase, src_w: io.IOBase):
        '''
        Read `sys.stdin` and write `sys.stdout` to communicate with the source VM.

        :param src_r: Async pipe to read.
        :param src_w: Async pipe to write.
        '''
        try:
            stdin = open_single_pipe(0, 'rb')
            stdout = open_single_pipe(1, 'wb')
            await asyncio.gather(
                connect_noblock(stdin, src_w),
                connect_noblock(src_r, stdout))
        finally:
            self.logger.debug(f'closing {src_r} {src_w} {stdin} {stdout}')
            src_r.close()
            src_w.close()
            stdin.close()
            stdout.close()
            self.logger.debug('default communicate_src(): returned')

class QrexecDestinationPlugin_default(QrexecDestinationPlugin):
    '''
    The implicit default destination plugin.

    Creates a `qrexec` communication channel to the VM passed via the
    `meta` attribute.
    '''

    async def communicate_dst(self, dst_r: io.IOBase, dst_w: io.IOBase):
        '''
        Start a qrexec connection to communicate with the destination VM.

        :param dst_r: Async pipe to read.
        :param dst_w: Async pipe to write.
        '''
        try:
            #NOTE: we redirect stderr to sys.stderr, knowing that the qrexec-proxy script will redirect it locally (otherwise stderr would go to the sending VM)
            proc = await asyncio.create_subprocess_exec('/usr/lib/qubes/qrexec-client-vm', self.meta['dst'], self.meta['qrexec'], stdin=dst_r, stdout=dst_w, stderr=sys.stderr)
            ret = await proc.wait()
        finally:
            self.logger.debug(f'closing {dst_r} {dst_w}')
            dst_r.close()
            dst_w.close()
        if ret != 0:
            raise RuntimeError('A non-zero exit code %d was returned by qrexec-client-vm. Maybe Qubes OS disallowed the qrexec request?' % ret)
        self.logger.debug('default communicate_destination(): returned')
