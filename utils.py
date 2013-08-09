#!/usr/bin/env python
# -*- coding:utf-8 -*-

import os
import sys
import logging


class ErrorIgnore(object):
    def __init__(self, errors, errorreturn = None, errorcall = None):
        self.errors = errors
        self.errorreturn = errorreturn
        self.errorcall = errorcall

    def __call__(self, function):
        def returnfunction(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as E:
                if type(E) not in self.errors:
                    raise E
                if self.errorcall is not None:
                    self.errorcall(E, *args, **kwargs)
                return self.errorreturn
        return returnfunction
