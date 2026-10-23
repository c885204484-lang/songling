"""Exercise the real chassis binary on sltestcan in an isolated ROS domain."""
import os,signal,socket,struct,subprocess,threading,time
from pathlib import Path
from ament_index_python.packages import get_package_prefix
binary=str(Path(get_package_prefix('hunter_base'))/'lib/hunter_base/hunter_base_node')
sock=socket.socket(socket.PF_CAN,socket.SOCK_RAW,socket.CAN_RAW)
sock.bind(('sltestcan',))
feeding=threading.Event();feeding.set();stop=threading.Event()
def feed():
    while not stop.wait(.02):
        if feeding.is_set():
            for ident,body in ((0x211,bytes([0,1,2,1,0,0,0])),(0x221,bytes(7))):
                checksum=(ident%256+ident//256+8+sum(body))%256
                sock.send(struct.pack('=IB3x8s',ident,8,body+bytes([checksum])))
thread=threading.Thread(target=feed);thread.start()
env=dict(os.environ,ROS_DOMAIN_ID='88',ROS_LOCALHOST_ONLY='1')
log=Path('/tmp/songling-driver-virtual-test.log').open('wb',buffering=0)
p=None
def run():
    return subprocess.Popen([binary,'--ros-args','-p','port_name:=sltestcan','-p','robot_model:=hunter2'],env=env,stdout=log,stderr=log)
try:
    p=run();time.sleep(2)
    assert p.poll() is None,'Driver did not initialize on virtual feedback'
    assert 'Robot initialized' in Path(log.name).read_text()
    feeding.clear()
    rc=p.wait(timeout=5)
    assert rc==0,('Driver did not stop cleanly after feedback timeout',rc)
    assert 'CAN feedback timed out' in Path(log.name).read_text()
    print('PASS: real chassis driver detects lost CAN feedback and exits cleanly',flush=True)
    feeding.set();p=run();time.sleep(2)
    assert p.poll() is None,'Driver did not reconnect'
    p.send_signal(signal.SIGINT)
    assert p.wait(timeout=5)==0,'Driver shutdown was not clean'
    print('PASS: real chassis driver reconnects and stops cleanly on SIGINT',flush=True)
finally:
    stop.set();thread.join(timeout=2);sock.close()
    if p and p.poll() is None:p.kill();p.wait()
    log.close()
