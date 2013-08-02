#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os
import sys
import argparse
import shutil
import time
import re
import datetime
import urllib
import urllib2
import mechanize
import praw
import rest


REGEX_URL = re.compile(r'(https?://([-\w\.]+)+(:\d+)?(/([-\w/_\.\#\%]*(\?\S+)?)?)?)')
REGEX_DOMAIN = re.compile(r'(https?://([-\w\.]+)+(:\d+)?)')


class ScholarBot:
    def __init__(self, config):
        self.__config = config
        self.__user_agent = user_agent = ("Scholar bot 0.01 by /u/leap_down_here")
        self.__r = praw.Reddit(user_agent=self.__user_agent)
        self.__r.login(self.__config['reddit_usr'] , self.__config['reddit_pwd'])
        self.__subreddit = self.__r.get_subreddit(self.__config['subreddit'])
        self.__br = mechanize.Browser(factory=mechanize.RobustFactory())
        self.__br.set_handle_robots(False)
        self.__done = []
        self.__todo = []
        self.__gett = rest.User.login({
            'apikey': self.__config['gett_apk'],
            'email': self.__config['gett_usr'],
            'password': self.__config['gett_pwd']
        })

    def __ez_authenticate(self):
        self.__br.select_form(nr=0)
        self.__br['username'] = self.__config['ez_usr']
        self.__br['password'] = self.__config['ez_pwd']
        self.__br.submit()

    def __add_proxy_to_url(self, url):
        u = [p for p in url.split('/') if p]
        u[0] = u[0] + '/'
        u[1] = u[1] + '.gate1.inist.fr'
        return '/'.join(u)

    def __fetch_pdf(self, url):
        filepath = None
        pdf_url = None
        domain = REGEX_DOMAIN.search(url).group()
        try:
            self.__br.open(url)
        except urllib2.HTTPError, e:
            return None
        if self.__br.title() == "Service d'authentification de l'Inist-CNRS":
            self.__ez_authenticate()
        for link in self.__br.links(text_regex='(Full.*Text.*PDF.*)|(.*Download.*PDF.*)'):
            #print link.text, link.url
            if link.url.endswith('pdf+html'):
                pdf_url = link.url[:-5]
                break
            else:
                pdf_url = link.url
                break
        if pdf_url:
            try:
                filepath = self.__br.retrieve(pdf_url)[0]
            except ValueError:
                filepath = self.__br.retrieve('/'.join([domain, pdf_url]))[0]
            shutil.move(filepath, filepath+'.pdf')
            filepath += '.pdf'
        return filepath

    def __share(self, filepath, name):
        try:
            self.__current_share.create_file({'filename': name})
            self.__current_share.upload_file(filepath)
        except rest.ApiError:
            pass
        finally:
            os.remove(filepath)

    def __post_link_to_articles(self, submission):
        url = '/'.join(['http://ge.tt', self.__current_share['sharename']])
        submission.add_comment(url)
        #time.sleep(610)

    def __delete_old(self, hours=24):
        now = datetime.datetime.now()
        shares = self.__gett.shares()
        for share in shares:
            if (now - share['created']).total_seconds() / 3600 > hours:
                share.destroy()
        time.sleep(6)

    def __get_new_requests(self):
        for submission in self.__subreddit.get_hot(limit=20):
            if submission not in self.__done:
                self.__todo.append(submission)

    def __process_requests(self):
        for submission in self.__todo:
            #print
            #print '---'
            #print submission.title
            urls = [i[0].strip('(){}[]') for i in REGEX_URL.findall(submission.selftext)]
            urls = [u for u in urls if u.startswith('http://www.ncbi.nlm') is False]
            if len(urls) > 0:
                urls = map(self.__add_proxy_to_url, urls)
                urls = list(set(urls))
                self.__current_share = self.__gett.create_share({'title': submission.title})
                for url in urls:
                    #print '\t', url
                    filepath = self.__fetch_pdf(url)
                    if filepath:
                        self.__share(filepath, url)
                    else:
                        self.__current_share.destroy()
                #self.__post_link_to_articles(submission)
            self.__done.append(submission)
        self.__todo = []

    def run(self):
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
    return d


def main(args):
    config = parse_config(args.config_file)
    scholar_bot = ScholarBot(config = config)
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
        '-d', '--dry', dest='dry',
        action='store_true',
        default=False,
        help='Do not post link in comments'
    )
    main(parser.parse_args())
