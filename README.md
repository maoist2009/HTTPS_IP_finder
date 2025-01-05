# IP查找器

## 用处

找到在GFW的封锁下幸存的ip

## 特性

+ 扫ip+端口
+ 支持前置反DPI代理
+ 并发

## [文档]

```shell
usage: main.py [-h] [--proxy [PROXY]] [--url [URL]] [--ipr [IPR]] [--ipf [IPF]] [--ports PORTS] [--portt [PORTT]]
               [--numasyncio [NUMASYNCIO]] [--numprocess [NUMPROCESS]] [--timeout [TIMEOUT]] [--ignore-cert] [--check200 [CHECK200]]
               [--check30x]

命令行参数解析示例

optional arguments:
  -h, --help            show this help message and exit
  --proxy [PROXY]       使用的反DPI代理（HTTP）
  --url [URL]           目标url
  --ipr [IPR]           ip范围，形如10.0.0.0/24，与ipf参数二选一
  --ipf [IPF]           （ip范围或ip）文件位置，每行一个ip，与ipr参数二选一，多有则取ipf文件
  --ports PORTS         端口号起始枚举值，默认443
  --portt [PORTT]       端口号终止枚举值，端口号左闭右开，若没有此项，则取ports+1
  --numasyncio [NUMASYNCIO]
                        单进程最大异步请求数，默认20（搞不定aiohttp库，暂时使用threading实现）
  --numprocess [NUMPROCESS]
                        同时最大进程数，默认5（暂不支持）
  --timeout [TIMEOUT]   单连接超时事件，默认10秒
  --ignore-cert         是否忽略证书错误，默认False
  --check200 [CHECK200]
                        如果为200响应，判断响应内容是否符合对应文件内容
  --check30x            是否检查30x跳转，默认False
```

## GUI

会使用aardio实现windows版，不在此项目中。
