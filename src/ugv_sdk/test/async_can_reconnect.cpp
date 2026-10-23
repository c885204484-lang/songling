#include <asio.hpp>
#include "ugv_sdk/details/async_port/async_can.hpp"
#include <atomic>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <unistd.h>
#include <cstring>
#include <cstdlib>
#include <poll.h>

void check(bool v, const char* why) { if (!v) throw std::runtime_error(why); }
int main() {
  westonrobot::AsyncCAN unopened("sltestcan");
  unopened.Close();
  westonrobot::AsyncCAN absent("nosuchcan9");
  check(!absent.Open(), "missing interface accepted");
  auto port = std::make_shared<westonrobot::AsyncCAN>("sltestcan");
  std::atomic<int> count{0};
  port->SetReceiveCallback([&](can_frame* f) { if (f->can_id == 0x654) ++count; });
  check(port->Open(), "cannot open virtual CAN");
  int fd=socket(PF_CAN,SOCK_RAW,CAN_RAW);check(fd>=0,"socket failed");
  ifreq ifr{};std::strcpy(ifr.ifr_name,"sltestcan");check(ioctl(fd,SIOCGIFINDEX,&ifr)==0,"ifindex failed");
  sockaddr_can addr{};addr.can_family=AF_CAN;addr.can_ifindex=ifr.ifr_ifindex;
  check(bind(fd,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))==0,"bind failed");
  can_frame incoming{};incoming.can_id=0x654;incoming.can_dlc=8;
  check(write(fd,&incoming,sizeof(incoming))==sizeof(incoming),"receive stimulus failed");
  for(int i=0;i<100&&count==0;++i)std::this_thread::sleep_for(std::chrono::milliseconds(5));
  check(count>0,"no receive callback");
  for(int i=0;i<200;++i) {
    can_frame outgoing{};outgoing.can_id=0x123;outgoing.can_dlc=8;
    std::memcpy(outgoing.data,&i,sizeof(i));port->SendFrame(outgoing);
    std::memset(&outgoing,0xff,sizeof(outgoing));
    pollfd pfd{fd,POLLIN,0};check(poll(&pfd,1,1000)==1,"no transmitted frame");
    can_frame got{};check(read(fd,&got,sizeof(got))==sizeof(got),"short frame");
    int value=-1;std::memcpy(&value,got.data,sizeof(value));
    check(got.can_id==0x123&&got.can_dlc==8&&value==i,"asynchronous TX buffer corrupted");
  }
  std::cout<<"PASS: RX and 200 stack-backed asynchronous TX frames"<<std::endl;
  check(std::system("sudo -n ip link set sltestcan down")==0,"cannot lower test interface");
  for(int i=0;i<100&&port->IsOpened();++i)std::this_thread::sleep_for(std::chrono::milliseconds(10));
  check(!port->IsOpened(),"disconnect not detected");
  port->Close();
  check(std::system("sudo -n ip link set sltestcan up")==0,"cannot restore test interface");
  check(port->Open(),"same-object reconnect failed");
  port->Close();port->Close();port.reset();close(fd);
  std::cout<<"PASS: disconnect, clean shutdown, reopen and repeated close without deadlock"<<std::endl;
}
