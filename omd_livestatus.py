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
import os
import sys
import optparse                         # Legacy ... 2.6 still out there
import socket

try:
    import json
except ImportError:
    import simplejson as json


class OMDLivestatusInventory(object):

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
        self.build_inventory_by_ip()

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
        parser.add_option('--list', action='store_true', 
                          dest='list', default=False)
        parser.add_option('--host', type='string',
                          dest='host', default=None)
        parser.add_option('--socket', type='string',
                          dest='socket', default=None)
        parser.add_option('--to-static', action='store_true',
                          dest='static', default=False)
        self.opts, _ = parser.parse_args()

        # Make --list default if no other command is specified.
        if not self.opts.host:
            self.opts.list = True

    def load_from_omd(self):
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
        inventory = {}
        hostvars = {}
        for host in self.data['hosts']:
            for group in host['groups'] or ['_NOGROUP']:
                if group in inventory:
                    inventory[group].append(host['ip'])
                else:
                    inventory[group] = [host['ip']]
            hostvars[host['ip']] = {
                'omd_name': host['name'],
                'omd_alias': host['alias'],
            }
        self.inventory = inventory
        self.inventory['_meta'] = {
            'hostvars': hostvars
        }

    def print_static_inventory(self):
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
