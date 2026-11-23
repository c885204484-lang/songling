#!/usr/bin/env bash

navigation_url=http://127.0.0.1:8080/simple
can_ports=(can0 can1)

show_error() {
    local message=$1
    printf '%s\n' "$message" >&2
    if [[ -n ${DISPLAY:-}${WAYLAND_DISPLAY:-} ]]; then
        if command -v zenity >/dev/null; then
            zenity --error --title='松灵导航' --text="$message" 2>/dev/null || true
        elif command -v xmessage >/dev/null; then
            xmessage -center "$message" 2>/dev/null || true
        fi
    fi
}

fail() {
    show_error "$1"
    exit 1
}

if [[ ${1:-} == --from-file-manager && ! ${2:-} -ef /home/nvidia/songling/songling_ws/start_navigation.sh ]]; then
    fail '请双击 songling_ws 工作区中的 start_navigation.sh。'
fi

configure_can() (
    cd ~/songling_ws/ || fail '无法进入 ~/songling_ws/。'

    local port details flags
    local -a missing=()
    local -A links=()
    for port in "${can_ports[@]}"; do
        if details=$(ip -details link show dev "$port" 2>/dev/null); then
            links[$port]=$details
        else
            missing+=("$port")
        fi
    done
    if ((${#missing[@]})); then
        fail "未检测到 CAN 接口 ${missing[*]}，请检查连接后重新启动。"
    fi

    for port in "${can_ports[@]}"; do
        details=${links[$port]}
        flags=${details#*<}
        flags=${flags%%>*}
        if [[ ,$flags, == *,UP,* ]]; then
            if [[ $details =~ [[:space:]]bitrate[[:space:]]500000([[:space:]]|$) ]]; then
                continue
            fi
            sudo ip link set "$port" down || fail "无法关闭 $port 以重新配置波特率。"
        fi
        sudo ip link set "$port" up type can bitrate 500000 ||
            fail "无法启用 $port 或设置波特率为 500000，请检查接口和 sudo 权限。"
    done
)

watch_navigation() {
    local port page_opened=false page_deadline=$((SECONDS + 60))
    local -A missing=()

    while kill -0 "$launch_pid" 2>/dev/null; do
        for port in "${can_ports[@]}"; do
            if ip link show dev "$port" >/dev/null 2>&1; then
                unset 'missing[$port]'
            elif [[ -z ${missing[$port]:-} ]]; then
                missing[$port]=1
                show_error "CAN 接口 $port 已丢失，请检查连接。" &
            fi
        done

        if [[ $page_opened == false ]]; then
            if curl --noproxy '*' --fail --silent --max-time 2 --output /dev/null "$navigation_url"; then
                firefox --new-tab "$navigation_url" &
                page_opened=true
            elif ((page_deadline && SECONDS >= page_deadline)); then
                show_error "导航页面在 60 秒内未就绪。请检查此终端中的 ROS 日志。" &
                page_deadline=0
            fi
        fi
        sleep 1
    done
}

cd /home/nvidia/songling/songling_ws || fail '无法进入 songling_ws 工作区。'
source /opt/ros/humble/setup.bash || fail '无法加载 ROS 2 Humble 环境。'
source install/setup.bash || fail '无法加载 songling_ws 环境。'
command -v firefox >/dev/null || fail '找不到 Firefox。'
if curl --noproxy '*' --silent --max-time 2 --output /dev/null "$navigation_url"; then
    fail '本机 8080 端口已有网页服务，请关闭该服务后再启动导航。'
fi
configure_can || exit 1

# 保留 ROS 的 SIGINT 处理，让脚本退出时能正常关闭节点。
env --default-signal=INT ros2 launch songling_navigation gps_navigation.launch.py \
    use_offline_map:=True \
    offline_enable_motion:=True </dev/null &
launch_pid=$!
watch_navigation &
watch_pid=$!

stop_watcher() {
    kill "$watch_pid" 2>/dev/null || true
    wait "$watch_pid" 2>/dev/null || true
}

stop_navigation() {
    trap '' INT TERM
    stop_watcher
    kill -INT "$launch_pid" 2>/dev/null || true
    wait "$launch_pid" 2>/dev/null
    exit "$1"
}

trap 'stop_navigation 130' INT
trap 'stop_navigation 143' TERM
wait "$launch_pid"
launch_status=$?
stop_watcher
if ((launch_status != 0)); then
    show_error "导航启动进程已退出，状态码 $launch_status。请检查此终端中的 ROS 日志。"
fi
exit "$launch_status"
