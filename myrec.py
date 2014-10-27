#=======================================================================
# Rullion Timesheet submission
#
# config:
#  wbs.conf: WBS code -> description
#  rull.auth: username and password
# input: argv[1]: date
# action:
#  submit_pt_timesheet
#   dated XML file -> Timesheet
#   quarterise(): round to 15-minute multiples
#   write adjusted XML file
#   login
#   find timesheet for date
#   if more rows in file:
#    post request to add rows
#   elif fewer rows in file:
#    # post with request to delete rows
#   create query to fill grids
#   post update to save as draft
#=======================================================================
from ptscrape import PageSource, soup, bs_cdata
from urlparse import urljoin
import datetime
import re
import os
import logging

_log = logging.getLogger(__name__)

class MyRec(object):
    '''Tool for submitting timesheets to Rullion MyRecruiter'''

    siteurl = 'https://ssl.rullionsolutions.com'

    def __init__(self, org, authfile, cachedir='~/var/myrec', replay=False):
        '''
        :param org: First segment of site URL path
        :param authfile: File containing username:password
        :param cachedir: Folder to hold saved web pages
        :param replay: If True, read from cachedir instead of web site
        '''
        self.org = org
        self.wbs_titles = {}
        self.baseurl = '%s/%s/' % (self.siteurl, org)
        with open(os.path.expanduser(authfile)) as f:
            self.user, self.password = f.readline().rstrip().split(':')
        self.source = PageSource(cachedir=cachedir, replay=replay)

    def login(self):
        '''Log in to MyRecuiter using credentials from the authfile'''
        # Get the main page, setting a session cookie.  (Is it necessary?)
        main = self.source.get(self.baseurl+'main/',
                               tag='main')
        assert main.find('title').text == u'Login'
        # Post login credentials
        query = {
            'j_username': self.user,
            'j_password': self.password,
            }
        check = self.source.post(self.baseurl+'j_security_check', query,
                                 tag='check')
        #assert check.find('title').text == u'Resources'
        # Fetch the login page.  If login failed, we won't see Resources
        home = self.source.get(self.baseurl+'main/',
                               tag='home')
        assert home.find('title').text == u'Resources'
        # The menu will have pending timesheet tasks
        return home

    def timesheet(self, href):
        '''Get a timesheet update page'''
        tsurl = urljoin(self.baseurl+'main/', href)
        ts = self.source.get(tsurl, tag='ts')
        assert ts.find('title').text.startswith(u'Update this Timesheet')
        return ts

    def add_timesheet_rows(self, href, count):
        '''Post a request for a new timesheet with more rows
        The page has a span "Add New Timesheet Line Row(s)" with javascript
        which posts to .../main/ts_tmsht_update?page_key=nnnnn
          page_button=add_row_grid_1
          add_row_number_gris_1=n
        '''
        tsurl = urljoin(self.baseurl+'main/', href)
        query = {
            'page_button': 'add_row_grid_1',
            'add_row_number_grid_1': str(count),
            }
        ts = self.source.post(tsurl, query, tag='tsrows')
        return ts

    def parse_timesheet(self, doc):
        '''
        <div id='grid_1'>
         <div ...>
          <table>
        </div>

        Return (hrows, arows)
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
        #print hrows

        grid2 = doc.find('div', id='grid_2')
        if not grid2:
            raise ValueError('div#grid_2 not found')
        grid2t = grid2.find('table')
        if not grid2t:
            raise ValueError('div#grid_2 table not found')
        arows = self.parse_allowance_table(grid2t)
        #print arows
        return hrows, arows

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
                    rows[wbs][0] = name[:-9]
                elif type == 'hidden':
                    rows[wbs][1] = name[:-9]
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
                # Probably header
                # print tr
                continue
            id = span['id']
            if re.match(r'grid_2_\d+_rate_code', id):
                rows[span['val']] = id[:-10]
        return rows

    def get_timesheet_links(self):
        doc = self.login()
        # Identify pending timesheets in the task menu
        menu = doc.find('li', {'id':'task_menu'})
        tslinks = {}
        for a in menu.findAll('a', {'href': lambda h:'/ts_tmsht_update' in h}):
            m = re.search(r' - (\d\d)/(\d\d)/(\d\d)\)', a.text)
            assert m
            date = '20%s-%s-%s' % m.group(3,2,1)
            tslinks[date] = a['href']
        return tslinks

    def get_timesheet(self, date):
        tslinks = rec.get_timesheet_links()
        if date not in tslinks:
            raise KeyError('No timesheet for %s' % date)
        link = tslinks[args.date]
        ts = self.timesheet(link)
        return link, ts

    def timesheet_query(self, timesheet, hrows, arows):
        '''Create a query for the submission of a timesheet.
        timesheet contains hours and allowances.
        hrows and arows contain mappings from WBS/allowance codes to row ids.
        '''
        query = []
        wbss = timesheet.wbs_list()
        print 'wbss',wbss
        nwbs = len(wbss)
        if len(wbss) > len(hrows):
            raise ValueError('Need %d rows, only %d available' %
                             (nwbs, len(hrows)))
        for wbs, hrow in zip(wbss, hrows.values()[:nwbs]):
            std, ovt = timesheet.jobs[wbs]
            print 'std',std
            print 'ovt',ovt
            print 'hrow',hrow
            # Standard
            pfx = hrow[0] + '_'
            query.append((pfx+'wbs_code', wbs))
            query.append((pfx+'title', self.wbs_titles.get(wbs, wbs)))
            for d in range(7):
                query.append((pfx + 'd%d' % (1+d), '%.2f' % std[d]))
            # Overtime
            if any(ovt):
                pfx = hrow[1] + '_'
                query.append((pfx+'wbs_code', ''))
                query.append((pfx+'title', ''))
                for d in range(7):
                    query.append((pfx + 'd%d' % (1+d), '%.2f' % ovt[d]))
        # Allowances
        aused = set()
        for code, rowid in arows.items():
            pfx = rowid+'_'
            if code in timesheet.allowances:
                days = timesheet.allowances[code]
                aused.add(code)
            else:
                days = [0] * 7
            for d in range(7):
                query.append((pfx + 'd%d' % (1+d), '%.2f' % days[d]))
        for code in timesheet.allowances:
            if code not in aused:
                raise ValueError('Allowance %s not found in form' % code)
        # Delete any extra hours rows
        for hrow in hrows.values()[nwbs:]:
            query.append(('delete_grid_1', hrow[0]))
        return query
        
class Timesheet:
    '''Model of a timesheet for a single week
      enddate     YYYY-MM-DD or None
      jobs        dict, key=WBS, value=7-element list of (std,ovt) hours
      allowances  dict, key=code, value=7-element list of 1|0
    '''
    def __init__(self, enddate=None):
        if isinstance(enddate, (str, unicode)):
            enddate = date_from_iso(enddate)
        self.enddate = enddate
        self.name = None
        self.company = None
        self.jobs = {}          # wbs -> [[stddays],[ovtdays]]
        self.allowances = {}    # code -> [days]

    def set_enddate(self, date):
        if isinstance(date, (str, unicode)):
            date = date_from_iso(date)
        if self.enddate is not None  and  date != self.enddate:
            raise ValueError('End date already set to %s' % self.enddate)
        self.enddate = date

    def add_hours(self, date, wbs, hours, type='STD'):
        '''Record hours against a given job code on one day.
        By default standard hours, unless type='OVT'.'''
        day = self._day_number(date)
        if type not in ('STD,OVT'):
            raise ValueError('Invalid type "%s"; must be STD or OVT' % type)
        if wbs in self.jobs:
            job = self.jobs[wbs]
        else:
            job = self.jobs[wbs] = [[0]*7, [0]*7]
        job[1 if type=='OVT' else 0][day] += hours

    def add_allowance(self, date, code, quantity):
        day = self._day_number(date)
        #if code not in allowance_desc:
        #    raise ValueError('Unknown allowance code "%s"' % code)
        if code in self.allowances:
            al = self.allowances[code]
        else:
            al = self.allowances[code] = [0]*7
        al[day] += quantity

    def _day_number(self, date):
        if isinstance(date, (str, unicode)):
            date = date_from_iso(date)
        if self.enddate is None:
            raise ValueError('No enddate set')
        day = (date - self.enddate).days + 6
        if day < 0 or day > 6:
            raise ValueError('Date %s not in week ending %s' %
                             (date, self.enddate))
        return day

    def show(self):
        print self.enddate
        for wbs in sorted(self.jobs.keys()):
            job = self.jobs[wbs]
            for i, typ in enumerate(('STD','OVT')):
                if any([j != 0 for j in job]):
                    print '%s %s' % (wbs, typ),\
                        ' '.join(map(f2dot, job[i]))
        for code in sorted(self.allowances.keys()):
            al = self.allowances[code]
            # Assume they exist only if any recorded
            print '%s            ' % code,\
                ' '.join(map(f2dot, al))

    def wbs_list(self):
        return sorted(self.jobs.keys())

    @classmethod
    def from_tasklog_xml_file(cls, filename):
        with open(filename) as f:
            xml = f.read()
        return cls.from_tasklog_xml(xml)

    @classmethod
    def from_tasklog_xml(cls, xml):
        code_map = dict(ABP='SCM',
                        ABR='SCW',
                        ALH='MES')
        self = cls()
        doc = soup.BeautifulSoup(xml, features='xml')
        self.name = bs_cdata(doc.find('name'))
        self.company = bs_cdata(doc.find('company'))
        week = doc.find('week')
        enddate = week['enddate']
        self.set_enddate(enddate)
        for time in week.findAll('time'):
            wbs = time['jobcode']
            date = time['date']
            hours = time['hours']
            weekend = time.get('weekend','')
            self.add_hours(date, wbs, float(hours), 'OVT' if weekend else 'STD')
        alday = 1
        for allowance in week.findAll('allowance'):
            code = allowance['code']
            quantity = allowance['quantity']
            date = allowance.get('date','')
            if date == '':
                # Old tasklog did not tag allowance with date
                alday += 1
                date = date_shift(self.enddate, -7 + alday)
            self.add_allowance(date, code_map[code], float(quantity))
        return self

    def write_tasklog_xml(self, filename):
        '''Regenerate XML file from adjusted values
        '''
        f = open(filename, 'w')
        print >>f, '<?xml version="1.0"?>'
        print >>f, '<timesheet>'
        print >>f, ' <name>%s</name>' % self.name
        print >>f, ' <company>%s</company>' % self.company
        print >>f, '<week enddate="%s">' % self.enddate
        for wbs, stdovt in self.jobs.items():
            for ov in (0,1):
                byday = stdovt[ov]
                for d in range(len(byday)):
                    if byday[d] != 0:
                        print >>f, '<time jobcode="%s" date="%s"%s hours="%.2f"/>' %\
                        (wbs,
                         date_shift(self.enddate, -6+d),
                         ov and ' weekend="1"' or '',
                         byday[d])
            # FIXME ovt
        for code, byday in self.allowances.items():
            for d in range(len(byday)):
                if byday[d] != 0:
                    print >>f, '<allowance date="%s" code="%s" quantity="%d"/>' %\
                        (date_shift(self.enddate, -6+d), code, byday[d])
        print >>f, '</week>'
        print >>f, '</timesheet>'
        f.close()

    def fill_form(self, form):
        '''Prepare values to be posted
        form['hours']['grid_1_37']['std']['items']['d1'] = 4.5
        form['allowances']['grid_2_1']['ALH']['d5'] = 1
        '''
        joblist = self.wbse_list()
        week = self.doc.find('week')
        endday = dayno(week['enddate'])
        for time in week.findAll('time'):
            wbse = time['jobcode']
            date = time['date']
            hours = time['hours']
            rowindex = joblist.index(wbse)
            dn = 'd%d' % (dayno(date) + 7 - endday)
            form['hours'][rowindex]['std']['items']['wbs_code'] = wbse
            form['hours'][rowindex]['std']['items']['title'] = wbse # FIXME
            form['hours'][rowindex]['std']['items'][dn] = hours
        for al in week.findAll('allowance'):
            code = al['code']
            date = al['date']
            quantity = al['quantity']
            dn = 'd%d' % (dayno(date) + 7 - endday)
            form['allowances'][code]['items'][dn] = quantity

    def quarterise(self, itype=0):
        '''Fudge times to be round quarter-hours
        :param itype: 0 for standard hours, 1 for overtime
        '''
        total = 0.0
        by_wbs = {}
        for wbs,stdovt in self.jobs.items():
            wbstot = sum(stdovt[itype])
            by_wbs[wbs] = wbstot
            total += wbstot
        fix_wbs = round_dict(by_wbs, 0.25)
        _log.debug('round', str(fix_wbs))
        for wbs, stdovt in self.jobs.items():
            by_day = {}
            for d in range(7):
                by_day[d] = stdovt[itype][d]
            fix_day = round_dict(by_day, 0.25, fix_wbs[wbs])
            for d in range(7):
                self.jobs[wbs][itype][d] = fix_day[d]

def round_dict(d, quantum, target=None):
    '''Round values in a dict to be multiples of a quantum.
    Round the total up.
    '''
    units = {}
    diff = {}
    total = 0.0
    utotal = 0
    for k,v in d.items():
        # print 'k,v',k,v
        total += v
        units[k] = quanta(v, quantum)
        diff[k] = v - units[k] * quantum
        utotal += units[k]
    if target is None:
        # Round up
        import math
        utarget = int(math.ceil(total / quantum))
    else:
        utarget = quanta(target, quantum)
    # print 'utarget=%d utotal=%d' % (utarget,utotal)
    if utotal < utarget:
        # Initial adjusted values are too low.
        # E.g. 2.3, 0.4, 0.9.  units=2,0,1  utotal=3
        #      total=3.6, utarget=4
        #      diff=0.3, 0.4, -0.1
        # want to round up the largest
        # so units[k] := 2,1,1
        d2 = sorted(diff.keys(), key=lambda x:diff[x], reverse=True)
        for k in d2[:utarget-utotal]:
            units[k] += 1
    elif utotal > utarget:
        # Initial adjusted values are too high
        d2 = sorted(diff.keys(), key=lambda x:diff[x])
        for k in d2[:utotal-utarget]:
            units[k] -= 1
    adj = {}
    for k,u in units.items():
        adj[k] = u * quantum
    return adj

def quanta(value, quantum):
    '''Integer for which value is the nearest multiple'''
    return int(round(value / quantum))

def date_from_iso(isodate):
    return datetime.date(*[int(d) for d in isodate.split('-')])

if __name__=='__main__':
    def last_saturday():
        today = datetime.date.today()
        lastsat = today - datetime.timedelta(days=today.isoweekday() % 7 + 1)
        date = lastsat.strftime('%Y-%m-%d')
        return date

    import argparse
    import logging
    ap = argparse.ArgumentParser()
    ap.add_argument('--replay', action='store_true')
    ap.add_argument('--date', default=last_saturday())
    ap.add_argument('--rows', type=int, default=1)
    ap.add_argument('--timesheet', type=str)
    ap.add_argument('action')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    rec = MyRec('ccfe_prod', '~/.rullion.auth', replay=args.replay)

    if args.action == 'login':
        rec.login()
    elif args.action == 'tslinks':
        tslinks = rec.get_timesheet_links()
        for date, link in sorted(tslinks.items()):
            print date, link
    elif args.action == 'tspage':
        href, ts = rec.get_timesheet(args.date)
    elif args.action == 'inputs':
        href, ts = rec.get_timesheet(args.date)
        tsdata = rec.parse_timesheet(ts)
        for inp in tsdata:
            print inp
    elif args.action == 'tsrows':
        href, ts = rec.get_timesheet(args.date)
        hrows, arows = rec.parse_timesheet(ts)
        if len(hrows) < args.rows:
            tsr = rec.add_timesheet_rows(href, args.rows - len(hrows))
    elif args.action == 'query':
        ts = Timesheet.from_tasklog_xml_file(args.timesheet)
        #print 'ts',ts
        #print 'allow',ts.allowances
        href, tspage = rec.get_timesheet(args.date)
        hrows, arows = rec.parse_timesheet(tspage)
        if len(hrows) < args.rows:
            tspage = rec.add_timesheet_rows(href, args.rows - len(hrows))
        hrows, arows = rec.parse_timesheet(tspage)
        #print 'hrows',hrows
        #print 'arows',arows
        query = rec.timesheet_query(ts, hrows, arows)
        for n,v in sorted(query):
            print n,v
    else:
        raise ValueError('Unknown action %r' % args.action)
