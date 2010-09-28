# Copyright 2009, 2010 Onen (onen.om@free.fr)
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

class ObmPlugin(object):
    """Abstract base class for logging plugins.

    Every plugin should extend this abstract class, which contains expected content for a plugin.
    """

    def __init__(self, logger):
        """Sets the logger initialised state to False."""
        self.__initialised = False

    def init(self):
        """This methods sets up the plugin.

        Add here the initialisation of the plugin (open file, etc.)."""
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    def is_working(self):
        """Tells if the plugin is working.

        Returns True if the plugin is currently working (doing a logging loop), False otherwise."""
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    def do_iteration(self, callBack):
        """Call this method to make the plugin do one iteration of logging.

        callBack is a pointer to a method to be called upon completion."""
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    @staticmethod
    def get_description():
        """Gets a text description for this plugin."""
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    @staticmethod
    def get_id():
        """Returns the plugin identification string."""
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    def get_logging_frequency(self):
        """Returns the logging frequency in seconds.

        The scheduler will try to run the loop (do_iteration() method) every 'result' seconds.
        """
        raise NotImplementedError("This method is abstract, needs to be implemented.")

    @staticmethod
    def get_version():
        """Returns the plugin version under the form 'xx.xx.xx'.

        Example: 02.23.00
        """
        raise NotImplementedError("This method is abstract, needs to be implemented.")