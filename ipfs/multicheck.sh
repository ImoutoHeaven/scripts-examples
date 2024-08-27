#!/bin/bash

# 准备记录失败、不同状态和stdout、stderr为空的命令的数组
failed_commands=()          # 执行成功但状态为failed的命令
error_failed_commands=()    # 由于错误导致最终执行失败的命令
pinning_commands=()
queued_commands=()
empty_output_commands=()    # stdout和stderr都为空的命令

log_file="check-output.log"  # 默认日志文件路径

# 解析输入参数
while [[ "$1" =~ ^- && ! "$1" == "--" ]]; do case $1 in
  -o | --out )
    shift; log_file=$1
    ;;
esac; shift; done
if [[ "$1" == '--' ]]; then shift; fi

# 如果日志文件路径不存在，则创建路径
log_dir=$(dirname "$log_file")
mkdir -p "$log_dir"

echo "请输入需要逐行执行的指令，按回车输入下一条指令；全部输入完成后按Ctrl+D进行运行："

# 逐行读取用户输入的指令
commands=()
while IFS= read -r line; do
    commands+=("$line")
done

echo "正在运行指令..."

# 函数用于执行命令并处理输出
execute_command() {
    local cmd="$1"
    local retries=0
    local max_retries=3
    local success=false

    while [ $retries -lt $max_retries ]; do
        echo "正在执行第$(($i + 1))条：$cmd"
        
        # 执行命令并同时显示 stdout 和 stderr
        stdout=$(eval "$cmd" 2>&1) 

        # 实时显示输出
        echo "$stdout"
        
        if [ -z "$stdout" ]; then
            cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
            echo "第$(($i + 1))条指令stdout和stderr均无输出，记录此指令；"
            empty_output_commands+=("$cid")
            success=true
            break
        elif echo "$stdout" | grep -iq "error"; then
            retries=$((retries + 1))
            if [ $retries -lt $max_retries ]; then
                echo "第$(($i + 1))条指令遇到错误，重试$retries/$max_retries次："
            else
                echo "第$(($i + 1))条指令在多次重试后仍然失败，跳过；"
                cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
                error_failed_commands+=("$cmd")
                success=true
            fi
            continue
        elif echo "$stdout" | grep -iq "failed"; then
            cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
            echo "stdout或stderr返回failed，记录此指令。"
            failed_commands+=("$cid")
            success=true
            break
        elif echo "$stdout" | grep -iq "pinned"; then
            echo "第$(($i + 1))条指令返回pinned，跳过；"
            success=true
            break
        elif echo "$stdout" | grep -iq "pinning"; then
            cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
            echo "stdout或stderr返回pinning，记录此指令。"
            pinning_commands+=("$cid")
            success=true
            break
        elif echo "$stdout" | grep -iq "queued"; then
            cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
            echo "stdout或stderr返回queued，记录此指令。"
            queued_commands+=("$cid")
            success=true
            break
        else
            echo "第$(($i + 1))条指令执行成功，stdout和stderr输出："
            success=true
            break
        fi
    done

    if [ "$success" = false ]; then
        cid=$(echo "$cmd" | grep -oP '(?<=--cid=)[^ ]+')
        error_failed_commands+=("$cmd")
    fi
}

# 依次执行每条指令
for i in "${!commands[@]}"; do
    execute_command "${commands[$i]}"
done

# 如果有由于错误导致执行失败的指令，再尝试重试三次
if [ ${#error_failed_commands[@]} -ne 0 ]; then
    echo "开始重试由于错误导致失败的指令..."
    temp_failed_commands=("${error_failed_commands[@]}")
    error_failed_commands=()
    for cmd in "${temp_failed_commands[@]}"; do
        execute_command "$cmd"
    done
fi

# 生成日志文件内容并展示结果
{
    echo "pinning:"
    printf "%s\n" "${pinning_commands[@]}"
    echo "======"
    echo "queued:"
    printf "%s\n" "${queued_commands[@]}"
    echo "======"
    echo "failed:"
    printf "%s\n" "${failed_commands[@]}"
    echo "======"
    echo "error executing:"
    printf "%s\n" "${error_failed_commands[@]}"
    echo "======"
    echo "empty response:"
    printf "%s\n" "${empty_output_commands[@]}"
    echo "======"
    echo "=*=*=*=*=*="
    echo "total all cids:"
    printf "%s\n" "${pinning_commands[@]}" "${queued_commands[@]}" "${failed_commands[@]}" "${error_failed_commands[@]}" "${empty_output_commands[@]}"
    echo "=*=*=*=*=*="
} | tee "$log_file"  # 同时将内容输出到屏幕和日志文件

# 输出保存日志文件提示
echo "脚本执行完毕，所有结果已记录到日志文件：$log_file"
