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

'''
Intransparent and modular Qubes OS qrexec proxy.

Only works in Linux VMs.

Requires python-systemd [1]. Install via e.g. `apt install python3-systemd`.

[1] https://www.freedesktop.org/software/systemd/python-systemd/
'''

import sys
import os
import json
import asyncio
import inspect
import importlib.util

#globals
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PLUGIN_DIR_NAME = 'plugins'
PLUGIN_DIR = os.path.join(SCRIPT_DIR, PLUGIN_DIR_NAME)
CONF_FILE = os.path.join(PLUGIN_DIR, 'config.json')

#import the plugin base class
sys.path.insert(1, PLUGIN_DIR)
from plugins import QrexecProxyPlugin
from plugins import connect_noblock
from plugins import get_logger
LOG = get_logger()

def error_out(msg):
    LOG.error(msg)
    sys.exit(1)

async def communicate_destination(dst_vm, qrexec, r_pipe, w_pipe):
    '''
    Start a qrexec connection to communicate with the destination VM.

    :param r_pipe: Async pipe to read.
    :param w_pipe: Async pipe to write.
    '''
    try:
        #NOTE: we redirect stderr to sys.stderr, knowing that the qrexec-proxy script will redirect it locally (otherwise stderr would go to the sending VM)
        proc = await asyncio.create_subprocess_exec('/usr/lib/qubes/qrexec-client-vm', dst_vm, qrexec, stdin=r_pipe, stdout=w_pipe, stderr=sys.stderr)
        ret = await proc.wait()
    finally:
        r_pipe.close()
        w_pipe.close()
    if ret != 0:
        raise RuntimeError('A non-zero exit code %d was returned by qrexec-client-vm. Maybe Qubes OS disallowed the qrexec request?' % ret)
    LOG.debug('communicate_destination(): returned')

async def communicate_source(r_pipe, w_pipe):
    '''
    Read `sys.stdin` and write `sys.stdout` to communicate with the source VM.

    :param r_pipe: Async pipe to read.
    :param w_pipe: Async pipe to write.
    '''
    try:
        stdin = open_single_pipe(0, 'rb')
        stdout = open_single_pipe(1, 'wb')
        await asyncio.gather(
            connect_noblock(stdin, w_pipe),
            connect_noblock(r_pipe, stdout))
    finally:
        r_pipe.close()
        w_pipe.close()
        stdin.close()
        stdout.close()
        LOG.debug('communicate_source(): returned')

def open_single_pipe(pipe, mode):
    if not isinstance(pipe, int):
        raise RuntimeError('Pipes should be identified by integers. Found: %s' % type(pipe))
    #NOTES:
    # - pipes are identified by integers
    # - pipes always come in pairs - one sending end (w) and one receiving end (r), data goes from w to r --> a pipe is unidirectional
    # - fdopen() returns some io.IOBase object
    # - we need os.O_NONBLOCK as even asyncio will block to pipes otherwise (btw it also blocks to file operations)
    os.set_blocking(pipe, False)
    ret = os.fdopen(pipe, mode)
    LOG.debug(f'opened {ret}')
    return ret

def open_pipe():
    r, w = os.pipe()
    r = open_single_pipe(r, 'rb')
    w = open_single_pipe(w, 'wb')
    return (r, w)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    LOG.error('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

async def proxy_wrapper(proxy, *pipes):
    try:
        await proxy.proxy(*pipes)
    finally:
        for pipe in pipes:
            pipe.close()

async def main():
    #never let any unhandled exceptions slip to stdout or stderr (and thus the source VM)
    sys.excepthook = handle_exception

    source_vm = os.environ.get('QREXEC_REMOTE_DOMAIN')
    if not source_vm:
        error_out('Failed to identify the source VM.')

    if len(sys.argv) != 2:
        error_out('Unexpected number of arguments. Expected: [plugin chain]+[qrexec destination vm]+[qrexec call]')
    args = sys.argv[1].split('+') #Qubes OS always splits qrexec calls by +, so we do that here, too
    if len(args) != 3:
        error_out('Unexpected number of arguments. Expected: [plugin chain]+[qrexec destination vm]+[qrexec call]')
    chain = args[0]
    destination_vm = args[1]
    qrexec = args[2]
    meta = {
        'chain': chain,
        'src': source_vm,
        'dst': destination_vm,
        'qrexec': qrexec,
    }

    LOG.info('Starting %s --> %s: %s via chain %s...' % (source_vm, destination_vm, qrexec, chain))

    #load config
    with open(CONF_FILE, encoding='utf-8') as json_file:
        conf = json.load(json_file)
    if not isinstance(conf, dict):
        error_out('The configuration file %s needs to define a dict of [plugin chain] --> plugins: [ordered list of plugins].' % CONF_FILE)
    plugins = conf.get(chain).get('plugins')
    if not isinstance(plugins, list):
        error_out('The chain %s was not found inside the configuration file %s. You need to define a dict of [plugin chain] --> plugins: [ordered list of plugins].' % (chain, CONF_FILE))

    #load plugins: load first class named QrexecProxyPlugin_[plugin] and inheriting from QrexecProxyPlugin
    loaded_plugins = dict()
    for plugin in plugins:
        if loaded_plugins.get(plugin):
            continue

        plugin_file = ''.join([PLUGIN_DIR, '/', plugin, '.py'])
        try:
            spec = importlib.util.spec_from_file_location(PLUGIN_DIR_NAME + '.' + plugin, plugin_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except FileNotFoundError:
            error_out('Could not load the plugin %s from the file %s. Does it not exist?' % (plugin, plugin_file))

        cls = None
        cls_name = ''.join(['QrexecProxyPlugin_', plugin])
        for _, member in inspect.getmembers(module, inspect.isclass):
            if member.__name__ == cls_name and issubclass(member, QrexecProxyPlugin):
                cls = member
                break
        if not cls:
            error_out(f'The plugin %s appears to be incorrectly implemented. No matching class {cls_name} found.' % plugin)

        loaded_plugins[plugin] = { 'module': module, 'class': cls }
    LOG.debug('Loaded plugins: %s' % loaded_plugins)

    #connect source VM
    #NOTE: whatever is written to the *_w part will appear at the *_r part, that's why it's _one_ pipe
    src_r, src_w = open_pipe()
    dst_r, dst_w = open_pipe()
    awaitables = [ communicate_source(dst_r, src_w) ]

    #connect plugins
    for i, plugin in enumerate(plugins):
        cls = loaded_plugins[plugin]['class']
        lname = '_'.join([chain, plugin, str(i)])
        pconf = conf.get(chain).get('config') #chain config
        if pconf:
            #try index first (useful if the same plugin is used multiple times in a chain), plugin name second
            try:
                pconf = pconf[str(i)]
            except KeyError:
                pconf = pconf.get(plugin)
        LOG.debug(f'cls: {cls}')
        obj = cls(get_logger(lname), meta, config=pconf)

        r1, w1 = open_pipe()
        r2, w2 = open_pipe()
        awaitables.append(proxy_wrapper(obj, src_r, dst_w, r1, w2))

        src_r = r2
        dst_w = w1

    #connect destination VM
    awaitables.append(communicate_destination(destination_vm, qrexec, src_r, dst_w))

    #run everything
    try:
        pending = []
        awaitables = [ task if isinstance(task, asyncio.Task) else asyncio.create_task(task) for task in awaitables ]
        done, pending = await asyncio.wait(awaitables, return_when=asyncio.FIRST_EXCEPTION)

        for task in done:
            if isinstance(task.result(), Exception):
                raise task.result()
        LOG.info('All done. Exiting...')
    finally:
        for task in pending:
            task.cancel()
        LOG.debug('Cleanup done.')

if __name__ == '__main__':
    asyncio.run(main())
