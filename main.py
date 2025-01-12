import threading
import ssl
from aiohttp.resolver import DefaultResolver
from IPy import IP
import chardet

# parse arguments
HTTP_proxy = None
ips=[]
ports=[443]
num_asyncio = 20
num_process = 5
url="https://www.baidu.com"
destinations=[]
my_timeout = 5
ignore_cert = False
check200 = None
check30x = False
check_content = None

logpath = ""



# python main.py --proxy 127.0.0.1:2500 --ipr 10.0.0.0/24 --ipf ips.txt --ports 443 --portt 1445
# parse arguments

import socket

logfile=None

lock = threading.Lock()


def fprint(a,b,c):
    lock.acquire()
    try:
        print(a+":"+str(b)+"--------"+str(c))
        logfile.write(a+":"+str(b)+"--------"+str(c)+'\r\n')
    finally:
        lock.release()
    

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


        if ignore_cert:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

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
        response = b''
        while True:
            data = ssl_sock.recv(16384)
            if not data:
                break
            response = response + data
        response = response.decode(encoding='utf-8',errors='replace')
        response_code = response.split('\r\n')[0].split()[1]
        # response code
        fprint(ip,port,response_code)
        if (check200 and response_code == '200') or (check30x and response_code.startswith('3')):
            print("check not implemented, write to "+logpath+response_code+"/"+ip+"_"+str(port)+".rsp")
            try: 
                import os
                os.makedirs(logpath+response_code+"/", exist_ok=True)
                with open(logpath+response_code+"/"+ip+"_"+str(port)+".rsp", 'w+', encoding='utf-8', errors='replace') as f:
                    f.write(response)
            except Exception as e:
                print("output error",e)

        
        
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
    parser.add_argument('--numasyncio', type=int, nargs='?',help='单进程最大异步请求数，默认20（搞不定aiohttp库，暂时使用threading实现）')
    parser.add_argument('--numprocess', type=int, nargs='?',help='同时最大进程数，默认5（暂不支持）')
    parser.add_argument('--timeout', type=int, nargs='?',help='单连接超时事件，默认10秒')
    parser.add_argument('--ignore-cert',default=False,action='store_true',help='是否忽略证书错误，默认False')
    parser.add_argument('--check200',type=str, nargs='?',help='如果为200响应，判断响应内容是否符合对应文件内容')
    parser.add_argument('--check30x',default=False,action='store_true',help='是否检查30x跳转，默认False')

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
                lines = f.readlines()
                for line in lines:
                    temp_ips = line.strip()
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
            global num_asyncio
            num_asyncio = args.numasyncio
        if args.numprocess:
            global num_process
            num_process = args.numprocess
        if args.url:
            global url
            url = args.url
        if args.timeout:
            global my_timeout
            my_timeout = args.timeout
        if args.ignore_cert:
            global ignore_cert
            ignore_cert = True
        if args.check200:
            global check200
            check200 = args.check200
        if args.check30x:
            global check30x
            check30x = True
        
    except Exception as e:
        print(e)
        parser.print_help()

    ipsed={}
    ipst=[]
    for ip in ips:
        if ipsed.get(ip)==None:
            ipst.append(ip)
            ipsed[ip]=1
    print(len(ipst))
    import copy
    ips=copy.deepcopy(ipst)
    ipst=[]
    ipsed={}

    for ip in ips:
        for port in ports:
            destinations.append((ip,port))
    # print(destinations)


    import os
    
    from hashlib import md5
    import time
    global logpath
    logpath="rsp/"+md5((url+str(time.time())).encode(encoding='utf-8')).hexdigest()+"/"
    os.makedirs(logpath, exist_ok=True)
    print("日志位置："+logpath)
    global logfile
    logfile=open(logpath+"log.txt","w+",encoding='utf-8')

    with open("log.txt", 'a+', encoding='utf-8') as f:
        # 输出传入参数和时间到日志文件
        f.write(logpath+": "+str(time.time())+" "+str(args)+'\r\n')


    if check200:
        with open(check200, 'r') as f:
            global check_content
            check_content = f.read()

    try:
        print("开始扫描：",url)
        scan_ips()
    except KeyboardInterrupt:
        print("用户中断")

    print("日志位置："+logpath)
        
    
main()
