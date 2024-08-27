**Script Usage:**

Multipin.sh:

执行： ```/path/to/multipin.sh```

回车输入多行 ```ipfs pin remote add --service=crust --background <cid>``` 指令。其中 cid 可以是文件 cid 也可以是文件夹 cid.

输入完成后，按 Ctrl+D 开始执行指令。你可以开一个 screen 会话挂后台执行。

Multicheck.sh:

一行一个查询指令：```ipfs pin remote ls --service=<nickname> --cid=<cid> --status=pinned,pinning,failed,queued```

如果返回pinned，证明成功；返回其他的包括无返回则均为卡链状态。可以通过crustfiles.io手动上传或者单纯重试Remote Pin进行修复。
