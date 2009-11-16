#!/usr/bin/env python

# Copyright 2009 Onen (onen.om@free.fr)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import unittest
import os
import ConfigParser

from logger import Config

Config.CONFIGURATION_FILENAME += '.test'

class TestConfig(unittest.TestCase):

    def setUp(self):
        self._config = Config()
        self._test_section_string = 'test_section'
        self._test_option_string = 'test_option'
        self._test_value_string = 'test_value'
        self._test_tuple = (self._test_section_string,
                            self._test_option_string,
                            self._test_value_string)

    def tearDown(self):
        os.remove(Config.CONFIGURATION_FILENAME)

    def test_set_config_if_not_exist_section_not_exist(self):
        """The section does not exist."""
        self.failUnlessRaises(ConfigParser.NoSectionError,
                              self._config.set,
                              *self._test_tuple)
        self._config.set_config_if_not_exist([
                                              (self._test_section_string, [
                                                                           (self._test_option_string,
                                                                            self._test_value_string)
                                                                           ]
                                              )
                                              ])
        self.failUnless(self._config.get(*self._test_tuple[:-1]) == self._test_value_string, '')

    def test_set_config_if_not_exist_option_not_exist(self):
        """The option does not exist."""
        self._config._config.add_section(self._test_section_string)
        self.failUnless(self._config._config.has_section(self._test_section_string) == True,'')
        self.failUnless(self._config._config.has_option(self._test_section_string,
                                                        self._test_option_string) == False,'')
        self._config.set_config_if_not_exist([
                                              (self._test_section_string, [
                                                                           (self._test_option_string,
                                                                            self._test_value_string)
                                                                           ]
                                              )
                                              ])
        self.failUnless(self._config.get(*self._test_tuple[:-1]) == self._test_value_string, '')

    def test_set_config_if_not_exist_option_exist(self):
        """The option does already exist."""
        self._config.set_config_if_not_exist([
                                              (self._test_section_string, [
                                                                           (self._test_option_string,
                                                                            self._test_value_string)
                                                                           ]
                                              )
                                              ])
        self.failUnless(self._config.get(*self._test_tuple[:-1]) == self._test_value_string, '')
        self._config.set_config_if_not_exist([
                                              (self._test_section_string, [
                                                                           (self._test_option_string,
                                                                            'toto')
                                                                           ]
                                              )
                                              ])
        self.failUnless(self._config.get(*self._test_tuple[:-1]) == self._test_value_string, '')

    def test_set_config_if_not_exist_multiple_options(self):
        params = [
                  (self._test_section_string, [
                                               (self._test_option_string, self._test_value_string),
                                               ('toto', 'titi')
                                               ]
                  )
                  ]

        self._config.set_config_if_not_exist(params)
        self.failUnless(self._config.get(*self._test_tuple[:-1]) == self._test_value_string, '')
        self.failUnless(self._config.get(params[0][0],
                                         'toto') == 'titi', '')

if __name__ == '__main__':
    unittest.main()