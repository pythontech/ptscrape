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
        return Page(url, doc)

    def read_cache(self, tag):
        cachefile = os.path.join(os.path.expanduser(self.cachedir), tag)
        with open(cachefile, 'rb') as f:
            content = f.read()
        return content

    def write_cache(self, tag, content):
        cachefile = os.path.join(os.path.expanduser(self.cachedir), tag)
        with open(cachefile, 'wb') as f:
            f.write(content)

class Page(object):
    def __init__(self, url, doc):
        self.url = url
        self.doc = doc

def bs_cdata(tag):
    '''Get the character data inside a BeautifulSoup element, ignoring all markup'''
    return ''.join(tag.findAll(text=True))

if __name__=='__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--replay', action='store_true')
    ap.add_argument('url')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
