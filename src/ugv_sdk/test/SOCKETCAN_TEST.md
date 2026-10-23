# SocketCAN reconnect regression

This opt-in test uses only a virtual interface named `sltestcan`. Do not assign
that name to a physical CAN device. The test sends 200 frames, lowers/raises the
virtual interface and checks clean shutdown and reopening. It never uses `can0`.

From the workspace root:

```bash
sudo modprobe vcan
sudo ip link add sltestcan type vcan
sudo ip link set sltestcan up
c++ -std=c++11 -pthread -I src/ugv_sdk/include \
  src/ugv_sdk/test/async_can_reconnect.cpp \
  src/ugv_sdk/src/async_port/async_can.cpp -o /tmp/songling_can_regression
/tmp/songling_can_regression
sudo ip link delete sltestcan
```

The test uses `sudo -n ip link set sltestcan down/up`, so cached sudo credentials
or an equivalent scoped permission are required. With `BUILD_TESTING=ON` it is
also built as the `async_can_reconnect` target.
