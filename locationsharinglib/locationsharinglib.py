#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: locationsharinglib.py
#
# Copyright 2017 Costas Tyfoxylos
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to
#  deal in the Software without restriction, including without limitation the
#  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#  sell copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#

"""
Main code for locationsharinglib

.. _Google Python Style Guide:
   http://google.github.io/styleguide/pyguide.html

"""

import json
import logging
import pickle
from datetime import datetime

from bs4 import BeautifulSoup as Bfs
from cachetools import TTLCache, cached
from requests import Session

from .locationsharinglibexceptions import (InvalidCredentials,
                                           InvalidData,
                                           InvalidUser,
                                           InvalidCookies)

__author__ = '''Costas Tyfoxylos <costas.tyf@gmail.com>'''
__docformat__ = '''google'''
__date__ = '''2017-12-24'''
__copyright__ = '''Copyright 2017, Costas Tyfoxylos'''
__credits__ = ["Costas Tyfoxylos", "Michaël Arnauts", "Amy Nagle"]
__license__ = '''MIT'''
__maintainer__ = '''Costas Tyfoxylos'''
__email__ = '''<costas.tyf@gmail.com>'''
__status__ = '''Development'''  # "Prototype", "Development", "Production".

# This is the main prefix used for logging
LOGGER_BASENAME = '''locationsharinglib'''
LOGGER = logging.getLogger(LOGGER_BASENAME)
LOGGER.addHandler(logging.NullHandler())

INVALID_EMAIL_MESSAGE = 'Sorry, Google doesn&#39;t recognize that email.'
INVALID_PASSWORD_TOKEN = 'Wrong password. Try again.'  # noqa
STATE_CACHING_SECONDS = 30

STATE_CACHE = TTLCache(maxsize=1, ttl=STATE_CACHING_SECONDS)


class Person(object):  # pylint: disable=too-many-instance-attributes
    """A person sharing its location as coordinates"""

    def __init__(self, data):
        logger_name = u'{base}.{suffix}'.format(base=LOGGER_BASENAME,
                                                suffix=self.__class__.__name__)
        self._logger = logging.getLogger(logger_name)
        self._id = None
        self._picture_url = None
        self._full_name = None
        self._nickname = None
        self._latitude = None
        self._longitude = None
        self._timestamp = None
        self._address = None
        self._country_code = None
        self._populate(data)

    def _populate(self, data):
        try:
            self._id = data[6][0]
            self._picture_url = data[6][1]
            self._full_name = data[6][2]
            self._nickname = data[6][3]
            self._latitude = data[1][1][2]
            self._longitude = data[1][1][1]
            self._timestamp = data[1][2]
            self._address = data[1][4]
            self._country_code = data[1][6]
        except IndexError:
            self._logger.debug(data)
            raise InvalidData

    def __str__(self):
        text = ('Full name        :{}'.format(self.full_name),
                'Nickname         :{}'.format(self.nickname),
                'Current location :{}'.format(self.address),
                'Latitute         :{}'.format(self.latitude),
                'Longitude        :{}'.format(self.longitude),
                'Datetime         :{}'.format(self.datetime))
        return '\n'.join(text)

    @property
    def id(self):  # pylint: disable=invalid-name
        """The internal google id of the account"""
        return self._id

    @property
    def picture_url(self):
        """The url of the person's avatar"""
        return self._picture_url

    @property
    def full_name(self):
        """The full name of the user as set in google"""
        return self._full_name

    @property
    def nickname(self):
        """The nickname as set in google"""
        return self._nickname

    @property
    def latitude(self):
        """The latitude of the person's current location"""
        return self._latitude

    @property
    def longitude(self):
        """The longitude of the person's current location"""
        return self._longitude

    @property
    def timestamp(self):
        """The timestamp of the location retrieval"""
        return self._timestamp

    @property
    def datetime(self):
        """A datetime representation of the location retrieval"""
        return datetime.fromtimestamp(int(self.timestamp) / 1000)

    @property
    def address(self):
        """The address as reported by google for the current location"""
        return self._address

    @property
    def country_code(self):
        """The location's country code"""
        return self._country_code


class Service(object):
    """An object modeling the service to retrieve locations"""

    def __init__(self, email, password, cookies_file=None):
        logger_name = u'{base}.{suffix}'.format(base=LOGGER_BASENAME,
                                                suffix=self.__class__.__name__)
        self._logger = logging.getLogger(logger_name)
        self._session = Session()
        self.email = email
        self.password = password
        self._login_url = 'https://accounts.google.com'

        # Try login with cookie
        if cookies_file and self._validate_cookie(cookies_file):
            return

        # Try login based on username/password
        self._authenticate()
        if cookies_file:
            self._export_cookie(cookies_file)

    def _validate_cookie(self, cookies_file):
        try:
            cfile = open(cookies_file, 'rb')
            self._session.cookies = pickle.load(cfile)
        except KeyError:
            self._logger.error(('Could not load pickle file, '
                                'probably invalid pickle.'))
            return False
        except IOError:
            self._logger.error(('Could not open pickle file, either file '
                                'does not exist or no read access.'))
            return False

        # Check if cookies are valid
        response = self._session.get(self._login_url)
        if 'Sign in - Google Accounts' in response.text:
            message = ('The cookies provided do not provide a valid session.'
                       'Please authenticate normally and save a valid session '
                       'again')
            raise InvalidCookies(message)

        return True

    def _export_cookie(self, cookies_file):
        try:
            cfile = open(cookies_file, 'wb')
            pickle.dump(self._session.cookies, cfile)
        except IOError:
            message = 'Could not export cookies to {}.'.format(cookies_file)
            raise InvalidCookies(message)

    def _authenticate(self):
        initial_form = self._initialize()
        password_form = self._submit_email(initial_form)
        self._submit_password(password_form)

    def _initialize(self):
        url = '{login_url}/ServiceLogin'.format(login_url=self._login_url)
        response = self._session.get(url)
        soup = Bfs(response.text, 'html.parser')
        form = soup.find('form')
        return self._get_hidden_form_fields(form)

    def _submit_email(self, payload):
        url = '{login_url}/signin/v1/lookup'.format(login_url=self._login_url)
        payload['Email'] = self.email
        response = self._session.post(url, data=payload)
        if INVALID_EMAIL_MESSAGE in response.text:
            raise InvalidUser(self.email)
        soup = Bfs(response.text, 'html.parser')
        form = soup.find('form')
        return self._get_hidden_form_fields(form)

    def _submit_password(self, payload):
        url = ('{login_url}/signin/'
               'challenge/sl/password').format(login_url=self._login_url)
        payload['Passwd'] = self.password
        response = self._session.post(url, data=payload)
        if "Unavailable because of too many failed attempts." in response.text:
            message = ("Too many failed login attempts. Try again in a few hours.")
            raise InvalidCredentials(message)
        if INVALID_PASSWORD_TOKEN in response.text:
            raise InvalidCredentials
        if "challenge/az" in response.url:
            response = self._handle_prompt(response)

    def _handle_prompt(self, resp):
        # Borrowed with slight modification from https://git.io/vxu1A
        response_page = Bfs(resp.text, 'html.parser')
        challenge_url = resp.url.split("?")[0]

        data_key = response_page.find('div', {'data-api-key': True}).get('data-api-key')
        data_tx_id = response_page.find('div', {'data-tx-id': True}).get('data-tx-id')
        
        await_url = "https://content.googleapis.com/cryptauth/v1/authzen/awaittx?alt=json&key=%s" % data_key
        await_body = {'txId': data_tx_id}
        
        print("Open the Google App, and tap 'Yes' on the prompt to sign in ...")
        
        self._session.headers['Referer'] = resp.url
        response = self._session.post(await_url, json=await_body)
        parsed = json.loads(response.text)

        payload = {
            'challengeId': response_page.find('input', {'name': 'challengeId'}).get('value'),
            'challengeType': response_page.find('input', {'name': 'challengeType'}).get('value'),
            'TL': response_page.find('input', {'name': 'TL'}).get('value'),
            'gxf': response_page.find('input', {'name': 'gxf'}).get('value'),
            'token': parsed['txToken'],
            'action': response_page.find('input', {'name': 'action'}).get('value'),
            'TrustDevice': 'on',
        }

        resp = self._session.post(challenge_url, data=payload)
        resp.raise_for_status()
        return resp       

    def logout(self):
        """Logs the session out, invalidating the cookies

        Returns:
            True on success, False otherwise

        """
        url = '{login_url}/Logout'.format(login_url=self._login_url)
        response = self._session.get(url)
        return response.ok

    @staticmethod
    def _get_hidden_form_fields(form):
        return {field.get('name'): field.get('value')
                for field in form.find_all('input')}

    @cached(STATE_CACHE)
    def _get_data(self):
        payload = {'authuser': 0,
                   'hl': 'en',
                   'gl': 'en',
                   # pd holds the information about the rendering of the map and
                   # it is irrelevant with the location sharing capabilities.
                   # the below info points to google's headquarters.
                   'pb': ('!1m7!8m6!1m3!1i14!2i8413!3i5385!2i6!3x4095'
                          '!2m3!1e0!2sm!3i407105169!3m7!2sen!5e1105!12m4'
                          '!1e68!2m2!1sset!2sRoadmap!4e1!5m4!1e4!8m2!1e0!'
                          '1e1!6m9!1e12!2i2!26m1!4b1!30m1!'
                          '1f1.3953487873077393!39b1!44e1!50e0!23i4111425')} 
        url = 'https://www.google.com/maps/preview/locationsharing/read'
        response = self._session.get(url, params=payload)
        self._logger.debug(response.text)
        return json.loads(response.text.split("'", 1)[1])

    def get_shared_people(self):
        """Retrieves all people that share their location with this account"""
        output = ''  # making pycharm introspection happy
        try:
            output = self._get_data()
            people = [Person(info) for info in output[0]]
        except (IndexError, TypeError):
            self._logger.exception('Response: %s', output)
            return []
        return people

    def get_authenticated_person(self):
        """Retrieves the person associated with this account"""
        output = ''  # making pycharm introspection happy
        try:
            output = self._get_data()
            person = Person([
                self.email,
                output[9][1],
                None,
                None,
                None,
                None,
                [
                    None,
                    None,
                    self.email,
                    self.email
                ]
            ])
        except (IndexError, TypeError):
            self._logger.exception('Response: %s', output)
            return None
        return person

    def get_all_people(self):
        """Retrieves all people sharing their location"""
        people = self.get_shared_people() + [self.get_authenticated_person()]
        return filter(None, people)

    def get_person_by_nickname(self, nickname):
        """Retrieves a person by nickname"""
        return next((person for person in self.get_all_people()
                     if person.nickname.lower() == nickname.lower()), None)

    def get_person_by_full_name(self, name):
        """Retrieves a person by full name"""
        return next((person for person in self.get_all_people()
                     if person.full_name.lower() == name.lower()), None)

    def get_coordinates_by_nickname(self, nickname):
        """Retrieves a person's coordinates by nickname"""
        person = self.get_person_by_nickname(nickname)
        if not person:
            return '', ''
        return person.latitude, person.longitude

    def get_coordinates_by_full_name(self, name):
        """Retrieves a person's coordinates by full name"""
        person = self.get_person_by_full_name(name)
        if not person:
            return '', ''
        return person.latitude, person.longitude
