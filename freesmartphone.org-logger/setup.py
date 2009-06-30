from distutils.core import setup
import glob
    
setup(name='openbmap-logger',
        version='0.3.2',
        description='GPS and GSM logger for openBmap.',
        author='Onen',
        author_email='onen.om@free.fr',
        url='http://www.openbmap.org',
        download_url='http://sourceforge.net/project/showfiles.php?group_id=218065&package_id=310952',
        classifiers=[
            'Development Status :: 5 - Production/Stable',
            'Environment :: X11 Applications :: GTK',
            'Intended Audience :: End Users/Desktop',
            'License :: OSI Approved :: GNU General Public License (GPL)',
            'Operating System :: POSIX :: Linux',
            'Programming Language :: Python',
            'Topic :: Scientific/Engineering :: GIS',
            ],
        package_dir= {'openbmap':'openbmap'},
        packages=['openbmap'],
        data_files=[('share/applications', ['openBmap.desktop']),
                    ('share/openBmap', ['AUTHORS', 'CHANGELOG', 'README',
                                        'ExitButton.png', 'GenerateButton.png',
                                        'StopButton.png', 'UploadButton.png',
                                        'Main.glade',
                                        'gpl.txt', 'lgpl.txt' ]),
                    ('share/pixmaps', ['openBmap-desktop.png'])
                    ],
        scripts = ['openBmapGTK']
     )
