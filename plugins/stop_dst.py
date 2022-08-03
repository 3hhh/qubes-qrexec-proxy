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

from plugins.byte_limit import QrexecProxyPlugin_byte_limit

class QrexecProxyPlugin_stop_dst(QrexecProxyPlugin_byte_limit):
    '''A convenience plugin to only allow one-way communication from the source to the destination / stop communication from the destination.'''

    def __init__(self, logger, meta, config=None):
        super().__init__(logger, meta, config={'src2dst_limit': -1, 'dst2src_limit': 0})
