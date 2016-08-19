#!/usr/bin/env python
# -*- mode: python; coding: utf-8 -*-

u"""
OMD Livestatus dynamic inventory script
=======================================

If running as an OMD site user, i.e. if ${OMD_ROOT} is set, we try to
connect to the Livestatus socket at the default location

    ${OMD_ROOT}/tmp/run/live

Alternatively, the path to the Livestatus socket can be set from the
environment via

    export OMD_LIVESTATUS_SOCKET=/omd/sites/mysite/tmp/run/live

or on the command-line with --socket.


Inspired by the DigitalOcean inventory script:
https://github.com/ansible/ansible/blob/devel/contrib/inventory/digital_ocean.py

:author: Andreas Härpfer <andreas.haerpfer@consol.de>
"""

from __future__ import print_function

__version__ = '0.1'

import os
import sys
import optparse                         # Legacy ... 2.6 still out there
import socket

try:
    import json
except ImportError:
    import simplejson as json

try:
    maketrans = str.maketrans           # Python 3
except AttributeError:
    from string import maketrans        # Python 2


class OMDLivestatusInventory(object):

    #: string of bad characters in host or group names
    _bad_chars = '.,;:[] '

    #: replacement char for bad chars
    _replacement_char = '_'

    #: translation table for sanitizing group names
    _trans_table = maketrans(_bad_chars, _replacement_char * len(_bad_chars))

    # For Python 3 alternatively:
    #_trans_table = dict(zip(map(ord, _bad_chars),
    #                        _replacement_char * len(_bad_chars)))

    def __init__(self):
        self.data = {}
        self.inventory = {}

        self._read_cli_args()
        if not self.opts.socket:
            if 'OMD_LIVESTATUS_SOCKET' in os.environ:
                self.opts.socket = os.environ['OMD_LIVESTATUS_SOCKET']
            elif 'OMD_ROOT' in os.environ:
                self.opts.socket = os.environ['OMD_ROOT'] + '/tmp/run/live'
            else:
                print('Unable to determine Livestatus socket.')
                sys.exit(1)

        self.load_from_omd()
        if self.opts.by_ip:
            self.build_inventory_by_ip()
        else:
            self.build_inventory_by_name()

        if self.opts.static:
            self.print_static_inventory()
        elif self.opts.list:
            print(json.dumps(self.inventory, indent=4))
        elif self.opts.host:
            if self.opts.host in self.inventory['_meta']['hostvars']:
                print(json.dumps(
                    self.inventory['_meta']['hostvars'][self.opts.host],
                    indent=4
                ))
            else:
                print("{}")
        else:
            print('Missing command.')
            sys.exit(1)
        
    def _read_cli_args(self):
        parser = optparse.OptionParser()
        parser.add_option(
            '--list', action='store_true', dest='list', default=False,
            help='Return full Ansible inventory as JSON (default action).')
        parser.add_option(
            '--host', type='string', dest='host', default=None,
            help='Return Ansible hostvars as JSON.')
        parser.add_option(
            '--socket', type='string', dest='socket', default=None,
            help='Set path to Livestatus socket.')
        parser.add_option(
            '--by-ip', action='store_true', dest='by_ip', default=False,
            help='Create inventory by IP (instead of the default by name).')
        parser.add_option(
            '--to-static', action='store_true', dest='static', default=False,
            help='Print inventory in static file format to stdout.')
        self.opts, _ = parser.parse_args()

        # Make --list default if no other command is specified.
        if not self.opts.host:
            self.opts.list = True

    def load_from_omd(self):
        """Read data from livestatus socket and populate self.data['hosts'].

        """
        self.data['hosts'] = []
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.opts.socket)
        s.send('GET hosts\nColumns: address name alias groups\n')
        s.shutdown(socket.SHUT_WR)
        answer = s.recv(100000000)
        for line in answer.splitlines():
            fields = line.split(';')
            groups = [f.strip() for f in fields[3].split(',') if f]
            self.data['hosts'].append({
                'ip': fields[0],
                'name': fields[1],
                'alias': fields[2],
                'groups': groups,
            })

    def build_inventory_by_ip(self):
        """Wrap OMD data into an Ansible compatible inventory data structure.

        Hosts are identified by IP, group names are sanitized to not
        contain characters that Ansible can't digest.  In particular
        group names in Ansible must not contain blanks!

        """
        inventory = {}
        hostvars = {}
        for host in self.data['hosts']:
            for group in host['groups'] or ['_NOGROUP']:
                sanitized_group = group.translate(self._trans_table)
                if sanitized_group in inventory:
                    inventory[sanitized_group].append(host['ip'])
                else:
                    inventory[sanitized_group] = [host['ip']]
            hostvars[host['ip']] = {
                'omd_name': host['name'],
                'omd_alias': host['alias'],
            }
        self.inventory = inventory
        self.inventory['_meta'] = {
            'hostvars': hostvars
        }

    def build_inventory_by_name(self):
        """Create Ansible inventory by OMD name instead of by IP.

        """
        inventory = {}
        hostvars = {}
        for host in self.data['hosts']:
            for group in host['groups'] or ['_NOGROUP']:
                sanitized_group = group.translate(self._trans_table)
                if sanitized_group in inventory:
                    inventory[sanitized_group].append(host['name'])
                else:
                    inventory[sanitized_group] = [host['name']]
            hostvars[host['name']] = {
                'ansible_host': host['ip'],
                'omd_alias': host['alias'],
            }
        self.inventory = inventory
        self.inventory['_meta'] = {
            'hostvars': hostvars
        }

    def print_static_inventory(self):
        """Print out data in a format that can be used as a static inventory.

        """
        for group in [k for k in self.inventory.keys() if k != '_meta']:
            print('\n[{0}]'.format(group))
            for host in self.inventory[group]:
                vars = self.inventory['_meta']['hostvars'][host]
                hostvars = []
                for varname in vars.keys():
                    hostvars.append('{0}="{1}"'.format(varname, vars[varname]))
                print('{0}\t{1}'.format(host, ' '.join(hostvars)))


if __name__ == '__main__':
    OMDLivestatusInventory()
