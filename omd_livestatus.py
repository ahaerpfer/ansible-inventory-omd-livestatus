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

__version__ = '0.2'

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

    def __init__(self, location=None, method='socket', by_ip=False):
        self.data = {}
        self.inventory = {}

        if not location:
            if 'OMD_LIVESTATUS_SOCKET' in os.environ:
                self.location = os.environ['OMD_LIVESTATUS_SOCKET']
            elif 'OMD_ROOT' in os.environ:
                self.location = os.environ['OMD_ROOT'] + '/tmp/run/live'
            else:
                raise EnvironmentError(
                    'Unable to determine location of Livestatus socket.')
        else:
            self.location = location

        self.load_from_omd()
        if by_ip:
            self.build_inventory_by_ip()
        else:
            self.build_inventory_by_name()

    def load_from_omd(self):
        """Read host data from livestatus socket.

        Populates self.data['hosts'].

        """
        self.data['hosts'] = []
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.location)
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
        """Create Ansible inventory by IP address instead of by name.

        Cave: contrary to hostnames IP addresses are not guaranteed to
        be unique in OMD!  Since there is only one set of hostvars for a
        given IP, duplicate IPs might mean that you are loosing data.
        When creating static inventory output we issue a warning for
        duplicate IPs.  For the default JSON output this warning is
        suppressed since Ansible discards any output on STDERR.

        Group names are sanitized to not contain characters that Ansible
        can't digest.  In particular group names in Ansible must not
        contain blanks!

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
            # Detect duplicate IPs in inventory.  Keep first occurence
            # in hostvars instead of overwriting with later data.
            ip = host['ip']
            if ip not in hostvars:
                hostvars[ip] = {
                    'omd_name': host['name'],
                    'omd_alias': host['alias'],
                }
            #else:
            #    # duplicate IP
            #    pass
        self.inventory = inventory
        self.inventory['_meta'] = {
            'hostvars': hostvars
        }

    def build_inventory_by_name(self):
        """Create Ansible inventory by OMD name.

        Group names are sanitized to not contain characters that Ansible
        can't digest.  In particular group names in Ansible must not
        contain blanks!

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

    def list(self, indent=None, sort_keys=False):
        """Return full inventory data as JSON."""
        return json.dumps(self.inventory, indent=indent, sort_keys=sort_keys)

    def host(self, name, indent=None, sort_keys=False):
        """Return hostvars for a single host as JSON."""
        if name in self.inventory['_meta']['hostvars']:
            return(json.dumps(
                self.inventory['_meta']['hostvars'][name],
                indent=indent,
                sort_keys=sort_keys
            ))
        else:
            return("{}")

    def static(self):
        """Return data in static inventory format."""
        out = []
        for group in [k for k in self.inventory.keys() if k != '_meta']:
            out.append('\n[{0}]'.format(group))
            for host in self.inventory[group]:
                vars = self.inventory['_meta']['hostvars'][host]
                hostvars = []
                for varname in vars.keys():
                    hostvars.append('{0}="{1}"'.format(varname, vars[varname]))
                out.append('{0}\t{1}'.format(host, ' '.join(hostvars)))
        return '\n'.join(out)


def parse_arguments():
    """Parse command line arguments."""
    parser = optparse.OptionParser(version='%prog {0}'.format(__version__))
    output_group = optparse.OptionGroup(parser, 'Output formats')
    output_group.add_option(
        '--list', action='store_true', dest='list', default=False,
        help='Return full Ansible inventory as JSON (default action).')
    output_group.add_option(
        '--host', type='string', dest='host', default=None,
        help='Return Ansible hostvars for HOST as JSON.')
    output_group.add_option(
        '--static', action='store_true', dest='static', default=False,
        help='Print inventory in static file format to stdout.')
    output_group.add_option(
        '--by-ip', action='store_true', dest='by_ip', default=False,
        help='Create inventory by IP (instead of the default by name).')
    parser.add_option_group(output_group)

    connect_group = optparse.OptionGroup(parser, 'Connection options')
    connect_group.add_option(
        '--socket', type='string', dest='socket', default=None,
        help=('Set path to Livestatus socket.  If omitted, try to use '
              '$OMD_LIVESTATUS_SOCKET or $OMD_ROOT/tmp/run/live.'
        ))
    parser.add_option_group(connect_group)

    return parser.parse_args()


if __name__ == '__main__':
    opts, args = parse_arguments()
    # Make `list` the default action.
    if not opts.host:
        opts.list = True
    inv = OMDLivestatusInventory(opts.socket, by_ip=opts.by_ip)

    if opts.static:
        print(inv.static())
    elif opts.list:
        print(inv.list(indent=4, sort_keys=True))
    elif opts.host:
        print(inv.host(opts.host, indent=4, sort_keys=True))
    else:
        print('Missing command.')
        sys.exit(1)
