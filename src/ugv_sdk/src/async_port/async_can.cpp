/*
 * async_can.cpp
 *
 * Created on: Sep 10, 2020 13:23
 * Description:
 *
 * Copyright (c) 2020 Weston Robot Pte. Ltd.
 */

#include "ugv_sdk/details/async_port/async_can.hpp"

#include <net/if.h>
#include <poll.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/can.h>

#include <iostream>

namespace westonrobot {
AsyncCAN::AsyncCAN(std::string can_port)
    : port_(can_port), socketcan_stream_(io_context_) {}

AsyncCAN::~AsyncCAN() { Close(); }

bool AsyncCAN::Open() {
  if (port_opened_) return true;
  if (io_thread_.joinable()) Close();
  try {
    const size_t iface_name_size = strlen(port_.c_str()) + 1;
    if (iface_name_size > IFNAMSIZ) return false;

    can_fd_ = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK, CAN_RAW);
    if (can_fd_ < 0) return false;

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    memcpy(ifr.ifr_name, port_.c_str(), iface_name_size);

    const int ioctl_result = ioctl(can_fd_, SIOCGIFINDEX, &ifr);
    if (ioctl_result < 0) {
      Close();
      return false;
    }

    struct sockaddr_can addr;
    memset(&addr, 0, sizeof(addr));
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;

    const int bind_result =
        bind(can_fd_, (struct sockaddr *)&addr, sizeof(addr));
    if (bind_result < 0) {
      Close();
      return false;
    }

    port_opened_ = true;
    std::cout << "Start listening to port: " << port_ << std::endl;
  } catch (std::system_error &e) {
    port_opened_ = false;
    std::cout << e.what() << std::endl;
    return false;
  }

  // give some work to io_service to start async io chain
  asio::error_code assign_error;
  socketcan_stream_.assign(can_fd_, assign_error);
  if (assign_error) {
    ::close(can_fd_);
    can_fd_ = -1;
    port_opened_ = false;
    return false;
  }

#if ASIO_VERSION < 101200L
  io_context_.post(std::bind(&AsyncCAN::ReadFromPort, this,
                             std::ref(rcv_frame_),
                             std::ref(socketcan_stream_)));
#else
  asio::post(io_context_,
             std::bind(&AsyncCAN::ReadFromPort, this, std::ref(rcv_frame_),
                       std::ref(socketcan_stream_)));
#endif

  // start io thread
  io_thread_ = std::thread([this]() { io_context_.run(); });

  return true;
}

void AsyncCAN::Close() {
  port_opened_ = false;
  io_context_.stop();
  if (io_thread_.joinable()) io_thread_.join();
  // The Asio descriptor owns an assigned fd. Closing it through both APIs can
  // accidentally close a subsequently reused descriptor.
  asio::error_code ignored;
  if (socketcan_stream_.is_open())
    socketcan_stream_.close(ignored);
  else if (can_fd_ >= 0)
    ::close(can_fd_);
  can_fd_ = -1;
  // Drain cancelled handlers while this object still exists, before a reopen.
  io_context_.reset();
  io_context_.poll();
  io_context_.reset();
}

bool AsyncCAN::IsOpened() const { return port_opened_; }

void AsyncCAN::DefaultReceiveCallback(can_frame *rx_frame) {
  std::cout << std::hex << rx_frame->can_id << "  ";
  for (int i = 0; i < rx_frame->can_dlc; i++)
    std::cout << std::hex << int(rx_frame->data[i]) << " ";
  std::cout << std::dec << std::endl;
}

void AsyncCAN::ReadFromPort(struct can_frame &rec_frame,
                            asio::posix::basic_stream_descriptor<> &stream) {
  stream.async_read_some(
      asio::buffer(&rec_frame, sizeof(rec_frame)),
      [this](asio::error_code error, size_t bytes_transferred) {
        if (!port_opened_) return;
        if (error) {
          // This callback runs on io_thread_. Calling Close() here attempts to
          // join the current thread and throws "Resource deadlock avoided".
          // Leave joining to the owning thread; close the failed device now.
          port_opened_ = false;
          asio::error_code ignored;
          socketcan_stream_.close(ignored);
          can_fd_ = -1;
          std::cerr << "CAN interface " << port_ << " disconnected: "
                    << error.message() << std::endl;
          return;
        }
        if (bytes_transferred == sizeof(rcv_frame_)) {
          if (rcv_cb_ != nullptr)
            rcv_cb_(&rcv_frame_);
          else
            DefaultReceiveCallback(&rcv_frame_);
        }
        if (port_opened_)
          ReadFromPort(std::ref(rcv_frame_), std::ref(socketcan_stream_));
      });
}

void AsyncCAN::SendFrame(const struct can_frame &frame) {
  if (!port_opened_) return;
  // Callers commonly pass a stack frame. Keep a copy alive until async IO ends.
  auto outgoing = std::make_shared<can_frame>(frame);
  auto send = [this, outgoing]() {
    if (!port_opened_) return;
    socketcan_stream_.async_write_some(
      asio::buffer(outgoing.get(), sizeof(*outgoing)),
      [outgoing](asio::error_code error, size_t bytes_transferred) {
        if (error) {
          std::cerr << "Failed to send CAN frame" << std::endl;
        }
        // std::cout << "frame sent" << std::endl;
      });
  };
#if ASIO_VERSION < 101200L
  io_context_.post(send);
#else
  asio::post(io_context_, send);
#endif
}

}  // namespace westonrobot
