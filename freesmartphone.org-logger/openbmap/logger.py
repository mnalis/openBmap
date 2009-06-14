#!/usr/bin/python

# Copyright 2008, 2009 Ronan DANIELLOU
# Copyright 2008, 2009 Onen (onen.om@free.fr)
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

import gobject
import dbus
import sys
import dbus.mainloop.glib
import time
from datetime import datetime
import logging
import ConfigParser
import threading
import os.path
import urllib2
import math

# HTTP multi part upload
import Upload

class Gsm:
    # This lock will be used when reading/updating *any* GSM related variable.
    # Thus MCC, MNC, lac, cellid and strength are consistent.
    lock = threading.Lock()
    
    def __init__(self, bus):
        # "MCC", "MNC", "lac", "cid" and "strength" are received asynchronuously, through signal handler
        # thus we need to store them for the time the logging loop runs
        self._lac = -1
        self._cid = -1
        self._strength = -1
        self._networkAccessType = ''
        self._MCC = ''
        self._MNC = ''
        self._registrationGSM = ''
        
        self._manufacturer = 'N/A'
        self._model = 'N/A'
        self._revision = 'N/A'
        self.get_device_info()
        self._observers = []
        self._call_ongoing = False
        
        if bus:
            bus.add_signal_receiver(self.network_status_handler,
                                          'Status',
                                          'org.freesmartphone.GSM.Network',
                                          'org.freesmartphone.ogsmd',
                                          '/org/freesmartphone/GSM/Device')
            bus.add_signal_receiver(self.signal_strength_handler,
                                          'SignalStrength',
                                          'org.freesmartphone.GSM.Network',
                                          'org.freesmartphone.ogsmd',
                                          '/org/freesmartphone/GSM/Device')
            bus.add_signal_receiver(self.call_status_handler,
                                          'CallStatus',
                                          'org.freesmartphone.GSM.Call',
                                          'org.freesmartphone.ogsmd',
                                          '/org/freesmartphone/GSM/Device')
            self._gsmMonitoringIface = dbus.Interface( bus.get_object('org.freesmartphone.ogsmd', '/org/freesmartphone/GSM/Device'),
                                                       "org.freesmartphone.GSM.Monitor" )
            self._gsmNetworkIface = dbus.Interface( bus.get_object('org.freesmartphone.ogsmd', '/org/freesmartphone/GSM/Device'),
                                                       "org.freesmartphone.GSM.Network" )
            self._gsmCallIface = dbus.Interface( bus.get_object('org.freesmartphone.ogsmd', '/org/freesmartphone/GSM/Device'),
                                                       "org.freesmartphone.GSM.Call" )

    def call_status_handler(self, data, *args, **kwargs):
        """This maps to org.freesmartphone.GSM.Call.CallStatus.
        """
        logging.debug('Call status change notified, gets the lock.')
        self.acquire_lock()
        # CallStatus ( isa{sv} )
        #i: id
        #The index of the call that changed its status or properties.
        #s: status
        #The new status of the call. Expected values are:
        # * "incoming" = The call is incoming (but not yet accepted),
        # * "outgoing" = The call is outgoing (but not yet established),
        # * "active" = The call is the active call (you can talk),
        # * "held" = The call is being held,
        # * "release" = The call has been released.
        self._call_ongoing = False
        list = self._gsmCallIface.ListCalls()
        for call in list:
            index, status, properties = call
            if status != 'release':
                logging.info('Call ongoing: %i, %s.' % (index, status) )
                self._call_ongoing = True
        if not self._call_ongoing:
            logging.info('No call ongoing left.')
        logging.debug('Call status updated, released the lock.')
        self.release_lock()

    def call_ongoing(self):
        """Returns True if a call is ongoing. False otherwise."""
        logging.debug('call_ongoing() gets the lock.')
        self.acquire_lock()
        result = self._call_ongoing
        logging.debug('call_ongoing()? %s' % result)
        logging.debug('call_ongoing(), released the lock.')
        self.release_lock()
        return result

    def network_status_handler(self, data, *args, **kwargs):
        """Handler for org.freesmartphone.GSM.Network.Status signal.
        
        MCC, MNC, lac, cid and signal strengh are received asynchronuously through this signal/handler.
        Warning: we do not receive this signal when only the signal strength changes, see
        org.freesmartphone.GSM.Network.SignalStrength signal, and self.signal_strength_handler().
        """
        logging.debug("Wait for updating GSM data.")
        self.acquire_lock()
        logging.debug("Lock acquired, updating GSM data.")
        try:
            if data['registration'] == 'home' or data['registration'] == 'roaming':
                logging.info('Registration status is: %s.' % data['registration'])
            else:
                logging.info('Registration status is: %s. Skip.' % data['registration'])
                raise Exception, 'GSM data not available.'
                    
            if "lac" and "cid" and "strength" and "code" and "act" in data:
                self._MCC = (str(data['code'])[:3]).lstrip('0')
                self._MNC = (str(data['code'])[3:]).lstrip('0')
                self._networkAccessType = data['act']
                # lac and cid are hexadecimal strings
                self._lac = str(int(data["lac"], 16))
                self._cid = str(int(data["cid"], 16))
                # The signal strength in percent (0-100) is returned.
                # Mickey pointed out (see dev mailing list archive):
                # in module ogsmd.gsm.const:
                #def signalQualityToPercentage( signal ):
                #"""
                #Returns a percentage depending on a signal quality strength.
                #"""
                #<snip>
                #if signal == 0 or signal > 31:
                #    return 0
                #else:
                #    return int( round( math.log( signal ) / math.log( 31 ) * 100 ) )
                if data["strength"] == 0:
                    raise Exception, 'GSM strength (0) not suitable.'
                else:
                    self._strength = self.signal_percent_to_dbm( data["strength"] )
                    val_from_modem = (self._strength + 113 ) / 2
                    self._registrationGSM = data['registration']
                    logging.info("MCC %s MNC %s LAC %s, CID %s, strength %i/%i/%i (dBm, modem, percent 0-100)" % \
                                 (self._MCC, self._MNC, self._lac, self._cid,
                                  self._strength, val_from_modem, data['strength']))
            else:
                raise Exception, 'One or more required GSM data (MCC, MNC, lac, cid or strength) is missing.'
        except Exception, e:
            logging.warning('Unable to get GSM data.')
            self.empty_GSM_data()
            logging.warning(str(e))
        self.release_lock()
        logging.debug("GSM data updated, lock released.")
        self.notify_observers()

    def signal_strength_handler(self, data, *args, **kwargs):
        """Handler for org.freesmartphone.GSM.Network.SignalStrength signal.
        """
        logging.debug("Wait for updating GSM signal strength.")
        self.acquire_lock()
        logging.debug("Lock acquired, updating GSM signal strength.")
        try:
            new_dbm = self.signal_percent_to_dbm(data)
            if self.check_GSM():
                logging.info('GSM Signal strength updated from %i dBm to %i dBm (%i %%)' %
                             (self._strength,
                              new_dbm,
                              data))
                self._strength = new_dbm
            else:
                logging.info('GSM data invalid, no signal strength update to %i dBm (%i %%)' %
                             (new_dbm, data))
        except Exception, e:
            logging.warning('Unable to update GSM signal strength.')
            logging.warning(str(e))
        self.release_lock()
        logging.debug("GSM signal strength update finished, lock released.")
        self.notify_observers()

    def empty_GSM_data(self):
        """Empty all the local GSM related variables."""
        self._lac = ''
        self._cid = ''
        self._MCC = ''
        self._MNC = ''
        self._strength = 0
        self._registrationGSM = ''
        self._networkAccessType = ''
    
    def get_device_info(self):
        """If available, returns the manufacturer, model and revision."""
        #TODO call the dBus interface only if instance attributes are not set.
        obj = dbus.SystemBus().get_object('org.freesmartphone.ogsmd', '/org/freesmartphone/GSM/Device')
        data = dbus.Interface(obj, 'org.freesmartphone.GSM.Device').GetInfo()
        if 'manufacturer' in data:
            # At the moment the returned string starts and ends with '"' for model and revision
            self._manufacturer = data['manufacturer'].strip('"')
        if 'model' in data:
            # At the moment the returned string starts and ends with '"' for model and revision
            self._model = data['model'].strip('"')
        if 'revision' in data:
            # At the moment the returned string starts and ends with '"' for model and revision
            self._revision = data['revision'].strip('"')
        logging.info('Hardware manufacturer=%s, model=%s, revision=%s.' % \
                     (self._manufacturer, self._model, self._revision))
        return(self._manufacturer, self._model, self._revision)
        
    def check_GSM(self):
        """Returns True if valid GSM data is available."""
        # if something went wrong with GSM data then strength will be set to 0 (see empty_GSM_data() )
        # see 3GPP documentation TS 07.07 Chapter 8.5, GSM 07.07 command +CSQ
        return (self._strength >= -113 and self._strength <= -51)
    
    def signal_percent_to_dbm(self, val):
        """Translate the signal percent value to dbm."""
        # The signal strength in percent (0-100) is returned.
        # Mickey pointed out (see dev mailing list archive):
        # in module ogsmd.gsm.const:
        #def signalQualityToPercentage( signal ):
        #"""
        #Returns a percentage depending on a signal quality strength.
        #"""
        #<snip>
        #if signal == 0 or signal > 31:
        #    return 0
        #else:
        #    return int( round( math.log( signal ) / math.log( 31 ) * 100 ) )
        val_from_modem = int( round(math.exp(val * math.log( 31 ) /100)) )
        # translate to dBm (see 3GPP documentation TS 07.07 Chapter 8.5, GSM 07.07 command +CSQ)
        return val_from_modem * 2 - 113
    
    def get_serving_cell_information(self):
        """Returns a dictionary with serving cell monitoring data.
        
        If available contains 'lac' and 'cid'. May contain 'rxlev' and 'tav'.
        Otherwise returns an empty dictionary.
        """
        result = {}
        try:
            data = self._gsmMonitoringIface.GetServingCellInformation()
            
            # Debug
            # string hex
            #data['cid'] = '0'
            # string hex
            #data['lac'] = '0'
            # int
            #data['rxlev'] = 0
            #del data['lac']
            #del data['cid']
            # end of debug
            
            logging.debug( 'Raw data serving cell: %s' % data)
            
            if 'cid' in data and int(data['cid'], 16) == 0:
                # I have seen cid of 0. This does not make sense?
                logging.info('Serving cell with cell id of 0 discarded.')
            elif 'lac' in data and int(data['lac'], 16) == 0:
                # Not sure if I have seen lac of 0. This does not make sense? In case of...
                logging.info('Serving cell with lac of 0 discarded.')
            elif ('rxlev' in data) and (data['rxlev'] == 0):
                    logging.info('GSM rxlev (0) not suitable, this serving cell is discarded.')
            else:
                # wiki.openmoko.org/wiki/Neo_1973_and_Neo_FreeRunner_gsm_modem#Serving_Cell_Information_.282.2C1.29
                # states:
                # rxlev      Received Field Strength      (rxlev/2)+2 gives the AT+CSQ response value 
                # The best answer I could get was: no idea if this is correct.
                # Thus we keep the values as unmodified as possible.
                for key in ['rxlev', 'tav']:
                    if key in data:
                        result[key] = data[key]

                if "lac" in data and "cid" in data:
                    # lac and cid are hexadecimal strings
                    result['lac'] = str(int(data["lac"], 16))
                    result['cid'] = str(int(data["cid"], 16))
                else:
                    logging.debug('Either lac or cid is missing in serving cell information.')
                    result.clear()

        except Exception, e:
            logging.error('get serving cell info: %s' % str(e))
            result.clear()

        logging.debug( 'serving cell result: %s' % result)
        return result

    def get_neighbour_cell_info(self):
        """Returns a tuple of dictionaries, one for each cell.
        
        Each dictionary contains lac and cid fields.
        They may contain rxlev, c1, c2, and ctype.
        """
        results = []
        try:
            data = self._gsmMonitoringIface.GetNeighbourCellInformation()
            for cell in data:
                #logging.debug( 'Raw data neighbour cell: %s' % cell)
                if "lac" and "cid" in cell:
                    # lac and cid are hexadecimal strings
                    result = {}
                    result['lac'] = str(int(cell["lac"], 16))
                    result['cid'] = str(int(cell["cid"], 16))
                    # The signal strength in percent (0-100) is returned.
                    # The following comments were about the signal strength (see GetStatus):
                        # Mickey pointed out (see dev mailing list archive):
                        # in module ogsmd.gsm.const:
                        #def signalQualityToPercentage( signal ):
                        #"""
                        #Returns a percentage depending on a signal quality strength.
                        #"""
                        #<snip>
                        #if signal == 0 or signal > 31:
                        #    return 0
                        #else:
                        #    return int( round( math.log( signal ) / math.log( 31 ) * 100 ) )
                        
                        # http://wiki.openmoko.org/wiki/Neo_1973_and_Neo_FreeRunner_gsm_modem#Serving_Cell_Information_.282.2C1.29
                        # states:
                        # rxlev      Received Field Strength      (rxlev/2)+2 gives the AT+CSQ response value 
                        # The best answer I could get was: no idea if this is correct.
                        # Thus we keep the values as unmodified as possible.
                    if 'rxlev' in cell:
                        result['rxlev'] = cell['rxlev']
                    if 'c1' in cell:
                        result['c1'] = cell['c1']
                    if 'c2' in cell:
                        result['c2'] = cell['c2']
                    #if 'ctype' in cell:
                    #    result['ctype'] = ('NA', 'GSM', 'GPRS')[cell['ctype']]
                    #logging.debug( 'Neighbour cell result: %s' % result)
                    
                    if int(result['cid']) == 0:
                        # I have seen cid of 0. This does not make sense?
                        logging.info('Neighbour cell with cell id of 0 discarded.')
                    elif int(result['lac']) == 0:
                        # Not sure if I have seen lac of 0. This does not make sense? In case of...
                        logging.info('Neighbour cell with lac of 0 discarded.')
                    elif ('rxlev' in cell) and (cell['rxlev'] == 0):
                            logging.info('GSM rxlev (0) not suitable, this neighbour cell is discarded.')
                    else:
                        results.append(result)
        except Exception, e:
            logging.error('get neighbour cells info: %s' % str(e))
            return ()
        return tuple(results)
        
    def get_gsm_data(self):
        """Return validity boolean, tuple serving cell data, tuple of neighbour cells dictionaries.
        
        Operation is atomic, values cannot be modified while reading it.
        The validity boolean is True when all fields are valid and consistent,
        False otherwise.
        
        Serving cell tuple contains: MCC, MNC, lac, cid, signal strength, access type, timing advance, rxlev.
        Timing advance and rxlev may be emtpy.
        
        Each neighbour cell dictionary contains lac and cid fields.
        They may contain rxlev, c1, c2, and ctype.
        """
        logging.debug("Wait for reading GSM data.")
        self.acquire_lock()
        logging.debug("Lock acquired, reading GSM data.")
        (valid, mcc, mnc, lac, cid, strength, act) = (self.check_GSM(),
                                                      self._MCC,
                                                      self._MNC,
                                                      self._lac,
                                                      self._cid,
                                                      self._strength,
                                                      self._networkAccessType)
        neighbourCells = ()
        tav = ''
        rxlev = ''
        # this is deactivated for release 0.2.0
        # and re-activated for release 0.3.0
        if valid: 
            neighbourCells = self.get_neighbour_cell_info()
            servingInfo = self.get_serving_cell_information()
            # in case of a change in registration not already taken into account here
            # by processing D-Bus signal by network_status_handler(), we prefer using data
            # from get_serving_cell_information()
            if ('lac' in servingInfo) and ('cid' in servingInfo):
                lac = servingInfo['lac']
                cid = servingInfo['cid']
            
                # deactivated. Timing advance only works for the serving cell, and when a channel is actually open
                #if 'tav' in servingInfo:
                #    tav = str(servingInfo['tav'])
                    
                if 'rxlev' in servingInfo:
                    rxlev = str(servingInfo['rxlev'])
        
        logging.info("valid=%s, MCC=%s, MNC=%s, lac=%s, cid=%s, strength=%s, act=%s, tav=%s, rxlev=%s" %
             (valid, mcc, mnc, lac, cid, strength, act, tav, rxlev))
                
        self.release_lock()
        logging.debug("GSM data read, lock released.")
        return (valid, (mcc, mnc, lac, cid, strength, act, tav, rxlev), neighbourCells )
    
    def get_status(self):
        """Get GSM status.
        
        Maps to org.freesmartphone.GSM.Network.GetStatus().
        It uses network_status_handler() to parse the output.
        """
        status = self._gsmNetworkIface.GetStatus()
        self.network_status_handler(status)
        
    def acquire_lock(self):
        """Acquire the lock to prevent state of the GSM variables to be modified."""
        self.lock.acquire()
        
    def release_lock(self):
        """Release the lock on the object"""
        self.lock.release()
        
    def notify_observers(self):
        for obs in self._observers:
            obs.notify()
        logging.debug('Gsm class notifies its observers.')
            
    def register(self, observer):
        self._observers.append(observer)
    
class Config:
    LOG_FILENAME = 'General log file name'
    LOGGING_LEVEL = 'Logging level'
    APP_HOME_DIR = os.path.join(os.environ['HOME'], '.openBmap')
    TEMP_LOG_FILENAME = os.path.join(APP_HOME_DIR,
                                     'openBmap.log')
    CONFIGURATION_FILENAME = os.path.join(APP_HOME_DIR,
                                     'openBmap.conf')
    XML_LOG_VERSION = 'V2'
    # For ease of comparison in database, we use ##.##.## format for version:
    SOFTWARE_VERSION = '00.03.01'
    
    def __init__(self):        
        # strings which will be used in the configuration file
        self.GENERAL = 'General'
        self.OBM_LOGS_DIR_NAME = 'OpenBmap logs directory name'
        self.OBM_PROCESSED_LOGS_DIR_NAME = 'OpenBmap uploaded logs directory name'
        self.OBM_UPLOAD_URL = 'OpenBmap upload URL'
        self.OBM_API_CHECK_URL = 'OpenBmap API check URL'
        self.OBM_API_VERSION = 'OpenBmap API version'
        self.SCAN_SPEED_DEFAULT = 'OpenBmap logger default scanning speed (in sec.)'
        self.MIN_SPEED_FOR_LOGGING = 'GPS minimal speed for logging (km/h)'
        self.MAX_SPEED_FOR_LOGGING = 'GPS maximal speed for logging (km/h)'
        # NB_OF_LOGS_PER_FILE is considered for writing of log to disk only if MAX_LOGS_FILE_SIZE <= 0
        self.NB_OF_LOGS_PER_FILE = 'Number of logs per file'
        # puts sth <=0 to MAX_LOGS_FILE_SIZE to ignore it and let other conditions trigger
        # the write of the log to disk (e.g. NB_OF_LOGS_PER_FILE)
        self.MAX_LOGS_FILE_SIZE = 'Maximal size of log files to be uploaded (kbytes)'
        
        self.CREDENTIALS = 'Credentials'
        self.OBM_LOGIN = 'OpenBmap login'
        self.OBM_PASSWORD = 'OpenBmap password'
        
        self._config = self.load_config()
        # TODO: it writes the config file every time! :-(
        self.save_config()
                
    def load_config(self):
        """Try loading the configuration file.
        
        Try to load the configuration file. If it does not exist, the default values
        are loaded, and the configuration file is saved with these default values.
        """
        logging.debug('Loading configuration file: \'%s\'' % Config.CONFIGURATION_FILENAME)
        config = ConfigParser.RawConfigParser();
        try:
            config.readfp(open(self.CONFIGURATION_FILENAME))
            logging.debug('Configuration file loaded.')
        except Exception, e:
                logging.warning("No configuration file found: uses default values")
                config.add_section(self.GENERAL)
                #config.set(self.GENERAL, self.CONFIGURATION_FILENAME, 'OpenBmap.conf')
                #TODO config.set(self.GENERAL, self.LOGGING_LEVEL, 'logging.DEBUG')
                #TODO config.set(self.GENERAL, self.LOG_FILENAME,
                #           os.path.join(self.APP_HOME_DIR,
                #                        'OpenBmap.log'))
                config.set(self.GENERAL, self.OBM_LOGS_DIR_NAME, 
                           os.path.join(self.APP_HOME_DIR,
                                        'Logs'))
                config.set(self.GENERAL, self.OBM_PROCESSED_LOGS_DIR_NAME, 
                           os.path.join(self.APP_HOME_DIR,
                                        'Processed_logs'))
                config.set(self.GENERAL, self.OBM_UPLOAD_URL, 'http://realtimeblog.free.fr/upload/upl.php5')
                config.set(self.GENERAL, self.OBM_API_CHECK_URL, 'http://realtimeblog.free.fr/getInterfacesVersion.php')
                config.set(self.GENERAL, self.OBM_API_VERSION, '2')
                config.set(self.GENERAL, self.SCAN_SPEED_DEFAULT, 10) # in sec.
                config.set(self.GENERAL, self.MIN_SPEED_FOR_LOGGING, 0)
                config.set(self.GENERAL, self.MAX_SPEED_FOR_LOGGING, 150)
                config.set(self.GENERAL, self.NB_OF_LOGS_PER_FILE, 3)
                config.set(self.GENERAL, self.MAX_LOGS_FILE_SIZE, 20)
                
                config.add_section(self.CREDENTIALS)
                config.set(self.CREDENTIALS, self.OBM_LOGIN, 'your_login')
                config.set(self.CREDENTIALS, self.OBM_PASSWORD, 'your_password')
                           
        return config
        
    def get(self, section, option):
        try:
            if option in [self.SCAN_SPEED_DEFAULT,
                          self.MIN_SPEED_FOR_LOGGING,
                          self.MAX_SPEED_FOR_LOGGING,
                          self.NB_OF_LOGS_PER_FILE,
                          self.MAX_LOGS_FILE_SIZE]:
                return self._config.getint(section, option)
            else:
                return self._config.get(section, option)
        except Exception, e:
            # we cannot find it. Maybe the current config file (old version) did not contain
            # this entry (newer version of the software)
            defaultValue = 0
            if option in [self.MAX_LOGS_FILE_SIZE]:
                defaultValue = 20
            else:
                logging.critical("get_option() does not find (%s / %s). This is much probably a bug." % (section, option))
                logging.critical(str(e))
                #TODO: well in case this happens, this should be forwarded to Views (GUI) in order to inform the user
                sys.exit(-1)
            self._config.set(self.GENERAL, option, defaultValue)
            logging.info('Option \'%s\' cannot be found. Add it to the config file with default value: %i'
                         % (option, defaultValue))
            self.save_config()
            return defaultValue

    def set(self, section, option, value):
        self._config.set(section, option, value)
        
    def save_config(self):
        configFile = open(Config.CONFIGURATION_FILENAME, 'wb')
        logging.info('Save config file \'%s\'' % Config.CONFIGURATION_FILENAME)
        self._config.write(configFile)
        configFile.close()        
    
class Gps:
    
    GYPSY_DEVICE_FIX_STATUS_INVALID = 0
    GYPSY_DEVICE_FIX_STATUS_NONE = 1
    # A fix with latitude and longitude has been obtained 
    GYPSY_DEVICE_FIX_STATUS_2D = 2
    # A fix with latitude, longitude and altitude has been obtained
    GYPSY_DEVICE_FIX_STATUS_3D = 3

    def __init__(self):	
        self._dbusobj = dbus.SystemBus().get_object('org.freesmartphone.ogpsd', '/org/freedesktop/Gypsy')
        self._lat = -1
        self._lng = -1
        self._alt = -1
        self._spe = -1
        self._user_speed_kmh = -1
        self._pdop = -1
        self._hdop = -1
        self._vdop = -1
        self._tstamp = -1

    def request(self):
        """Requests the GPS resource through /org/freesmartphone/Usage."""
        obj = dbus.SystemBus().get_object('org.freesmartphone.ousaged', '/org/freesmartphone/Usage')
        request = dbus.Interface(obj, 'org.freesmartphone.Usage').RequestResource('GPS')
        if (request == None):
            logging.info("GPS ressource succesfully requested (%s)." % request)
            return True
        else:
            logging.critical("ERROR requesting the GPS (%s)" % request)
            return False
    
    def get_GPS_data(self):
        """Returns Validity boolean, time stamp, lat, lng, alt, pdop, hdop, vdop."""
        logging.debug('Get GPS position')
        (fields, tstamp, lat, lng, alt) = dbus.Interface(self._dbusobj, 'org.freedesktop.Gypsy.Position').GetPosition()
        # From Python doc: The precision determines the number of digits after the decimal point and defaults to 6.
        # A difference of the sixth digit in lat/long leads to a difference of under a meter of precision.
        # Thus 6 is good enough.
        logging.debug('GPS position: fields (%d), lat (%f), lnt (%f), alt (%f)'
                      % (fields, lat, lng, alt))
        valid = True
        if fields != 7:
            valid = False
        (fields, pdop, hdop, vdop) = self._dbusobj.GetAccuracy(dbus_interface='org.freedesktop.Gypsy.Accuracy')
        logging.debug('GPS accuracy: fields (%d), pdop (%g), hdop (%g), vdop (%g)'
                      % (fields, pdop, hdop, vdop))
        if fields != 7:
            valid = False
        self._lat = lat
        self._lng = lng
        self._alt = alt
        self._pdop = pdop
        self._hdop = hdop
        self._vdop = vdop
        self._tstamp = tstamp
        return valid, tstamp, lat, lng, alt, pdop, hdop, vdop
        
    def get_course(self):
        """Return validity boolean, speed in knots, heading in decimal degree."""
        (fields, tstamp, speed, heading, climb) = self._dbusobj.GetCourse(dbus_interface='org.freedesktop.Gypsy.Course')
        logging.debug('GPS course: fields (%d), speed (%f), heading (%f)'
                      % (fields, speed, heading))
        if (fields & (1 << 0)) and (fields & (1 << 1)):
            return True, speed, heading
        return False, speed, heading


class ObmLogger():
    # Lock to access the OBM logs files
    fileToSendLock = threading.Lock()
    
    def __init__(self):
        self._gps = Gps()
        self._observers = []
        # is currently logging? Used to tell the thread to stop
        self._logging = False
        self._loggingThread = None
        self._bus = self.init_dbus()
        self._gsm = Gsm(self._bus)
        self._gsm.register(self)
        self._mcc = ""
        self._loggerLock = threading.Lock()
        # we will store every log in this list, until writing it to a file:
        self._logsInMemory = []
        # _logsInMemory is a list of strings, which will be concatenated to write to disk
        self._logsInMemoryLengthInByte = 0
        self._logFileHeader = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + \
        "<logfile manufacturer=\"%s\" model=\"%s\" revision=\"%s\" swid=\"FSOnen1\" swver=\"%s\">\n" \
        % ( self._gsm.get_device_info() + (config.SOFTWARE_VERSION,) )
        self._logFileTail = '</logfile>'
        
        # DEBUG = True if you want to activate GPS/Web connection simulation
        self.DEBUG = False
        if self.DEBUG:
            self.get_gps_data = self.simulate_gps_data
            #self.get_gsm_data = self.simulate_gsm_data

    def request_ressource(self, resource):
        """Requests the given string resource through /org/freesmartphone/Usage."""
        obj = self._bus.get_object('org.freesmartphone.ousaged', '/org/freesmartphone/Usage')
        request = dbus.Interface(obj, 'org.freesmartphone.Usage').RequestResource(resource)
        if (request == None):
            logging.info("'%s' resource succesfully requested (%s)." % (resource, request))
            return True
        else:
            logging.critical("ERROR requesting the resource '%s' (%s)" % (resource, request))
            return False
        
    def test_write_obm_log(self):
        self.write_obm_log(str(datetime.now()), 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
    
    def write_obm_log(self, date, tstamp, servingCell, lng, lat, alt, spe, heading, hdop, vdop, pdop, neighbourCells):
        """Format and stores in memory given data, possibly triggers writing in log file."""
        # From Python doc: %f -> The precision determines the number of digits after the decimal point and defaults to 6.
        # A difference of the sixth digit in lat/long leads to a difference of under a meter of precision.
        # Maximum error by rounding is 5. GPS precision is at best 10m. 2 x (maxError x error) = 2 x (5 x 1)
        # introduces an error of 10m! Thus we settle to 9.
        latLonPrecision = 9
        # http://gpsd.berlios.de/gpsd.html:
        # Altitude determination is more sensitive to variability to atmospheric signal lag than latitude/longitude,
        # and is also subject to errors in the estimation of local mean sea level; base error is 12 meters at 66%
        # confidence, 23 meters at 95% confidence. Again, this will be multiplied by a vertical dilution of
        # precision (VDOP).
        # Altitude is in meter.
        altitudePrecision = 1
        # speed is in km/h.
        speedPrecision = 3
        # Precision of 2 digits after the decimal point for h/p/v-dop is enough.
        hvpdopPrecision = 2
        # heading in decimal degrees
        headingPrecision = 9
        # log format, for release 0.2.0
        # "<gsm mcc=\"%s\" mnc=\"%s\" lac=\"%s\" id=\"%s\" ss=\"%i\"/>" % servingCell[:5]
        logmsg = "<scan time=\"%s\">" % date + \
        "<gsmserving mcc=\"%s\" mnc=\"%s\" lac=\"%s\" id=\"%s\" ss=\"%i\" act=\"%s\"" % servingCell[:6]
        if servingCell[6] != "":
            logmsg += " tav=\"%s\"" % servingCell[6]
        else:
            logging.debug("No timing advance available for serving cell, skip it.")
        if servingCell[7] != "":
            logmsg += " rxlev=\"%s\"" % servingCell[7]
        else:
            logging.debug("No rxlev available for serving cell, skip it.")
        logmsg += "/>"
         
        
        for cell in neighbourCells:
            # the best answer we could get was: it is highly probable that the neighbour cells have
            # the same MCC and MNC as the serving one, but this is not absolutely sure.
            logmsg += "<gsmneighbour mcc=\"%s\" mnc=\"%s\" lac=\"%s\"" % (servingCell[:2] + (cell['lac'],)) +\
            " id=\"%s\"" % cell['cid'] + \
            " rxlev=\"%i\"" % cell['rxlev'] + \
            " c1=\"%i\"" % cell['c1'] + \
            " c2=\"%i\"" % cell['c2'] + \
            "/>"
            #" ctype=\"%s\"" % cell['ctype'] + \
        
        logmsg += "<gps time=\"%s\"" % time.strftime('%Y%m%d%H%M%S', time.gmtime(tstamp)) + \
        " lng=\"%s\"" % ( ('%.*f' % (latLonPrecision, lng)).rstrip('0').rstrip('.') ) + \
        " lat=\"%s\"" % ( ('%.*f' % (latLonPrecision, lat)).rstrip('0').rstrip('.') ) + \
        " alt=\"%s\"" % ( ('%.*f' % (altitudePrecision, alt)).rstrip('0').rstrip('.') ) + \
        " hdg=\"%s\"" % ( ('%.*f' % (headingPrecision, heading)).rstrip('0').rstrip('.') ) + \
        " spe=\"%s\"" % ( ('%.*f' % (speedPrecision, spe)).rstrip('0').rstrip('.') ) + \
        " hdop=\"%s\"" % ( ('%.*f' % (hvpdopPrecision, hdop)).rstrip('0').rstrip('.') ) + \
        " vdop=\"%s\"" % ( ('%.*f' % (hvpdopPrecision, vdop)).rstrip('0').rstrip('.') ) + \
        " pdop=\"%s\"" % ( ('%.*f' % (hvpdopPrecision, pdop)).rstrip('0').rstrip('.') ) + \
        "/>" + \
        "</scan>\n"
        logging.debug(logmsg)
        self.fileToSendLock.acquire()
        logging.info('OpenBmap log file lock acquired.')
        #debug
        #self._gsm._call_ongoing = True
        #end of debug
        if self._gsm.call_ongoing():
            # see comments in log() about not logging in a call.
            logging.info('write_obm_log() canceled because a call is ongoing.')
            self.fileToSendLock.release()
            logging.info('OpenBmap log file lock released.')
            return

        maxLogsFileSize = config.get(config.GENERAL, config.MAX_LOGS_FILE_SIZE) * 1024

        if ( maxLogsFileSize > 0 ):
            # we use the max log file size as criterium to trigger write of file
            
            # we write ascii file, that is to say, one byte per character
            fileLengthInByte = len(self._logFileHeader) + len(logmsg) \
            + self._logsInMemoryLengthInByte + len(self._logFileTail)

            if (fileLengthInByte <= maxLogsFileSize):
                logging.debug('Current size of logs in memory %i bytes, max size of log files is %i bytes.'
                              % (fileLengthInByte, maxLogsFileSize))
            else:
                self.write_obm_log_to_disk_unprotected()
            self._logsInMemory.append(logmsg)
            self._logsInMemoryLengthInByte += len(logmsg)
        else:
            self._logsInMemory.append(logmsg)
            self._logsInMemoryLengthInByte += len(logmsg)
            if len(self._logsInMemory) < config.get(config.GENERAL, config.NB_OF_LOGS_PER_FILE):
                logging.debug('Max logs per file (%i/%i) not reached, wait to write to a file.'
                              % (len(self._logsInMemory), config.get(config.GENERAL, config.NB_OF_LOGS_PER_FILE)))
            else:
                self.write_obm_log_to_disk_unprotected()

        self.fileToSendLock.release()
        logging.info('OpenBmap log file lock released.')

    def write_obm_log_to_disk(self):
        """Gets the Lock and then calls write_obm_log_to_disk_unprotected()."""
        self.fileToSendLock.acquire()
        logging.info('OpenBmap log file lock acquired by write_obm_log_to_disk().')
        self.write_obm_log_to_disk_unprotected()
        self.fileToSendLock.release()
        logging.info('OpenBmap log file lock released by write_obm_log_to_disk().')

    def write_obm_log_to_disk_unprotected(self):
        """Takes the logs already formatted in memory and write them to disk. Clears the log in memory.

        Warning: this method is not protected by a Lock!
        """

        if len(self._logsInMemory) == 0:
            logging.debug('No log to write to disk, returning.')
            return

        now = datetime.now()
        #"yyyyMMddHHmmss"
        date = now.strftime("%Y%m%d%H%M%S")

        logDir = config.get(config.GENERAL, config.OBM_LOGS_DIR_NAME)
        # at the moment: log files follow: logYYYYMMDDhhmmss.xml
        # log format, for release 0.2.0
        # filename = os.path.join(logDir, 'log' + date + '.xml')
        # new filename format VX_MCC_logYYYYMMDDhhmmss.xml
        mcc = self._logsInMemory[0]
        # len('mcc="') = 5
        mcc = mcc[mcc.find("mcc=") + 5 : ]
        mcc = mcc[ : mcc.find('"')]
        filename = os.path.join(logDir, config.XML_LOG_VERSION + '_' + mcc + '_log' + date + '.xml')
        logmsg = self._logFileHeader
        for log in self._logsInMemory:
            logmsg += log
        #TODO: escaped characters wich would lead to malformed XML document (e.g. '"')
        logmsg += self._logFileTail
        logging.debug('Write logs to file: %s' % logmsg)
        try:
            file = open(filename, 'w')
            file.write(logmsg)
            file.close()
            self._logsInMemory[:] = []
            self._logsInMemoryLengthInByte = 0
        except Exception, e:
            logging.error("Error while writing GSM/GPS log to file: %s" % str(e))
        
    def send_logs(self):
        """Try uploading available log files to OBM database.
        
        Returns (b, i, i):
        True if nothing wrong happened.
        The total number of successfully uploaded files.
        The total number of files available for upload.
        """
        totalFilesToUpload = 0
        totalFilesUploaded = 0
        result = True
        
        # to store the data once sent:
        dirProcessed = os.path.join(config.get(config.GENERAL, config.OBM_PROCESSED_LOGS_DIR_NAME))
        logsDir = config.get(config.GENERAL, config.OBM_LOGS_DIR_NAME)
        
        self.fileToSendLock.acquire()
        logging.info('OpenBmap log file lock acquired.')
        try:
            if not self.check_obm_api_version():
                logging.error('We do not support the server API version,' + \
                              'do you have the latest version of the software?')
                return (False, -1, -1)
            os.chdir(logsDir)
            for f in os.listdir(logsDir):
                totalFilesToUpload += 1
                logging.info('Try uploading \'%s\'' % f)
                fileRead = open(f, 'r')
                content = fileRead.read()
                fileRead.close()
                (status, reason, resRead) = Upload.post_url(config.get(config.GENERAL, config.OBM_UPLOAD_URL),
                                                            [('openBmap_login', config.get(config.CREDENTIALS, config.OBM_LOGIN)),
                                                            ('openBmap_passwd', config.get(config.CREDENTIALS, config.OBM_PASSWORD))],
                                                            [('file', f, content)])
                logging.debug('Upload response status:%s, reason:%s, body:%s' % (status, reason, resRead))
                if resRead.startswith('Stored in'):
                    newName = os.path.join(dirProcessed, f)
                    os.rename(f, newName)
                    logging.info('File \'%s\' successfully uploaded. Moved to \'%s\'. Thanks for contributing!' %
                                 (f, newName))
                    totalFilesUploaded += 1
                elif resRead.strip(' ').endswith('already exists.'):
                    # We assume the file has already been uploaded...
                    newName = os.path.join(dirProcessed, f)
                    os.rename(f, newName)
                    logging.info('File \'%s\' probably already uploaded. Moved to \'%s\'. Thanks for contributing!' %
                                 (f, newName))
                else:
                    logging.error('Unable to upload file \'%s\'.' % f)
                    result = False
        except Exception, e:
            logging.error("Error while sending GSM/GPS logged data: %s" % str(e))
            return (False, totalFilesUploaded, totalFilesToUpload)
        finally:
            self.fileToSendLock.release()
            logging.info('OpenBmap log file lock released.')
        return (result, totalFilesUploaded, totalFilesToUpload)

    def delete_processed_logs(self):
        """Deletes all the files located in the 'processed' folder. Returns number deleted."""
        # no Lock used here, I don't see this needed for Processed logs...
        dirProcessed = os.path.join(config.get(config.GENERAL, config.OBM_PROCESSED_LOGS_DIR_NAME))
        deletedSoFar = 0
        for f in os.listdir(dirProcessed):
            toBeDeleted = os.path.join(dirProcessed, f)
            os.remove(toBeDeleted)
            deletedSoFar += 1
            logging.info('Processed log file \'%s\' has been deleted.' % toBeDeleted)
        return deletedSoFar
        
    def check_obm_api_version(self):
        """Get the current openBmap server API version, and return True if it corresponds."""
        logging.debug('Checking the openBmap server interface Version...')
        if self.DEBUG:
            # simulation
            return True
        try:
            logging.info('We support API version: %s.' % config.get(config.GENERAL, config.OBM_API_VERSION))
            response = urllib2.urlopen(config.get(config.GENERAL, config.OBM_API_CHECK_URL))
            for line in response:
                if line.startswith('MappingManagerVersion='):
                    version_string, val = line.split('=')
                    val = val.strip(' \n')
                    logging.info('Server API version: %s.' % val)
                    if  val == config.get(config.GENERAL, config.OBM_API_VERSION):
                        return True
        except Exception, e:
            logging.error(str(e))
        return False
        
    def init_dbus(self):
        """initialize dbus"""
        logging.debug("trying to get bus...")
        try:
            bus = dbus.SystemBus()
        except Exception, e:
            logging.error( "Can't connect to dbus: %s" % e )
        logging.debug("ok")
        return bus
    
    def init_openBmap(self):
        self._gps.request()
        # this is intended to prevent the phone to go to suspend
        self.request_ressource('CPU')
        
        logDir = config.get(config.GENERAL, config.OBM_LOGS_DIR_NAME)
        if not os.path.exists(logDir):
            logging.info('Directory for storing cell logs does not exists, creating \'%s\'' % 
                         logDir)
            os.mkdir(logDir)
                
        # to store the data once sent:
        dirProcessed = os.path.join(config.get(config.GENERAL, config.OBM_PROCESSED_LOGS_DIR_NAME))
        if not os.path.exists(dirProcessed):
            logging.info('Directory for storing processed cell logs does not exists, creating \'%s\'' % dirProcessed)
            os.mkdir(dirProcessed)
            
        # request the current status. If we are connected we get the data now. Otherwise
        # we would need to wait for a signal update.
        self._gsm.get_status()
        
        # check if we have no ongoing call...
        self._gsm.call_status_handler(None)

    def exit_openBmap(self):
        """Puts the logger in a nice state for exiting the application.

        * Saves logs in memory if any."""
        self.write_obm_log_to_disk()

    def log(self):
        logging.debug("OpenBmap logger runs.")
        self._loggerLock.acquire()
        logging.debug('OBM logger locked by log().')
        scanSpeed = config.get(config.GENERAL, config.SCAN_SPEED_DEFAULT)
        minSpeed = config.get(config.GENERAL, config.MIN_SPEED_FOR_LOGGING)
        maxSpeed = config.get(config.GENERAL, config.MAX_SPEED_FOR_LOGGING)


        startTime = datetime.now()
        now = datetime.now();
        logging.debug("Current date and time is: %s" % now)
        #("yyyy-MM-dd HH:mm:ss.000");
        #adate = now.strftime("%Y-%m-%d %H-%M-%S.")
        # "%f" returns an empty result... so we compute ms by ourself.
        #adate += str(now.microsecond/1000)[:3]
        #logging.debug("LogGenerator - adate = " + adate)
        #"yyyyMMddHHmmss"
        adate2 = now.strftime("%Y%m%d%H%M%S")
        logging.debug("LogGenerator - adate2 = " + adate2)
        #ToString("dd MM yyyy") + " at " + dt.ToString("HH") + ":" + dt.ToString("mm");
        #adate3 = now.strftime("%d %m %Y at %H:%M")
        #logging.debug("LogGenerator - adate3 = " + adate3)

        if self._gsm.call_ongoing():
            # When a call is ongoing, the signal strength diminishes
            # (without a DBus signal to notify it), and neighbour cells data returned is garbage:
            # thus we do not log during a call.
            # I fear that when the framework notifies this program about call status change, some
            # time has passed since the modem has taken it into account. This could result in effects
            # described above (e.g. the neighbour cells data we have read is already garbage), but as
            # we still have
            # not received and taken into account the call, we don't know that the data is bad. To
            # prevent this, I check just before reading the data, and I will check again just before
            # writing it, hoping to have let enough time to never see the (possible?) situation
            # described above.
            logging.info('Log canceled because a call is ongoing.')
        else:
            (validGps, tstamp, lat, lng, alt, pdop, hdop, vdop, spe, heading) = self.get_gps_data()
            (validGsm, servingCell, neighbourCells) = self.get_gsm_data()
            # the test upon the speed, prevents from logging many times the same position with the same cell.
            # Nevertheless, it also prevents from logging the same position with the cell changing...
            if spe < minSpeed:
                logging.info('Log rejected because speed (%g) is under minimal speed (%g).' % (spe, minSpeed))
            elif spe > maxSpeed:
                logging.info('Log rejected because speed (%g) is over maximal speed (%g).' % (spe, maxSpeed))
            elif validGps and validGsm:
                self.write_obm_log(adate2, tstamp, servingCell, lng, lat, alt, spe, heading, hdop, vdop, pdop,
                                   neighbourCells)
            else:
                logging.info('Data were not valid for creating openBmap log.')
                logging.debug("Validity=%s, MCC=%s, MNC=%s, lac=%s, cid=%s, strength=%i, act=%s, tav=%s, rxlev=%s"
                              % ((validGsm,) + servingCell) )
                logging.debug("Validity=%s, lng=%f, lat=%f, alt=%f, spe=%f, hdop=%f, vdop=%f, pdop=%f" \
                              % (validGps, lng, lat, alt, spe, hdop, vdop, pdop))
        
            self.notify_observers()
        duration = datetime.now() - startTime
        logging.info("Logging loop ended, total duration: %i sec)." % duration.seconds)

        if not self._logging:
            logging.debug('Logging loop is stopping.')
            self._loggingThread = None
        else:
            logging.debug('Next logging loop scheduled in %d seconds.' % scanSpeed)
        # storing in 'result' prevents modification of the return value between
        # the lock release() and the return statement.
        result = self._logging
        self._loggerLock.release()
        logging.debug('OBM logger lock released by log().')
        # together with timeout_add(). self._logging is True if it must keep looping.
        return result
        
    def start_logging(self):
        """Schedules a call to the logging method, using the scanning time."""
        if not self._loggerLock.acquire(False):
            logging.debug('OBM logger is already locked. Probably already running. Returning...')
            return
        logging.debug('OBM logger locked by start_logging().')
        if self._logging:
            logging.debug('OBM logger is already running.')
        else:
            self._logging = True
            scanSpeed = config.get(config.GENERAL, config.SCAN_SPEED_DEFAULT)
            self._loggingThread = gobject.timeout_add_seconds( scanSpeed, self.log )
            logging.info('OBM logger scheduled every %i second(s).' % scanSpeed)
        # be sure to notify as soon as possible the views, for better feedback
        self.notify_observers()
        self._loggerLock.release()
        logging.debug('OBM logger lock released by start_logging().')
    
    def stop_logging(self):
        """Stops the logging method to be regularly called."""
        if not self._loggerLock.acquire(False):
            logging.debug('OBM logger is already locked. Probably already running.')
            gobject.idle_add(self.stop_logging, )
            logging.info('OBM logger currently locked. Will retry stopping it later.')
        else:
            logging.debug('OBM logger locked by stop_logging().')
            self._logging = False
            logging.debug('Requested logger to stop.')
            self._loggerLock.release()
            logging.debug('OBM logger lock released by stop_logging().')
        
    #===== observable interface =======
    def register(self, observer):
        """Called by observers to be later notified of changes."""
        self._observers.append(observer)
        
    def notify_observers(self):
        for obs in self._observers:
            gobject.idle_add(obs.notify, )
        
        
    def get_gsm_data(self):
        """Returns Fields validity boolean, MCC, MNC, lac, cid, signal strength, tuple of neighbour cells dictionaries.
        
        Each neighbour cell dictionary contains lac and cid fields.
        They may contain rxlev, c1, c2, and ctype.
        If MCC has changed, triggers writing of log file.
        """
        
        result = self._gsm.get_gsm_data()
        currentMcc = result[1][0]
        if currentMcc != self._mcc:
            # as soon as we have changed from MCC (thus from country), we save the logs because
            # for now the log files have the MCC in their name, to make easy to dispatch them.
            # Thus, a log file is supposed to contain only one MCC related data.
            logging.info("MCC has changed from '%s' to '%s'." % (self._mcc, currentMcc))
            self.write_obm_log_to_disk()
            self._mcc = currentMcc
        else:
            logging.debug("MCC unchanged (was '%s', is '%s')" % (self._mcc, currentMcc))
        return result
        
    def get_gps_data(self):
        """Return validity boolean, time stamp, lat, lng, alt, pdop, hdop, vdop, speed in km/h, heading."""
        (valPos, tstamp, lat, lng, alt, pdop, hdop, vdop) = self._gps.get_GPS_data()
        (valSpe, speed, heading) = self._gps.get_course()
        # knots * 1.852 = km/h
        return (valPos and valSpe, tstamp, lat, lng, alt, pdop, hdop, vdop, speed * 1.852, heading)
    
    def get_credentials(self):
        """Returns openBmap login, password."""
        return (config.get(config.CREDENTIALS, config.OBM_LOGIN),
                config.get(config.CREDENTIALS, config.OBM_PASSWORD))

    def set_credentials(self, login, password):
        """Sets the given login and password, saves the config file."""
        config.set(config.CREDENTIALS, config.OBM_LOGIN, login)
        config.set(config.CREDENTIALS, config.OBM_PASSWORD, password)
        config.save_config()
        logging.info('Credentials set to \'%s\', \'%s\'' % (login, password) )

    def is_logging(self):
        """Returns True if the logger is running, False otherwise."""
        self._loggerLock.acquire()
        logging.debug('OBM logger locked by is_logging().')
        result = (self._loggingThread != None)
        logging.debug('Is the logger running? %s' % (result and 'Yes' or 'No') )
        self._loggerLock.release()
        logging.debug('OBM logger lock released by is_logging().')
        return result
    #===== end of observable interface =======

    #===== observer interface =======
    def notify(self):
        """This method is used by observed objects to notify about changes."""
        self.notify_observers()
    #===== end of observer interface =======
            
    def simulate_gps_data(self):
        """Return simulated validity boolean, time stamp, lat, lng, alt, pdop, hdop, vdop, speed in km/h, heading."""
        return (True, 345678, 2.989123456923999, 69.989123456123444, 2.896, 6.123, 2.468, 3.1, 3.456, 10)
    
    def simulate_gsm_data(self):
        """Return simulated Fields validity boolean, (MCC, MNC, lac, cid, signal strength, act), neighbour cells."""
        return (True, ('208', '1', '123', '4', -123, 'GSM'), (
                                                              {'mcc':'123',
                                                               'mnc':'02',
                                                               'cid':'123',
                                                               'rxlev':456,
                                                               'c1':-123,
                                                               'c2':-234,
                                                               'ctype':'GSM'}))
        
#----------------------------------------------------------------------------#
# program starts here
#----------------------------------------------------------------------------#
dbus.mainloop.glib.DBusGMainLoop( set_as_default=True )

if not os.path.exists(Config.APP_HOME_DIR):
    print('Main directory does not exists, creating \'%s\'' % 
                         Config.APP_HOME_DIR)
    os.mkdir(Config.APP_HOME_DIR)
            
logging.basicConfig(filename=Config.TEMP_LOG_FILENAME,
            level=logging.DEBUG,
            filemode='w',)
config = Config()

if __name__ == '__main__':
    #obmlogger = ObmLogger()
    #obmlogger.init_openBmap()
    
    mainloop = gobject.MainLoop()
    try:
        # start main loop, to receive DBus signals
        mainloop.run()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupted, exiting...")
        mainloop.quit()
    else:
        logging.info("normal exit.")
        sys.exit( 0 )