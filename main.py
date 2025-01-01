import aiohttp
import aiohttp_socks
import asyncio
from aiohttp.resolver import DefaultResolver

from IPy import IP

# parse arguments
HTTP_proxy = None
ips=[]
ports=[443]
num_asyncio = 20
num_process = 5
url="https://www.baidu.com"
destinations=[]
my_timeout = 10


# python main.py --proxy http://127.0.0.1:2500 --ipr 10.0.0.0/24 --ipf ips.txt --ports 443 --portt 1445
# parse arguments

import aiohttp.abc
import socket

class CustomResolver(DefaultResolver):
    def __init__(self, ip, port, *args, **kwargs):
        self.ip = ip
        self.port = port
        super().__init__()
    async def resolve(self, host, port=0, family=0):
        
        print(f"解析域名{host}到{self.ip}:{self.port}")
        return [aiohttp.abc.ResolveResult(
                    hostname=host,
                    host=self.ip,
                    port=self.port,
                    family=family,
                    proto=0,
                    flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
                )]


async def fetch_with_ip(url,ip,port):
    host_connector = aiohttp.TCPConnector(resolver=CustomResolver(ip=ip,port=port))


    async with aiohttp.ClientSession(connector=host_connector) as session:
        try:
            response = await asyncio.wait_for(session.get(url),timeout=my_timeout)
            print(f"IP:{ip} port {port} 状态码：{response.status}")
        except asyncio.TimeoutError:
            print(f"IP:{ip} port {port} 超时")
        except Exception as e:
            print(f"IP:{ip} port {port} 异常：{e}")
            raise e


# 运行主函数
async def do_fetch(url,destinations):
    print(destinations)
    tasks = []
    for ip,port in destinations:
        tasks.append(asyncio.create_task(fetch_with_ip(url,ip,port)))
    
    for task in tasks:
        await task

def _do_fetch(url,destinations):
    # print(destinations)
    asyncio.run(do_fetch(url,destinations))

def scan_ips():
    global url
    global destinations
    global num_asyncio
    global num_process
    global my_timeout
    import multiprocessing
    
    # _do_fetch(url,destinations)

    with multiprocessing.Pool(num_process) as pool:
        for i in range(0,len(destinations),num_asyncio):
            pool.apply_async(_do_fetch, args=(url,destinations[i:min(i+num_asyncio,len(destinations))]))
        pool.close()
        pool.join()

    


def main():
    global HTTP_proxy
    global ips
    global ports
    global num_asyncio
    global num_process
    global url
    global destinations
    global my_timeout
    import argparse
    parser = argparse.ArgumentParser(description='命令行参数解析示例')
    
    parser.add_argument('--proxy', type=str, nargs='?',help='使用的反DPI代理')
    parser.add_argument('--url', type=str, nargs='?',help='目标url')
    parser.add_argument('--ipr', type=str, nargs='?',help='ip范围，形如10.0.0.0/24，与ipf参数二选一')
    parser.add_argument('--ipf', type=str, nargs='?',help='（ip范围或ip）文件位置，每行一个ip，与ipr参数二选一，多有则取ipf文件')
    parser.add_argument('--ports', type=str, default="443",help='端口号起始枚举值，默认443')
    parser.add_argument('--portt', type=str, nargs='?',help='端口号终止枚举值，端口号左闭右开，若没有此项，则取ports+1')
    parser.add_argument('--numasyncio', type=int, nargs='?',help='单进程最大异步请求数，默认20')
    parser.add_argument('--numprocess', type=int, nargs='?',help='同时最大进程数，默认5')
    parser.add_argument('--timeout', type=int, nargs='?',help='单连接超时事件，默认10秒')


    try:
        # 解析参数
        args = parser.parse_args()
        # 访问参数
        if args.proxy:
            HTTP_proxy = args.proxy
        if args.ipr:
            temp_ips = IP(args.ipr)
            for ip in temp_ips:
                ips.append(str(ip))
        if args.ipf:
            with open(args.ipf, 'r') as f:
                temp_ips = f.readlines()
                if temp_ips.find('/')!= -1:
                    temp_ips=IP(temp_ips)
                    for ip in temp_ips:
                        ips.append(str(ip))
                else:
                    ips.append(str(temp_ips))
        if args.ports:
            if args.portt:
                ports = range(int(args.ports), int(args.portt))
            else:
                ports = [int(args.ports)]
        if args.numasyncio:
            num_asyncio = args.numasyncio
        if args.numprocess:
            num_process = args.numprocess
        if args.url:
            url = args.url
        if args.timeout:
            my_timeout = args.timeout
        
    except Exception as e:
        print(e)
        parser.print_help()

    for ip in ips:
        for port in ports:
            destinations.append((ip,port))
    # print(destinations)

    try:
        print(url)
        scan_ips()
    except KeyboardInterrupt:
        print("用户中断")
        
    
main()