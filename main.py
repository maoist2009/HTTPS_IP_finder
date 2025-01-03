import threading
import ssl
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
my_timeout = 5


# python main.py --proxy 127.0.0.1:2500 --ipr 10.0.0.0/24 --ipf ips.txt --ports 443 --portt 1445
# parse arguments

import socket

logfile=open('log.txt', 'w+')

def fprint(a,b,c):
    logfile.write(a+":"+str(b)+"--------"+str(c)+'\r\n')
    

def fetch_with_ip(url,ip,port):
    global HTTP_proxy
    global my_timeout
    try:
        phost, pport = HTTP_proxy.split(':')
        pport = int(pport)
        host= url.split('//')[1].split('/')[0]


        # 创建TCP连接
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except Exception as e:
            print("TCP Error",e)
        
        sock.settimeout(my_timeout)

        
        if HTTP_proxy:
            sock.connect((phost, pport))


            # HTTP proxy CONNECT
            request = f"CONNECT {ip}:{port} HTTP/1.1\r\n"+f"Host: {host}\r\n"+"Proxy-Connection: Keep-Alive\r\n"+"User-Agent: Python-asyncio\r\n"+"\r\n"        
            # print(request)
            sock.sendall(request.encode(encoding='utf-8'))
            response = sock.recv(1024)
            response = response.decode(encoding='utf-8')
            # print(response)
            if response.split()[1]!= '200':
                print("Proxy CONNECT Error",e)
                raise(e)
        else:
            sock.connect((ip, port))

        # wrap ssl
        
        ssl_context = ssl.create_default_context()
        ssl_sock = ssl_context.wrap_socket(sock, server_hostname=host)

        # send request
        if(len(url.split('//')[1].split('/',1)) == 1):
            url="/"
        else:
            url="/"+url.split('//')[1].split('/',1)[1]
        # print(url)
        request = f"GET {url} HTTP/1.1\r\n"+"Host: "+host+"\r\n"+"Connection: close\r\n"+"User-Agent: Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.140\r\n"+"\r\n"
        # print(request)
        ssl_sock.sendall(request.encode(encoding='utf-8'))
        
        # receive response
        response = ssl_sock.recv(16384)
        response = response.decode(encoding='utf-8')
        
        # response code
        fprint(ip,port,response.split('\r\n')[0].split()[1])
        # print(response)
        
    except Exception as e:
        if e==socket.timeout:
            fprint(ip,port,"Timeout")
        elif e==ssl.SSLError:
            fprint(ip,port,"SSL Error")
        elif e==socket.error:
            fprint(ip,port,"Socket Error")
        else:
            fprint(ip,port,e)
    



# 运行主函数
def do_fetch(url,destinations):
    print(destinations)
    threads = []
    for ip,port in destinations:
        thread_up = threading.Thread(target = fetch_with_ip , args =(url,ip,port) )
        threads.append(thread_up)
        thread_up.daemon = True   #avoid memory leak by telling os its belong to main program , its not a separate program , so gc collect it when thread finish
        thread_up.start()
    
    for thread in threads:
        thread.join()


def scan_ips():
    global url
    global destinations
    global num_asyncio
    global num_process
    global my_timeout
    import multiprocessing
    
    # _do_fetch(url,destinations)
    for i in range(0,len(destinations),num_asyncio):
        do_fetch(url,destinations[i:min(i+num_asyncio,len(destinations))])

    # with multiprocessing.Pool(num_process) as pool:
    #     for i in range(0,len(destinations),num_asyncio):
    #         pool.apply_async(_do_fetch, args=(url,destinations[i:min(i+num_asyncio,len(destinations))]))
    #     pool.close()
    #     pool.join()

    


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
    
    parser.add_argument('--proxy', type=str, nargs='?',help='使用的反DPI代理（HTTP）')
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