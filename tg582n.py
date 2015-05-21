from ptscrape import PageSource, soup, bs_cdata
from hashlib import md5
import os
import re

class Modem(object):
    def __init__(self, url, authfile, cachedir='~/var/modem', replay=False):
        self.url = url
        self.source = PageSource(cachedir=cachedir, replay=replay)
        f = open(os.path.expanduser(authfile))
        try:
            self.user, self.password = f.readline().rstrip().split(':')
        finally:
            f.close()

    def login(self):
        '''Log in to modem
        '''
        page = self.get_login_page()
        params = self.build_login_query(page)
        home = self.source.post(self.url+'/login.lp', query=params,
                                tag='home')
        assert bs_cdata(home.doc.find('title')).endswith(' Home')
        return home

    def get_login_page(self):
        page = self.source.get(self.url+'/login.lp',
                               tag='login')
        assert bs_cdata(page.doc.find('title')).endswith(' Login')
        return page

    def build_login_query(self, page):
        '''
        The page uses JavaScript to form a hash from username, password,
        a nonce value and other information.  We could run a JavaScript
        interpreter to perform the calculation, but it is just as easy
        and fun to mirror the calculations in Python.

        POST fields are:
        rn=(number)
        hidepw=(calculated md5hex)
        user=admin
        '''
        form = page.doc.find('form', {'name':'authform'})
        query = {}
        query['rn'] = form.find('input', {'name':'rn'})['value']
        query['user'] = self.user
        script = bs_cdata(page.doc.find('script'))
        #print script
        var = {}
        dig8 = xyz = None
        for line in script.split('\n'):
            m = re.match(r'^var (\w+) = \"(.*?)\"', line)
            if m:
                name, value = m.groups()
                var[name] = value
            m = re.match(r'^\s+":" \+ \"(\w+)\" \+ \":\" \+ \"(\w+)\"', line)
            if m:
                dig8, xyz = m.groups()
        #print var
        #print dig8, xyz
        HA1 = md5hex(self.user + ':' + var['realm'] + ':' + self.password)
        #print 'HA1',HA1
        HA2 = md5hex('GET' + ':' + var['uri'])
        #print 'HA2',HA2
        hidepw = md5hex(':'.join((HA1, var['nonce'],
                                  dig8, xyz, var['qop'], HA2)))
        #print 'hidepw',hidepw
        query['hidepw'] = hidepw
        #print query
        return query

    def get_broadband_page(self):
        page = self.source.get(self.url+'/cgi/b/bb/?be=0&l0=2&l1=-1',
                               tag='bb')
        assert bs_cdata(page.doc.find('title')).endswith(' Broadband Connection')
        return page

    def get_broadband_usage(self, page):
        raw = {}
        #blocks = page.doc.find_all('div', {'class':'contentitem'})
        blocks = page.doc.findAll('div', {'class':'contentitem'})
        for div in blocks:
            itemtitle = bs_cdata(div.find('span', {'class':'itemtitle'})).strip()
            lraw = raw[itemtitle] = {}
            datatable = div.find('table', {'class':'datatable'})
            #rows = datatable.find_all('tr')
            rows = datatable.findAll('tr')
            for tr in rows:
                #tds = tr.find_all('td')[:2]
                tds = tr.findAll('td')[:2]
                if len(tds) == 2:
                    desc = bs_cdata(tds[0]).strip()
                    value = bs_cdata(tds[1]).strip()
                    if desc:
                        lraw[desc] = value
        #print raw
        usage = {}
        for nkey,ntitle in (('dsl','DSL Connection'),('inet','Internet')):
            lusage = usage[nkey] = {}
            for key, value in raw[ntitle].items():
                if key.startswith('Data Transferred'):
                    tx, rx = txrx_gb(key, value)
                    lusage['tx'] = tx
                    lusage['rx'] = rx
        #print usage
        return usage

    def get_broadband_usage_string(self, page):
        usage = self.get_broadband_usage(page)
        vals = []
        for net, props in sorted(usage.items()):
            for key, value in sorted(props.items()):
                vals.append('%s.%s=%.2f' % (net, key, value))
        return ' '.join(vals)

def txrx_gb(label,values):
    m = re.match('Data Transferred.*\[(\w+)/(\w+)\]', label)
    if not m:
        raise ValueError('Data Transferred mismatch')
    txunit, rxunit = m.groups()
    if not all([unit in ('B','kB','MB','GB') for unit in (txunit,rxunit)]):
        raise ValueError('Unexpected units %r' % ((txunit,rxunit),))
    tx, rx = [float(v.strip().replace(',','.')) for v in values.split('/')]
    txGB = scale_GB(tx, txunit)
    rxGB = scale_GB(rx, rxunit)
    return txGB, rxGB

def scale_GB(num, unit):
    if unit == 'GB':
        return num / 1
    if unit == 'MB':
        return num / 1e3
    if unit == 'kB':
        return num / 1e6
    if unit == 'B':
        return num / 1e9
    raise ValueError('Unknown scale %s' % unit)

def md5hex(string):
    return md5(string).hexdigest()

if __name__=='__main__':
    import argparse
    import logging
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose','-v', action='store_true',
                    help='Show informational messages')
    ap.add_argument('--host','-H', default='adsl',
                    help='Hostname of modem')
    ap.add_argument('--replay', '-r', action='store_true',
                    help='Use cached pages rather than making web queries')
    sp = ap.add_subparsers(dest='action', metavar='ACTION',
                           help='Action to perform')
    a_login = sp.add_parser('login',
                            help='Log in to server')
    a_broadband = sp.add_parser('broadband',
                                help='Get broadband page')
    a_usage = sp.add_parser('usage',
                            help='Show broadband usage')
    a_log_usage = sp.add_parser('log-usage',
                                help='Record broadband usage in syslog')
    args = ap.parse_args()
    level = (logging.INFO if args.verbose else
             logging.WARNING)
    logging.basicConfig(level=level)
    modem = Modem('http://'+args.host, '~/.adsl.auth',
                  replay=args.replay)

    if args.action == 'login':
        modem.login()
    elif args.action == 'broadband':
        modem.login()
        page = modem.get_broadband_page()
        usage = modem.get_broadband_usage(page)
    elif args.action == 'usage':
        modem.login()
        page = modem.get_broadband_page()
        text = modem.get_broadband_usage_string(page)
        print text
    elif args.action == 'log-usage':
        modem.login()
        page = modem.get_broadband_page()
        text = modem.get_broadband_usage_string(page)
        import subprocess
        subprocess.call(['logger','-t','bbmodem',text])
    else:
        raise ValueError('Unknown action %r' % args.action)
