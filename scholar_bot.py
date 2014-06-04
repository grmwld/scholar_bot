#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os
import sys
import argparse
import shutil
import time
import logging
import re
import datetime
import urllib
import urllib2
import urlparse
import mechanize
import pyPdf
import praw
import rest
from bs4 import BeautifulSoup
from Fetcher import Domain


URL = re.compile(r"""(
        (?P<scheme>https?)://       # scheme
        (?P<domain>[-\w\.]+)+       # domain
        (?P<port>:\d+)?             # port
        (?P<path>/[-\w/_\.\#\%]*)?  # path
        (?P<params>\?\S+)?)         # params
        """, re.VERBOSE)


class ScholarBot:
    def __init__(self, config):
        self.__config = config
        self.__user_agent = user_agent = ("Scholar bot 0.01 by /u/leap_down_here")
        self.__r = praw.Reddit(user_agent=self.__user_agent)
        self.__r.login(self.__config['reddit_usr'] , self.__config['reddit_pwd'])
        self.__subreddit = self.__r.get_subreddit(self.__config['subreddit'])
        self.__br = mechanize.Browser(factory=mechanize.RobustFactory())
        self.__br.addheaders = [('User-agent', 'Mozilla/5.0')]
        self.__br.set_handle_robots(False)
        self.__br.set_handle_redirect(True)
        self.__br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=10)
        self.__done = []
        self.__todo = []
        self.__gett = rest.User.login({
            'apikey': self.__config['gett_apk'],
            'email': self.__config['gett_usr'],
            'password': self.__config['gett_pwd']
        })

    def __ez_authenticate(self, url):
        raw_url = url
        import traceback
        try: # Open the url, follow any redirects and add proxy to the final one
            self.__br.open(url) # Raises 401 if direct link to PDF
            url = self.__add_proxy_to_url(self.__br.geturl())
            self.__br.open(url)
        except mechanize.HTTPError as e:
            # Handle 401 from trying to open direct link to PDF
            if e.code == 401:
                url = self.__add_proxy_to_url(url)
                try:
                    self.__br.open(url)
                except mechanize.HTTPError as e:
                    logging.warning(' \tWARNING: ' + e.msg)
                    return None
                except:
                    if self.__br.response().info().gettype() == 'application/pdf':
                        return url
            # Handle 404 if the proxy does not give access to the website
            elif e.code == 404:
                return None
            else:
                traceback.print_exc()
        except:
            traceback.print_exc()
        logging.debug(' \t\t\t' + url)
        if self.__br.title() == "Service d'authentification de l'Inist-CNRS":
            self.__br.select_form(nr=0)
            self.__br['username'] = self.__config['ez_usr']
            self.__br['password'] = self.__config['ez_pwd']
            self.__br.submit()
        return url

    def __add_proxy_to_url(self, url, proxy='.gate1.inist.fr'):
        if proxy not in url:
            scheme, domain, port, path, params = URL.match(url).groups()[1:]
            url = scheme + '://' + domain + proxy
            if port: url += port
            if path: url += path
            if params: url += params
        return url

    def __resolve_ncbi(self, url):
        self.__br.open(url)
        logging.info(' \t\tResolving an NCBI link')
        page = BeautifulSoup(self.__br.response().read())
        try:
            url = page\
                    .find('div', {'class': 'linkoutlist'})\
                    .find_next('ul')\
                    .find_next('a')\
                    .get('href')
            logging.debug(' \t\t\tNCBI ==> ' + url)
        except AttributeError:
            pass
        return url

    def __fetch_pdf(self, url):
        website = Domain(self.__br)
        return website.pdf()

    def __share(self, filepath, name):
        try:
            self.__current_share.create_file({'filename': name})
            self.__current_share.upload_file(filepath)
        except rest.ApiError as e:
            logging.error(' ' + e.msg)
        finally:
            os.remove(filepath)

    def __post_link_to_articles(self, submission):
        url = '/'.join(['http://ge.tt', self.__current_share['sharename']])
        submission.add_comment(url)
        time.sleep(610)

    def __delete_old(self, hours=24):
        now = datetime.datetime.now()
        shares = self.__gett.shares()
        old_shares = 0
        for share in shares:
            if (now - share['created']).total_seconds() / 3600 > hours:
                old_shares += 1
                logging.debug(' Destroying old share ' + share.sharename)
                share.destroy()
        logging.info(' Destroyed ' + str(old_shares) + ' old shares')
        if self.__config['dry'] is False:
            time.sleep(600)
        else:
            time.sleep(4)

    def __get_new_requests(self):
        c = 0
        logging.info('\n\n ::::::::::::::::::::::::::::\n :::: Fetching new posts ::::\n ::::::::::::::::::::::::::::\n')
        for submission in self.__subreddit.get_hot(limit=self.__config['batch_size']):
            c += 1
            #if submission not in self.__done and len(submission.comments) == 0:
            if submission not in self.__done:
                self.__todo.append(submission)
        logging.info(' Found ' + str(len(self.__todo)) + ' new submissions to process (out of ' + str(c) + ')')

    def __process_requests(self):
        s_id = -1
        for submission in self.__todo:
            s_id += 1
            logging.info('\n \t======== BEGIN  SUBMISSION #' + str(s_id) + ' =======')
            #logging.info(' \t' + '\n \t'.join([submission.title[i:i+80] for i in range(0, len(submission.title), 80)]))
            logging.info(' \t' + submission.title)
            logging.debug(' \t--- begin submission text ---')
            logging.debug(' \t> ' + submission.selftext.replace('\n', '\n \t> '))
            logging.debug(' \t---  end submission text  ---')
            urls = list(set([i[0].strip('(){}[]') for i in URL.findall(submission.selftext)]))
            if len(urls) > 0:
                self.__current_share = self.__gett.create_share({'title': submission.title})
                logging.info(' \tFound ' + str(len(urls)) + ' links')
                shared_count = 0
                for url in urls:
                    logging.debug(' \t\t' + url)
                    if url.startswith('http://www.ncbi.nlm.nih.gov'):
                        url = self.__resolve_ncbi(url)
                    url = self.__ez_authenticate(url)
                    if url:
                        filepath = self.__fetch_pdf(url)
                        if filepath:
                            shared_count += 1
                            self.__share(filepath, url)
                if shared_count:
                    if self.__config['dry'] is False:
                        self.__post_link_to_articles(submission)
                else:
                    self.__current_share.destroy()
            self.__done.append(submission)
            logging.info(' \t========   END  SUBMISSION #' + str(s_id) + ' ======')
        self.__todo = []

    def run(self):
        if self.__config['dry']:
            self.__delete_old(hours=0)
        while True:
            self.__get_new_requests()
            self.__process_requests()
            self.__delete_old(hours=36)

    @property
    def todo(self):
        return self.__todo

    @property
    def done(self):
        return self.__done  


def parse_config(config_file):
    d = {}
    for ls in [l.strip().split(' ') for l in config_file]:
        d[ls[0]] = ls[1]
    # Dry mode
    if 'dry' in d:
        if d['dry'].lower() == 'false': d['dry'] = False
        elif d['dry'].lower() == 'true': d['dry'] = True
        else: raise ValueError('Invalid "dry" value in configuration file')
    else:
        d['dry'] = True
    # Batch size
    if 'batch_size' in d:
        d['batch_size'] = int(d['batch_size'])
    else:
        d['batch_size'] = 10
    return d


def main(args):

    logging.getLogger('requests').setLevel(logging.WARNING)
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)
    logformat = '%(message)s'
    logging.basicConfig(level=numeric_level, format=logformat) 
    
    config = parse_config(args.config_file)
    scholar_bot = ScholarBot(config=config)
    scholar_bot.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config_file', dest='config_file',
        type=argparse.FileType('r'),
        nargs='?',
        default=sys.stdin,
        help='Input file'
    )
    parser.add_argument(
        '-l', '--loglevel', dest='loglevel',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default='info',
        help='Logging level'
    )
    parser.add_argument(
        '-o', '--logfile', dest='logfile',
        type=argparse.FileType('a'),
        default=sys.stderr,
        help='Where should the logging data be stored'
    )
    main(parser.parse_args())

