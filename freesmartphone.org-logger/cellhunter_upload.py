from xml.dom import minidom
import os,dbus,urllib
"""
OBMhunter submitter 0.1.0  <maxious at lambdacomplex.org>
Submits appropriate openBMap xml logs to cellhunter DB.

Installation:
Patch the openBMap logger library:
patch < obm_hunter-logger.py.patch

Change the group name (gname), group password (gpass) and device id (a 
random number - check .cellhunter.conf if you want to be consistent) if
you want your results to count for a group's score. Otherwise leave 
defaults to remain anonymous.

Then just run the OBM logger as usual but you have to run this script after collecting the logs
but before you move them to the Processed Logs folder in OBM. So I do it before I do Upload in 
the OBM logger app.
"""
gname=""
gpass=""
device_id=0

bus = dbus.SystemBus()
ogsmd_obj = bus.get_object( "org.freesmartphone.ogsmd", "/org/freesmartphone/GSM/Device" )
ogsmd_network_iface = dbus.Interface( ogsmd_obj, "org.freesmartphone.GSM.Network" )
data = ogsmd_network_iface.GetStatus()
provider = urllib.quote(data['provider'])


path="/home/root/.openBmap/Logs/"
dirList=os.listdir(path)
for fname in dirList:
	print "Processing " + fname
	dom = minidom.parse(path + fname)
	for scannode in dom.getElementsByTagName("scan"):
		for gpsnode in scannode.getElementsByTagName("gps"):
			time = int(gpsnode.getAttribute("time"))
			lat  = float(gpsnode.getAttribute("lat"))
			long = float(gpsnode.getAttribute("lng"))
			alt  = float(gpsnode.getAttribute("alt"))
		for child in scannode.childNodes:
			if "gsm" in child.tagName:
				cell_mcc   = int(child.getAttribute("mcc"))
				cell_mnc   = int(child.getAttribute("mnc"))
				cell_la    = int(child.getAttribute("lac"))
				cell_id    = int(child.getAttribute("id"))
				if (child.getAttribute("rxlev") != "") & (child.getAttribute("arfcn") != ""):
					signal     = int(child.getAttribute("rxlev"))
					cell_arfcn = int(child.getAttribute("arfcn"))
					serving    = 1 if (child.tagName == "gsmserving") else 0
					URL = "http://ch.omoco.de/cellhunter/submit.php?provider=%s&cell_mcc=%d&cell_mnc=%d&cell_la=%x&cell_id=%x&signal=%d&time=%d&lat=%f&long=%f&alt=%f&gname=%s&gpass=%s&device_id=%d&cell_arfcn=%d&serving=%d " %(provider, cell_mcc,cell_mnc,cell_la,cell_id,signal,time,lat,long,alt,gname,gpass,device_id,cell_arfcn,serving)	
					os.system('wget --user-agent "OBMhunter 0.1.0 offline <maxious at lambdacomplex.org>" -q --output-document=- \"' + URL + '\"')
					print "\n"
	
