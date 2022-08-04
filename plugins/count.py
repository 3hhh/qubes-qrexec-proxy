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
import errno
import fcntl
import time
from plugins import QrexecProxyPlugin
from plugins import AbortException
from plugins import connect_noblock

class SysLock:
    ''' System wide async lock:
        The idea is to os.mkdir() a file to *.lock/ and only write it afterwards.
        This should work as os.mkdir() is atomic on POSIX systems.
    '''
    def __init__(self, file_path):
        self.file_path = file_path
        self.lock_path = '.'.join([file_path, 'lock'])
        self.fd = None

    async def wait_for_lock(self):
        while True:
            try:
                os.mkdir(self.lock_path)
                break
            except FileExistsError as e:
                await asyncio.sleep(0.2)

    async def __aenter__ (self):
        await self.wait_for_lock()
        #a+: open for reading & writing, don't truncate, create new file as needed
        self.fd = open(self.file_path, 'a+')
        return self

    async def __aexit__ (self, _exc_type, _exc, _tb):
        os.rmdir(self.lock_path)
        self.fd.close()
        self.fd = None

class QrexecProxyPlugin_count(QrexecProxyPlugin):
    '''
    Counts how often a proxy plugin chain was used and may abort it, if the amount exceeds a user-supplied value.

    Logs will usually show an `AbortException` or a `BrokenPipeError`.

    Configuration parameters:
    `limit`: Acceptable number of times to use this plugin chain within the `limit_interval`.
    `limit_interval`: Time in seconds during which the `limit` may not be overstepped.
    `state_dir`: Directory where this plugin manages its state. Non-existing directories are created.
                 Default: `[qrexec-proxy plugin directory]/state/count/`.
    '''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config=config)
        try:
            self.limit = int(self.config['limit'])
            self.limit_interval = float(self.config['limit_interval'])
        except (KeyError, ValueError) as e:
            raise RuntimeError('Please configure the limit and limit_interval parameters in the config.json.') from e

        if self.limit <= 0:
            raise RuntimeError('The limit parameter must be > 0.')
        if self.limit_interval <= 0:
            raise RuntimeError('The limit_interval parameter must be > 0.')

        self.state_dir = self.config.get('state_dir')
        if not self.state_dir:
            self.state_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'state/count/')
        self.logger.debug(f'state dir: {self.state_dir}')
        os.makedirs(self.state_dir, exist_ok=True)

    def update_counters(self, fd):
        '''
        Update the counters in the given file descriptor.
        Raises an exception, if the counter is too high.
        '''
        #file format: a line of [unix timestamp] for every connection
        cnt = 0
        now = int(time.time())
        out = []
        fd.seek(0)
        for line in fd.read().splitlines():
            otime = int(line)
            self.logger.debug(f'old time found: {otime}')
            if now - otime < self.limit_interval:
                cnt = cnt + 1
                out.append(str(otime))
        try:
            if cnt >= self.limit:
                raise AbortException('The connection limit of %d was reached for the chain %s.' % (self.limit, self.meta['chain']))
            out.append(str(now))
        finally:
            fd.seek(0)
            fd.truncate()
            fd.write('\n'.join(out))
            self.logger.debug(f'counters updated: {out}')

    async def check_count(self):
        '''
        Checks and updates the internal counter for a qrexec connection.
        Throws an exception, if the connection should be aborted.
        '''
        count_file = os.path.join(self.state_dir, self.meta['chain'])
        async with SysLock(count_file) as lock:
            self.update_counters(lock.fd)

    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        await self.check_count()
        await asyncio.gather(
            connect_noblock(src_r, dst_w),
            connect_noblock(dst_r, src_w))
