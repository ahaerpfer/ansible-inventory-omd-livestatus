Dynamic inventory for Ansible with OMD and Livestatus
=====================================================

*omd_livestatus.py* is a [dynamic inventory script](
https://docs.ansible.com/ansible/intro_dynamic_inventory.html ) for
Ansible that reads hosts and group information from an [OMD](
http://omdistro.org/ ) (Open Monitoring Distribution) instance.  Data is
read via [Livestatus socket](
https://mathias-kettner.de/checkmk_livestatus.html ) directly from the
running monitoring core.

The script has currently only been tested with the Nagios core but
should also work with alternative monitoring cores like e.g. Shinken or
Icinga.

**Side note:** See [ConSol Labs](https://labs.consol.de/repo/) for the
latest OMD packages; software at the original OMD site is not up to
date.
