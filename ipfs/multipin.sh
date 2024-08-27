#!/bin/bash

# 提示用户输入最大运行时间和 sleep 时间
read -p "请输入最大运行时间（默认 12 小时，单位为小时）:" max_runtime
max_runtime=${max_runtime:-12}

read -p "请输入 sleep 时间（默认 4 小时，单位为小时）:" sleep_time
sleep_time=${sleep_time:-4}

# 检查最大运行时间是否为 sleep 时间的整数倍数
if ((max_runtime % sleep_time != 0)); then
    echo "最大运行时间必须为 sleep 时间的整数倍数。请重新输入。"
    exit 1
fi

# 提示用户输入命令
echo "请输入要执行的命令，命令之间用换行符分割。输入完成后按 Ctrl+D 结束输入："

# 读取用户输入的命令
commands=()
while IFS= read -r line; do
    commands+=("$line")
done

# 定义一个函数来执行命令并检查错误
execute_command() {
    local cmd=$1
    local retries=3

    for ((attempt=1; attempt<=retries; attempt++)); do
        echo "尝试第 $attempt 次: $cmd"
        output=$(eval "$cmd" 2>&1)
        echo "$output"

        if [[$output != *"Error"*]]; then
            return 0
        else
            echo "命令执行失败，检测到错误。"
        fi
    done

    echo "重试 $retries 次后仍然失败。"
    return 1
}

# 定义信号处理函数
handle_sigint() {
    echo -e "\n 检测到 Ctrl+C，强制退出脚本。"
    exit 1
}

# 绑定 SIGINT 信号到信号处理函数
trap 'handle_sigint' SIGINT

# 计算循环次数
loops=$((max_runtime / sleep_time))

# 执行循环
for ((i=1; i<=loops; i++)); do
    echo "执行第 $i 次"

    failed_commands=()

    # 执行所有命令
    for cmd in "${commands[@]}"; do
        execute_command "$cmd"
        if [[$? -ne 0]]; then
            failed_commands+=("$cmd")
        fi
    done

    # 处理失败的命令
    if [[${#failed_commands[@]} -ne 0 ]]; then
        echo "尝试重试失败的命令..."

        for failed_cmd in "${failed_commands[@]}"; do
            execute_command "$failed_cmd"
            if [[$? -ne 0]]; then
                echo "跳过命令: $failed_cmd"
            fi
        done
    fi

    # 如果还有下一轮循环，sleep
    if ((i < loops)); then
        echo "等待 $sleep_time 小时..."
        sleep $((sleep_time * 3600)) &
        sleep_pid=$!
        trap 'handle_sigint' SIGINT # 确保 SIGINT 处理会触发 handle_sigint
        wait $sleep_pid
    fi
done

echo "所有任务完成"
