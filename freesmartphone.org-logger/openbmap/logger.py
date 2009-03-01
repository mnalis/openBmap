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
        self._MCC = ''
        self._MNC = ''
        self._registrationGSM = ''
        
        self._manufacturer = 'N/A'
        self._model = 'N/A'
        self._revision = 'N/A'
        self.get_device_info()
        self._observers = []
        
        if bus:
            bus.add_signal_receiver(self.network_status_handler,
                                          'Status',
                                          'org.freesmartphone.GSM.Network',
                                          'org.freesmartphone.ogsmd',
                                          '/org/freesmartphone/GSM/Device')

    def network_status_handler(self, data, *args, **kwargs):
        """Handler for org.freesmartphone.GSM.Network.Status signal.
        
        MCC, MNC, lac, cid and signal strengh are received asynchronuously through this signal/handler.
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
                    
            if "lac" and "cid" and "strength" and "code" in data:
                self._MCC = (str(data['code'])[:3]).lstrip('0')
                self._MNC = (str(data['code'])[3:]).lstrip('0')
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
                    val_from_modem = int( round(math.exp(data["strength"] * math.log( 31 ) /100)) )
                    # translate to dBm (see 3GPP documentation TS 07.07 Chapter 8.5, GSM 07.07 command +CSQ)
                    self._strength = val_from_modem * 2 - 113 
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

    def empty_GSM_data(self):
        """Empty all the local GSM related variables."""
        self._lac = ''
        self._cid = ''
        self._MCC = ''
        self._MNC = ''
        self._strength = 0
        self._registrationGSM = ''
    
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
        return (self._strength >= -113 and self._strength <= -53)
    
    def get_gsm_data(self):
        """Return validity boolean, MCC, MNC, lac, cid, signal strength.
        
        Operation is atomic, values cannot be modified while reading it.
        The validity boolean is True when all fields are valid and consistent,
        False otherwise."""
        logging.debug("Wait for reading GSM data.")
        self.acquire_lock()
        logging.debug("Lock acquired, reading GSM data.")
        (valid, mcc, mnc, lac, cid, strength) = (self.check_GSM(),
                                                 self._MCC,
                                                 self._MNC,
                                                 self._lac,
                                                 self._cid,
                                                 self._strength)
        logging.info("valid=%s, MCC=%s, MNC=%s, lac=%s, cid=%s, strength=%s" %
                     (valid, mcc, mnc, lac, cid, strength)) 
        self.release_lock()
        logging.debug("GSM data read, lock released.")
        return (valid, mcc, mnc, lac, cid, strength)
    
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
        self.NB_OF_LOGS_PER_FILE = 'Number of logs per file'
        
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
                
                config.add_section(self.CREDENTIALS)
                config.set(self.CREDENTIALS, self.OBM_LOGIN, 'your_login')
                config.set(self.CREDENTIALS, self.OBM_PASSWORD, 'your_password')
                           
        return config
        
    def get(self, section, option):
        try:
            if option in [self.SCAN_SPEED_DEFAULT,
                          self.MIN_SPEED_FOR_LOGGING,
                          self.MAX_SPEED_FOR_LOGGING,
                          self.NB_OF_LOGS_PER_FILE]:
                return self._config.getint(section, option)
            else:
                return self._config.get(section, option)
        except Exception, e:
            logging.critical("get_option() does not find (%s / %s). This is much probably a bug." % (section, option))
            logging.critical(str(e))
            #TODO: well in case this happens, this should be forwarded to Views (GUI) in order to inform the user
            sys.exit(-1)
        
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
        self._loggerLock = threading.Lock()
        # we will store every log in this list, until writing it to a file:
        self._logsInMemory = []
        
        # DEBUG = True if you want to activate GPS/Web connection simulation
        self.DEBUG = False
        if self.DEBUG:
            self.get_gps_data = self.simulate_gps_data
            self.get_gsm_data = self.simulate_gsm_data

    def test_write_obm_log(self):
        self.write_obm_log(str(datetime.now()), 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
    
    def write_obm_log(self, date, tstamp, mcc, mnc, lac, cellid, rssi, lng, lat, alt, spe, heading, hdop, vdop, pdop):
        """Write the OpenBMap log file."""
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
        logmsg = "<scan time=\"%s\">" % time.strftime('%Y%m%d%H%M%S', time.gmtime(tstamp)) + \
        "<gsm mcc=\"%s" % mcc + \
        "\" mnc=\"%s\"" % mnc + \
        " lac=\"%s\"" % lac +\
        " id=\"%s\"" % cellid + \
        " ss=\"%i\"" % rssi + \
        "/>" + \
        "<gps time=\"%s\"" % date + \
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
        self._logsInMemory.append(logmsg)
        if len(self._logsInMemory) < config.get(config.GENERAL, config.NB_OF_LOGS_PER_FILE):
            logging.debug('Max logs per file not reached, wait to write to a file.')
        else:
            logDir = config.get(config.GENERAL, config.OBM_LOGS_DIR_NAME)
            
            # at the moment: log files follow: logYYYYMMDDhhmmss.xml
            filename = os.path.join(logDir, 'log' + date + '.xml')
            # if the file does not exist, we start it with the "header"
            logmsg = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + \
            "<logfile manufacturer=\"%s\" model=\"%s\" revision=\"%s\">\n" % self._gsm.get_device_info()
            for log in self._logsInMemory:
                logmsg += log
        #TODO: escaped characters wich would lead to malformed XML document (e.g. '"')
        # TODO: manage the closing logfile mark at the end of the file        
            logmsg += '</logfile>'
            logging.debug('Logs: %s' % logmsg)
            try:
                file = open(filename, 'w')
                file.write(logmsg)
                file.close()
                self._logsInMemory[:] = []
            except Exception, e:
                logging.error("Error while writing GSM/GPS log to file: %s" % str(e))
        self.fileToSendLock.release()
        logging.info('OpenBmap log file lock released.')    
        
        
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

        (validGps, tstamp, lat, lng, alt, pdop, hdop, vdop, spe, heading) = self.get_gps_data()
        (validGsm, MCC, MNC, lac, cid, strength) = self.get_gsm_data()
        # the test upon the speed, prevents from logging many times the same position with the same cell.
        # Nevertheless, it also prevents from logging the same position with the cell changing...
        if spe < minSpeed:
            logging.info('Log rejected because speed (%g) is under minimal speed (%g).' % (spe, minSpeed))
        elif spe > maxSpeed:
            logging.info('Log rejected because speed (%g) is over maximal speed (%g).' % (spe, maxSpeed))
        elif validGps and validGsm:
            self.write_obm_log(adate2, tstamp, MCC, MNC, lac, cid, strength, lng, lat, alt, spe, heading, hdop, vdop, pdop)
        else:
            logging.info('Data were not valid for creating openBmap log.')
            logging.debug("Validity=%s, MCC=%s, MNC=%s, lac=%s, cid=%s, strength=%i"
                          % (validGsm, MCC, MNC, lac, cid, strength))
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
        """Return Fields validity boolean, MCC, MNC, lac, cid, signal strength."""
        return self._gsm.get_gsm_data()
        
    def get_gps_data(self):
        """Return validity boolean, time stamp, lat, lng, alt, pdop, hdop, vdop, speed in km/h, heading."""
        (valPos, tstamp, lat, lng, alt, pdop, hdop, vdop) = self._gps.get_GPS_data()
        (valSpe, speed, heading) = self._gps.get_course()
        # knots * 1.852 = km/h
        return (valPos and valSpe, tstamp, lat, lng, alt, pdop, hdop, vdop, speed * 1.852, heading)
    
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
        """Return simulated Fields validity boolean, MCC, MNC, lac, cid, signal strength."""
        return (True, '208', '1', '123', '4', -123)
        
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