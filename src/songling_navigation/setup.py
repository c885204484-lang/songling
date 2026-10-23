from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'songling_navigation'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py') + glob('launch/*.yaml')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'urdf'), glob('urdf/*.urdf')), 
        (os.path.join('share', package_name, 'behavior_trees'), glob('behavior_trees/*.xml')),
        (os.path.join('share', package_name, 'web', 'offline_nav'), glob('web/offline_nav/*')),
        (os.path.join('share', package_name, 'maps', 'xidian_hangzhou'), glob('maps/xidian_hangzhou/*')),
        (os.path.join('share', package_name), ['OFFLINE_NAVIGATION.md']),
        (os.path.join('lib', package_name), glob('scripts/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='nvidia',                
    maintainer_email='nvidia@todo.todo',  
    description='GPS navigation for Songling robot',
    license='Apache License 2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            'offline_map_editor = songling_navigation.offline_nav.server:main',
            'offline_demo_robot = songling_navigation.offline_nav.demo:main',
        ],
    },
)
