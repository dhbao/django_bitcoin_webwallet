#!/usr/bin/env python
import os
from setuptools import setup

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='django_bitcoin_webwallet',
    version='0.1',
    packages=['bitcoin_webwallet'],
    include_package_data=True,
    license='MIT License',
    description='Deterministic Bitcoin wallets for multi user Django apps. Internal transactions are made off chain.',
    author='Henrik Heino',
    author_email='henrik.heino@gmail.com',
    install_requires=[
        'django-cron',
        'pycoin',
        'pytz',
    ],
    dependency_links=[
        'git://github.com/jgarzik/python-bitcoinrpc.git#egg=python-bitcoinrpc',
    ],
)
