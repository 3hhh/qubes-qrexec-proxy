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
from plugins import QrexecSourcePlugin
from plugins import QrexecDestinationPlugin
from plugins import QrexecProxyPluginException
from plugins import get_logger
from plugins import open_pipe

LOG = get_logger()

class PluginLoadFailedException(QrexecProxyPluginException):
    ''' Raised when a plugin load operation fails. '''

def error_out(msg):
    LOG.error(msg)
    sys.exit(1)

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

def load_plugin(plugin, cls):
    plugin_file = ''.join([PLUGIN_DIR, '/', plugin, '.py'])
    try:
        spec = importlib.util.spec_from_file_location(PLUGIN_DIR_NAME + '.' + plugin, plugin_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except FileNotFoundError as e:
        raise PluginLoadFailedException('Could not load the plugin %s from the file %s. Does it not exist?' % (plugin, plugin_file)) from e

    ret = None
    cls_name = '_'.join([cls.__name__, plugin])
    for _, member in inspect.getmembers(module, inspect.isclass):
        if member.__name__ == cls_name and issubclass(member, cls):
            ret = member
            break
    if not ret:
        raise PluginLoadFailedException(f'The plugin {plugin} appears to be incorrectly implemented. No matching class {cls_name} found.')
    return ret

def instantiate_plugin(plugin, plugin_cls, chain, chain_conf=None, conf_index=0, meta=None):
    pconf = None
    if chain_conf:
        #try index first (useful if the same plugin is used multiple times in a chain), plugin name second
        try:
            pconf = chain_conf[conf_index]
        except KeyError:
            pconf = chain_conf.get(plugin)

    LOG.debug(f'Instantiating a {plugin_cls} object...')
    lname = '_'.join([chain, plugin, str(conf_index)])
    return plugin_cls(get_logger(lname), meta, config=pconf)

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

    #load source plugin
    user_plugin = False
    try:
        src_plugin = plugins[0]
        user_plugin = True
    except IndexError:
        src_plugin = 'default'

    try:
        src_plugin = load_plugin(src_plugin, QrexecSourcePlugin)
        if user_plugin:
            plugins.pop(0)
    except PluginLoadFailedException:
        src_plugin = load_plugin('default', QrexecSourcePlugin)

    #load destination plugin
    user_plugin = False
    try:
        dst_plugin = plugins[-1]
        user_plugin = True
    except IndexError:
        dst_plugin = 'default'

    try:
        dst_plugin = load_plugin(dst_plugin, QrexecDestinationPlugin)
        if user_plugin:
            plugins.pop(-1)
    except PluginLoadFailedException:
        dst_plugin = load_plugin('default', QrexecDestinationPlugin)

    #instantiate src_plugin & dst_plugin
    chain_conf = conf.get(chain).get('config')
    src_plugin = instantiate_plugin('src_plugin', src_plugin, chain, chain_conf=chain_conf, conf_index=0,  meta=meta)
    dst_plugin = instantiate_plugin('dst_plugin', dst_plugin, chain, chain_conf=chain_conf, conf_index=-1, meta=meta)
    LOG.debug(f'src_plugin: {src_plugin}')
    LOG.debug(f'dst_plugin: {dst_plugin}')

    #load proxy plugins: load first class named QrexecProxyPlugin_[plugin] and inheriting from QrexecProxyPlugin
    loaded_plugins = dict()
    for plugin in plugins:
        if loaded_plugins.get(plugin):
            continue
        cls = load_plugin(plugin, QrexecProxyPlugin)
        loaded_plugins[plugin] = cls
    LOG.debug('Loaded plugins: %s' % loaded_plugins)

    #connect source VM
    #NOTE: whatever is written to the *_w part will appear at the *_r part, that's why it's _one_ pipe
    src_r, src_w = open_pipe()
    dst_r, dst_w = open_pipe()
    awaitables = [ src_plugin.communicate_src(dst_r, src_w) ]

    #connect plugins
    for i, plugin in enumerate(plugins):
        cls = loaded_plugins[plugin]
        obj = instantiate_plugin(plugin, cls, chain, chain_conf=chain_conf, conf_index=i, meta=meta)

        r1, w1 = open_pipe()
        r2, w2 = open_pipe()
        awaitables.append(proxy_wrapper(obj, src_r, dst_w, r1, w2))

        src_r = r2
        dst_w = w1

    #connect destination VM
    awaitables.append(dst_plugin.communicate_dst(src_r, dst_w))

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
