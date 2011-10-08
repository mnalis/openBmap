.PHONY: all dist force-dist release builddist shr-t-ipk clean updateversion checkdistversion

all: dist clean

dist: clean release builddist
	@echo 
	@echo "Build done for version `cat VERSION`"
	@echo
	
force-dist: clean updateversion builddist
	@echo
	@echo "WARNING: not checking odd/even version for build (devel only!) - version `cat VERSION`"
	@echo

release: updateversion checkdistversion

clean:
	python setup.py clean
	rm -rf build tmp

# you should never run targets below this line manually

builddist: shr-t-ipk

shr-t-ipk:
	echo FIXME build shr-T .IPK


updateversion:
	@sed -ne '1s,^Version \(.*\) (.*$$,\1,p' CHANGELOG > VERSION
	@grep -q  '^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$$' VERSION || (echo "ERROR: Can't detect correct version from CHANGELOG: `cat VERSION`"; exit 1)
	sed -i -e "s/self.SOFTWARE_VERSION = '.*'/self.SOFTWARE_VERSION = '`cat VERSION`'/" openbmap/logger.py
	sed -i -e "s/version='.*',/version='`cat VERSION`',/" setup.py
	sed -i -e "s/Version=.*/Version=`cat VERSION`/" openBmap.desktop

checkdistversion:
	@VERSION=`cat VERSION` ; [ $$(( $${VERSION##*.} %2 )) -eq 0 ] || (echo "ERROR: odd version number indicates development, aborting release build! Use force-dist for devel"; exit 2)
	@README=`sed -ne "1s/^openBmap logger version \(.*\) (.*/\1/p" README`; VERSION=`cat VERSION`; [ "$$README" = "$$VERSION" ] || (echo "ERROR: versions mismatch: README says $$README, CHANGELOG says $$VERSION"; exit 3)
	@echo
	@echo "Versions $$VERSION OK, don't forget to commit auto-modified code to git and 'git tag' release!"
	@echo
	
