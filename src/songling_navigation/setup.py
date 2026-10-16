from setuptools import setup
import os
from glob import glob

package_name = 'songling_navigation'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],   # 明确指定唯一的Python包
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'urdf'), glob('urdf/*.urdf')), 
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
            # 如果你以后用面向对象的方式把脚本写在 songling_navigation 目录下，才用这里。
            # 现在既然放在 scripts 文件夹里，就留空即可。
        ],
    },
)