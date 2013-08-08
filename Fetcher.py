#!/usr/bin/env python
# -*- coding:utf-8 -*-

import sys
import argparse
import re
import logging
import urllib
import urllib2
import shutil
import mechanize
import pyPdf
from bs4 import BeautifulSoup



DOMAIN = re.compile(r'(https?://([-\w\.]+)+(:\d+)?)')


def Domain(browser):
    url = browser.response().geturl()
    domain = DOMAIN.search(url).group()
    for cls in Fetcher.__subclasses__():
        if cls.is_fetcher_for(domain):
            return cls(browser)
    return GenericFetcher(browser)



class Fetcher(object):
    def __init__(self, br):
        self.url = br.response().geturl()
        self.domain = DOMAIN.search(self.url).group()
        self.br = br

    def check_pdf(self, filepath):
        try:
            doc = pyPdf.PdfFileReader(file(filepath, 'rb'))
            return filepath
        except pyPdf.utils.PdfReadError:
            logging.info(' \t\t\tInvalid PDF')
            return None

    def _retrieve_pdf(self, pdf_text, pdf_url):
        filepath = None
        if pdf_url:
            if pdf_url.startswith('/'):
                pdf_url = '/'.join([self.domain, pdf_url])
            try:
                logging.debug(' \t\t\t' + ' ==> '.join([pdf_text, pdf_url]))
                filepath = self.br.retrieve(pdf_ur)[0]
                shutil.move(filepath, filepath+'.pdf')
                filepath += '.pdf'
                filepath = self.check_pdf(filepath)
            except mechanize.HTTPError:
                pass
        return filepath

    def _find_pdf(self):
        pass

    def pdf(self):
        filepath = self._retrieve_pdf('Current page', self.url)
        if not filepath:
            pdf_text, pdf_url = self._find_pdf()
            return self._retrieve_pdf(pdf_text, pdf_url)
        return filepath



class GenericFetcher(Fetcher):
    def __init__(self, br):
        super(GenericFetcher, self).__init__(br)

    @classmethod
    def is_fetcher_for(cls, domain):
        return False

    def _find_pdf(self):
        pdf_text = None
        pdf_url = None
        text_regex = '(Full.*Text.*PDF.*)|(.*Download.*PDF.*)|(.*PDF.*\([0-9]+.*\))'
        links = [l for l in self.br.links(text_regex=text_regex)]
        for link in links:
            pdf_text = link.text
            if link.url.endswith('pdf+html'):
                pdf_url = link.url[:-5]
                break
            else:
                pdf_url = link.url
                break
        return [pdf_text, pdf_url]



class SciencedirectFetcher(Fetcher):
    def __init__(self, br):
        super(SciencedirectFetcher, self).__init__(br)

    @classmethod
    def is_fetcher_for(cls, domain):
        return 'sciencedirect.com' in domain

    def _find_pdf(self):
        pdf_text = None
        pdf_url = None
        page = BeautifulSoup(self.br.response().read())
        pdf = page.find('a', {'id': 'pdfLink'})
        pdf_text = pdf.get_text()
        pdf_url = pdf.get('href')
        return [pdf_text, pdf_url]
        


class NatureFetcher(Fetcher):
    def __init__(self, br):
        super(NatureFetcher, self).__init__(br)

    @classmethod
    def is_fetcher_for(cls, domain):
        return 'nature.com' in domain

    def _find_pdf(self):
        pdf_text = None
        pdf_url = None
        page = BeautifulSoup(self.br.response().read())
        pdf = page.find('div', {'class': 'article-tools'})\
                .find_next('li', {'class': 'download-pdf'})\
                .find_next('a')
        pdf_text = pdf.get_text()
        pdf_url = pdf.get('href')
        return [pdf_text, pdf_url]



class ScienceFetcher(Fetcher):
    def __init__(self, br):
        super(ScienceFetcher, self).__init__(br)

    @classmethod
    def is_fetcher_for(cls, domain):
        return 'sciencemag.org' in domain

    def _find_pdf(self):
        pdf_text = None
        pdf_url = None
        page = BeautifulSoup(self.br.response().read())
        pdf = page\
                .find('div', {'id': 'article-cb-main'})\
                .find_next('a', {'rel': 'view-full-text.pdf'})
        pdf_text = pdf.get_text()
        pdf_url = pdf.get('href')
        return [pdf_text, pdf_url]



class WileyFetcher(Fetcher):
    def __init__(self, br):
        super(WileyFetcher, self).__init__(br)

    @classmethod
    def is_fetcher_for(cls, domain):
        return 'onlinelibrary.wiley.com' in domain

    def _find_pdf(self):
        pdf_text = None
        pdf_url = None
        page = BeautifulSoup(self.br.response().read())
        pdf = page.find('a', {'id': 'journalToolsPdfLink'})
        pdf_text = pdf.get_text()
        pdf_url = pdf.get('href')
        return [pdf_text, pdf_url]
