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

import io
import asyncio
import logging
from abc import ABC, abstractmethod
from systemd.journal import JournalHandler

#standard read buffer size in bytes used in this file
READ_BUF_SIZE=1024*1024

def get_logger(name=None):
    if name:
        ename = '_'.join(['qrexec-proxy', name])
    else:
        ename = 'qrexec-proxy'
    logging.basicConfig(handlers=[])
    log = logging.getLogger(ename)
    #NOTE: We must NOT write to stdout or stderr as that might reach the source VM.
    log.propagate = False
    if not log.hasHandlers():
        log.addHandler(JournalHandler())
    log.setLevel(logging.DEBUG)
    return log

async def read_full_noblock(reader: io.IOBase, size=-1):
    ''' Read from the given non-blocking reader until at least size bytes are read or EOF is reached.
    :param reader: A non-blocking io.IOBase object to read from.
    :param size: Number of bytes to read. -1 (default) reads until EOF.
    :return: Exactly size bytes of data read from the reader. If less is returned, EOF was reached.
    '''
    chunks = []
    l = size
    while True:
        chunk = await read_noblock(reader, size=l)
        if len(chunk) == 0:
            break
        chunks.append(chunk)
        if size > 0:
            l = l - len(chunk)
    return b''.join(chunks)

async def discard_noblock(reader: io.IOBase, close=True):
    ''' Discard all data from the given non-blocking reader until EOF is reached.
    :param reader: A non-blocking io.IOBase object to read from.
    :param close: Whether to close after reading everything.
    :return: Nothing.
    '''
    try:
        while True:
            chunk = await read_noblock(reader, size=READ_BUF_SIZE)
            if len(chunk) == 0:
                break
    finally:
        if close:
            logger = get_logger('discard_noblock')
            logger.debug(f'closing {reader}')
            reader.close()

async def read_noblock(reader: io.IOBase, size=-1):
    ''' Read from the given non-blocking reader until some data is retrieved or EOF is reached.
    :param reader: A non-blocking io.IOBase object to read from.
    :param size: Maximum number of bytes to read. -1 (default) reads as much as possible, but not necessarily all.
    :return: Read data. If the length of that data is 0, EOF was reached.
    '''
    #logger = get_logger('read_noblock')
    while True:
        data = None
        try:
            #some implementations return None, some throw a BlockingIOError on potential blocks
            data = reader.read(size)
            #logger.debug(f'{reader} read: {data}')
        except BlockingIOError:
            #logger.debug(f'read_noblock: received blockingioerror for: {data}')
            pass

        if data is None:
            await asyncio.sleep(0)
            continue

        break
    return data

async def flush_noblock(writer: io.IOBase):
    ''' Flush the given non-blocking writer until all data is flushed or some exception occurs. '''
    while True:
        try:
            writer.flush()
            break
        except BlockingIOError:
            await asyncio.sleep(0)

async def write_noblock(writer: io.IOBase, b, flush=True):
    ''' Write to the given non-blocking writer until all data is written or some exception occurs.
    :param reader: A non-blocking io.IOBase object to write to.
    :param b: Bytes to write.
    :param flush: Whether to flush after the write.
    :return: Nothing. Will only return once everything was written.
    '''
    #logger = get_logger('write_noblock')
    to_write = memoryview(b)

    while True:
        try:
            #some implementations return None, some throw a BlockingIOError on potential blocks
            l = writer.write(bytes(to_write))
            l = l or 0
        except BlockingIOError as e:
            l = e.characters_written or 0
            #logger.debug(f'write_noblock: received blockingioerror and len {l} for: {to_write}')

        if flush and l > 0:
            await flush_noblock(writer)

        #logger.debug(f'{writer} wrote: {l} bytes of {b}')

        if l == len(to_write):
            return

        to_write = to_write[l:]
        await asyncio.sleep(0)

async def connect_noblock(reader: io.IOBase, writer: io.IOBase, close=True, size=-1):
    ''' Connect the two given non-blocking file objects by reading from the first and writing to the second.
    :param reader: A non-blocking io.IOBase object to read from.
    :param writer: A non-blocking io.IOBase object to read from.
    :param close: Whether or not to close the reader and writer in the end.
    :param size: Maximum number of bytes to transfer. Default: -1 / infinite
    :return: Nothing. Will only return once everything was written.
    '''
    rsize = size

    try:
        while rsize != 0:
            if rsize == -1:
                buf = await read_noblock(reader, size=READ_BUF_SIZE)
            elif rsize > READ_BUF_SIZE:
                buf = await read_noblock(reader, size=READ_BUF_SIZE)
                rsize = rsize - len(buf)
            else:
                buf = await read_noblock(reader, size=rsize)
                rsize = rsize - len(buf)
                if rsize < 0:
                    raise RuntimeError(f'Unexpected remaining size to read from {reader}: {rsize}')

            if len(buf) == 0: #EOF
                break

            await write_noblock(writer, buf, flush=False)
    finally:
        await flush_noblock(writer)
        if close:
            logger = get_logger('connect_noblock')
            logger.debug(f'closing {reader} {writer}')
            reader.close()
            writer.close()


class QrexecProxyPlugin(ABC):
    '''
    Base class for plugins to inherit from.

    In addition they must use a class name equal to `QrexecProxyPlugin_[plugin name]` to be scheduled
    by the qrexec-proxy.
    '''

    def __init__(self, logger, meta, config=None):
        ''' Constructor.
        :param logger: A logger object to use for logging.
        :param meta: A metadata dict with information about the current connection.
        :param config: A dict with configuration options supplied by the user.
        '''
        self.logger = logger
        self.meta = meta
        self.config = config
        if not self.config:
            self.config = dict()

    @abstractmethod
    async def proxy(self, src_r: io.IOBase, src_w: io.IOBase, dst_r: io.IOBase, dst_w: io.IOBase):
        '''
        Proxy data between a sender (either the source VM or another plugin)
        and a receiver (either the target VM or another plugin).

        qrexec is bidirectional, i.e. there's two file descriptors per participant.

        The file descriptors are non-blocking.

        Implementations are expected to close the file descriptors as soon as they are done.
        Otherwise they will be closed after this function returns.

        Unhandled exceptions will abort the qrexec connection.

        :param src_r:  Readable binary file descriptor to receive data from the source.
        :param src_w:  Writable binary file descriptor to send data to the source.
        :param dst_r:  Readable binary file descriptor to receive data from the destination.
        :param dst_w:  Writable binary file descriptor to send data to the destination.
        :return: Nothing.
        '''
