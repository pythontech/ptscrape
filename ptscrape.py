#=======================================================================
#       Screen-scraping framework
#=======================================================================
import logging
import bs4 as soup
import urllib2
from urllib import urlencode
from urlparse import urljoin
import cookielib
import os
import re

_log = logging.getLogger(__name__)

class PageSource(object):
    def __init__(self, cachedir=None, replay=False):
        self.cachedir = cachedir
        self.replay = replay
        self.jar = cookielib.CookieJar()
        self.agent = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.jar))
#                                          urllib2.HTTPRedirectHandler())

    def get(self, url, query=None, tag=None):
        '''HTTP GET request on a URL with optional query'''
        if query:
            url += '?' + query.urlencode()
        _log.info('GET %s', url)
        return self._transact(url, tag=tag)

    def post(self, url, query=None, tag=None):
        '''HTTP POST request on a URL with optional query'''
        _log.info('POST %s', url)
        data = ''
        if query:
            data = urlencode(query)
        return self._transact(url, data, tag=tag)

    def _transact(self, url, data=None, tag=None):
        '''Perform an HTTP request, or fetch page from cache'''
        if tag is None:
            tag = os.path.basename(url)
        if self.replay:
            content = self.read_cache(tag)
        else:
            doc = self.agent.open(url, data)
            _log.info('info %r', doc.info())
            content = doc.read()
            if self.cachedir:
                self.write_cache(tag, content)
        doc = soup.BeautifulSoup(content)
        return doc

    def read_cache(self, tag):
        cachefile = os.path.join(os.path.expanduser(self.cachedir), tag)
        with open(cachefile, 'rb') as f:
            content = f.read()
        return content

    def write_cache(self, tag, content):
        cachefile = os.path.join(os.path.expanduser(self.cachedir), tag)
        with open(cachefile, 'wb') as f:
            f.write(content)

class Rullion(object):
    baseurl = 'https://ssl.rullionsolutions.com/ccfe_prod/'

    def __init__(self, authfile, cachedir='~/var/ccfe', replay=False):
        with open(os.path.expanduser(authfile)) as f:
            self.user, self.password = f.readline().rstrip().split(':')
        self.source = PageSource(cachedir=cachedir, replay=replay)

    def login(self):
        main = self.source.get(self.baseurl+'main/',
                               tag='main')
        assert main.find('title').text == u'Login'
        query = {
            'j_username':self.user,
            'j_password':self.password,
            }
        check = self.source.post(self.baseurl+'j_security_check', query,
                                 tag='check')
        #assert check.find('title').text == u'Resources'
        home = self.source.get(self.baseurl+'main/',
                               tag='home')
        assert home.find('title').text == u'Resources'
        return home

    def timesheet(self, href):
        '''Get a timesheet update page'''
        tsurl = urljoin(self.baseurl+'main/', href)
        ts = self.source.get(tsurl, tag='ts')
        assert ts.find('title').text.startswith(u'Update this Timesheet')
        return ts

    def timesheet_link(self, tree, date):
        y, m, d = date.split('-')
        dmy = '%s/%s/%s' % (d, m, y[-2:])
        tslink = tree.find('a', text=lambda t: ' - '+dmy in t)
        return tslink

    def parse_timesheet(self, doc):
        '''
        <div id='grid_1'>
         <div ...>
          <table>
        </div>
        '''
        err = doc.find('p', {'class': lambda c: 'error' in c.split()})
        if err:
            raise Exception('ERROR: %s' % cdata(err))
        grid1 = doc.find('div', id='grid_1')
        if not grid1:
            raise ValueError('div#grid_1 not found')
        grid1t = grid1.find('table')
        if not grid1t:
            raise ValueError('div#grid_1 table not found')
        hrows = self.parse_hours_table(grid1t)
        print hrows

        grid2 = doc.find('div', id='grid_2')
        if not grid2:
            raise ValueError('div#grid_2 not found')
        grid2t = grid2.find('table')
        if not grid2t:
            raise ValueError('div#grid_2 table not found')
        arows = self.parse_allowance_table(grid2t)
        print arows

    def parse_hours_table(self, table):
        '''
        <input> items:
        hidden delete_grid_1 
        checkbox delete_grid_1 23
        text grid_1_1_wbs_code 23133.A0010
        text grid_1_1_title Control & Diagnostics
        text grid_1_1_d1 
        text grid_1_1_d2 
        ...
        text grid_1_1_d7 
        hidden grid_1_2_wbs_code 
        hidden grid_1_2_title 
        text grid_1_2_d1 
        ...
        text grid_1_2_d7 
        
        return dict of wbs -> [stdrow,ovtrow,deltag]
        rows['22614.A0110'] = ['1','2','23']
        '''
        rows = {}
        wbs = None
        deltag = None
        for inp in table.findAll('input'):
            type = inp['type']
            name = inp['name']
            if name == 'delete_grid_1' and type == 'checkbox':
                deltag = inp['value']
            elif re.match(r'grid_1_\d+_wbs_code', name):
                if type == 'text':
                    wbs = inp['value']
                    rows[wbs] = [None, None, deltag]
                    rows[wbs][0] = name[7:-9]
                elif type == 'hidden':
                    rows[wbs][1] = name[7:-9]
        return rows

    def parse_allowance_table(self, table):
        '''
        <tr>
        <span id="grid_2_1_rate_code" val="BMA">
        <input type="text" name="grid_2_1_d1"> 
        ...
        <input type="text" name="grid_2_1_d7"> 
        </tr>
        '''
        rows = {}
        for tr in table.findAll('tr'):
            span = tr.find('span')
            if not span:
                print tr
                continue
            id = span['id']
            if re.match(r'grid_2_\d+_rate_code', id):
                rows[span['val']] = id[7:-10]
        return rows

if __name__=='__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--replay', action='store_true')
    ap.add_argument('--date')
    ap.add_argument('action')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    rul = Rullion('~/.rullion.auth', replay=args.replay)

    doc = rul.login()
    if args.action == 'login':
        raise SystemExit

    menu = doc.find('li', {'id':'task_menu'})
    tslinks = menu.findAll('a', {'href': lambda h:'/ts_tmsht_update' in h})
    if args.action == 'tasks':
        for tslink in tslinks:
            print tslink.text
        raise SystemExit

    if args.date:
        date = args.date
    else:
        import datetime
        today = datetime.date.today()
        lastsat = today - datetime.timedelta(days=today.isoweekday()+1)
        date = lastsat.strftime('%Y-%m-%d')
    tslink = rul.timesheet_link(menu, date)
    if tslink is None:
        raise Exception('No timesheet link for %s' % date)
    print tslink

    ts = rul.timesheet(tslink['href'])
    if args.action == 'tspage':
        raise SystemExit

    tsdata = rul.parse_timesheet(ts)
    for inp in tsdata:
        print inp
