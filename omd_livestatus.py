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

import datetime
import os
import sys
import optparse                         # Legacy ... 2.6 still out there
import socket
import subprocess

try:
    import json
except ImportError:
    import simplejson as json

try:
    maketrans = str.maketrans           # Python 3
except AttributeError:
    from string import maketrans        # Python 2


class OMDLivestatusInventory(object):

    #: default socket path
    _def_socket_path = u'/tmp/run/live'

    #: Livestatus query string
    _def_host_query = (u'GET hosts\n'
        'Columns: address name alias groups host_custom_variables\n'
        'OutputFormat: json\n')

    #: string of bad characters in host or group names
    _bad_chars = u'.,;:[]/ '

    #: replacement char for bad chars
    _replacement_char = u'_'

    def __init__(self, location=None, method='socket', by_ip=False):
        self.data = {}
        self.inventory = {}
        self.method = method

        #: translation table for sanitizing group names
        #
        # See the following to find out why this can't be a class variable:
        # http://stackoverflow.com/questions/13905741/accessing-class-variables-from-a-list-comprehension-in-the-class-definition

        # This version only works for byte strings but not for unicode :-(
        #self._trans_table = maketrans(
        #    self._bad_chars, self._replacement_char * len(_bad_chars))

        # Unicode version; see also:
        # http://stackoverflow.com/questions/1324067/how-do-i-get-str-translate-to-work-with-unicode-strings
        self._trans_table = dict((ord(char), self._replacement_char)
                                 for char in self._bad_chars)

        if not location:
            if 'OMD_LIVESTATUS_SOCKET' in os.environ:
                self.location = os.environ['OMD_LIVESTATUS_SOCKET']
            elif 'OMD_ROOT' in os.environ:
                self.location = (os.environ['OMD_ROOT']
                                 + OMDLivestatusInventory._def_socket_path)
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
        if self.method == 'ssh':
            answer = json.loads(self._read_from_ssh())
        else:
            answer = json.loads(self._read_from_socket())

        for host in answer:
            self.data['hosts'].append(
                dict(zip((u'ip', u'name', u'alias', u'groups', u'custom_vars'),
                         host)))

    def _read_from_socket(self):
        """Read data from local Livestatus socket."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.location)
        s.send(OMDLivestatusInventory._def_host_query.encode('utf-8'))
        s.shutdown(socket.SHUT_WR)
        return s.recv(100000000).decode('utf-8')

    def _read_from_ssh(self):
        """Read data from remote Livestatus socket via SSH.

        Assumes non-interactive (e.g. via ssh-agent) access to the
        remote host.  The `unixcat` command (part of Livestatus) has to
        be available via $PATH at the remote end.

        """
        l = self.location.split(':', 1)
        l.append('.' + OMDLivestatusInventory._def_socket_path)
        host, path = l[0], l[1]
        cmd = ['ssh', host,
               '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10',
               'unixcat {0}'.format(path)]
        p = subprocess.Popen(cmd,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        out, err = p.communicate(
            input=OMDLivestatusInventory._def_host_query.encode('utf-8'))
        if p.returncode:
            raise RuntimeError(err)
        return out.decode('utf-8')

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
            for group in host['groups'] or [u'_NOGROUP']:
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
                    'omd_custom_vars': host['custom_vars'],
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
            for group in host['groups'] or [u'_NOGROUP']:
                sanitized_group = group.translate(self._trans_table)
                if sanitized_group in inventory:
                    inventory[sanitized_group].append(host['name'])
                else:
                    inventory[sanitized_group] = [host['name']]
            hostvars[host['name']] = {
                'ansible_host': host['ip'],
                'omd_alias': host['alias'],
                'omd_custom_vars': host['custom_vars'],
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
        out.append('# File created: {}'.format(datetime.datetime.now()))
        for group in [k for k in self.inventory.keys() if k != '_meta']:
            out.append('\n[{0}]'.format(group))
            for host in self.inventory[group]:
                vars = self.inventory['_meta']['hostvars'][host]
                hostvars = []
                for varname in vars.keys():
                    hostvars.append('{0}="{1}"'.format(varname, vars[varname]))
                out.append('{0}\t{1}'.format(host, ' '.join(hostvars)))
        return '\n'.join(out)


def _save_method(option, opt_str, value, parser):
    parser.values.method = opt_str.lstrip('-')
    parser.values.location = value


def parse_arguments():
    """Parse command line arguments."""
    parser = optparse.OptionParser(version='%prog {0}'.format(__version__))
    parser.set_defaults(method='socket')

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
        '--socket', type='string', dest='location', default=None,
        action='callback', callback=_save_method,
        help=('Set path to Livestatus socket.  If omitted, try to use '
              '$OMD_LIVESTATUS_SOCKET or $OMD_ROOT/tmp/run/live.'
        ))
    connect_group.add_option(
        '--ssh', type='string', dest='location', default=None,
        action='callback', callback=_save_method,
        help=('Connect to Livestatus socket via SSH.  LOCATION has the '
              'form [user@]host[:path], the default path is ./tmp/run/live.'
        ))
    parser.add_option_group(connect_group)

    opts, args = parser.parse_args()
    # Make `list` the default action.
    if not opts.host:
        opts.list = True
    return opts, args

if __name__ == '__main__':
    opts, args = parse_arguments()
    inv = OMDLivestatusInventory(opts.location,
                                 method=opts.method,
                                 by_ip=opts.by_ip)
    if opts.static:
        print(inv.static())
    elif opts.list:
        print(inv.list(indent=4, sort_keys=True))
    elif opts.host:
        print(inv.host(opts.host, indent=4, sort_keys=True))
    else:
        print('Missing command.')
        sys.exit(1)
