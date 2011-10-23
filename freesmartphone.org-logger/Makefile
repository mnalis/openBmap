.PHONY: dist force-dist release clean distclean builddist source shr-t-ipk updateversion checkdistversion 

dist: clean release builddist
	@echo 
	@echo "Build done for version `cat VERSION`"
	@echo
	
force-dist: clean updateversion builddist
	@echo
	@echo "WARNING: not checking odd/even version for build (devel only!) - version `cat VERSION` (Branch `cat VERSIONB`)"
	@echo

release: updateversion checkdistversion

clean:
	python setup.py clean --all
	rm -rf build tmp
	rm -f *~ openbmap/*~ openbmap/plugins/*~
	rm -f openbmap/*.py[oc] openbmap/plugins/*.py[oc]
	
distclean: clean
	rm -rf dist	

# you should never run targets below this line manually

builddist: source shr-t-ipk

source:
	python setup.py sdist

# this target allows us to build .ipk without whole the OpenMoko devel environment
shr-t-ipk:
	rm -rf tmp
	mkdir -p tmp/root/DEBIAN
	python setup.py install --root tmp/root --install-layout=deb --install-lib=usr/lib/python2.6/site-packages  --no-compile --optimize=1
	
	echo "Package: openbmap-logger" > tmp/root/DEBIAN/control
	echo "Version: `cat VERSION`-r1.0" >> tmp/root/DEBIAN/control
	echo "Description: openBmap logger and uploader of GPS/GSM data" >> tmp/root/DEBIAN/control
	echo "Section: x11/utils" >> tmp/root/DEBIAN/control
	echo "Priority: optional" >> tmp/root/DEBIAN/control
	echo "Maintainer: Matija Nalis <mnalis-openmoko@voyager.hr>" >> tmp/root/DEBIAN/control
	echo "License: GPLv3" >> tmp/root/DEBIAN/control
	#echo "Architecture: armv7a" >> tmp/root/DEBIAN/control
	# should this actually be "any" and not "all"?
	echo "Architecture: all" >> tmp/root/DEBIAN/control
	echo "OE: openbmap-logger" >> tmp/root/DEBIAN/control
	echo "Homepage: http://www.openbmap.org/" >> tmp/root/DEBIAN/control
	echo "Build: `cat VERSIONB`" >> tmp/root/DEBIAN/control
	echo "Depends: python, python-dbus, python-pygobject, python-pygtk, libglade-2.0-0, python-subprocess, python-netclient, python-math, python-core, python-io, frameworkd" >> tmp/root/DEBIAN/control
	echo "Source: http://sourceforge.net/projects/myposition/files/openBmap%20Freesmartphone.org%20client/`cat VERSION`/openbmap-logger-`cat VERSION`.tar.gz" >> tmp/root/DEBIAN/control

	fakeroot dpkg-deb --build tmp/root dist/openbmap-logger_`cat VERSION`-r1.0_all.ipk


updateversion:
	@sed -ne '1s,^Version \(.*\) (.*$$,\1,p' CHANGELOG > VERSION
	@git branch -v | sed -ne 's,^\* \([^ ]*\)  *\([a-f0-9]*\) .*$$,\1/\2,p' > VERSIONB
	@grep -q  '^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$$' VERSION || (echo "ERROR: Can't detect correct version from CHANGELOG: `cat VERSION`"; exit 1)
	sed -i -e "s/self.SOFTWARE_VERSION = '.*'/self.SOFTWARE_VERSION = '`cat VERSION`'/" openbmap/logger.py
	sed -i -e "s/version='.*',/version='`cat VERSION`',/" setup.py
	sed -i -e "s/Version=.*/Version=`cat VERSION`/" openBmap.desktop

checkdistversion:
	@VERSION=`cat VERSION` ; [ $$(( $${VERSION##*.} %2 )) -eq 0 ] || (echo "ERROR: odd version number indicates development, aborting release build! Use force-dist for devel"; exit 2)
	@README=`sed -ne "1s/^openBmap logger version \(.*\) (.*/\1/p" README`; VERSION=`cat VERSION`; [ "$$README" = "$$VERSION" ] || (echo "ERROR: versions mismatch: README says $$README, CHANGELOG says $$VERSION"; exit 3)
	@echo
	@echo "Versions $$VERSION (Branch `cat VERSIONB`) OK, don't forget to commit auto-modified code to git and 'git tag' release!"
	@echo
	
