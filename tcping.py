import socket
import threading
import time
import argparse
from IPy import IP

# 全局配置
ips = []
ports = [80]
num_asyncio = 20     # 每批并发线程数
timeout = 3          # 单次连接超时时间（秒）
retries = 3          # 每个目标尝试次数
destinations = []    # 存储所有 (ip, port) 目标
results = {}         # 存储最终结果 { (ip,port): avg_delay }
vtimeout= 3000  # 超时摊入平均的值（毫秒）
lock = threading.Lock()

def tcp_ping(ip, port):
    delays = []
    for _ in range(retries):
        try:
            start = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                elapsed = (time.time() - start) * 1000  # 转换为毫秒
                if result == 0:
                    delays.append(elapsed)
                else:
                    delays.append(vtimeout)  # 连接失败则标记为vtimeout
        except Exception:
            delays.append(vtimeout)

    avg_delay = sum(delays) / len(delays)
    with lock:
        results[(ip, port)] = avg_delay

def do_fetch(targets):
    threads = []
    for ip, port in targets:
        thread = threading.Thread(target=tcp_ping, args=(ip, port))
        thread.daemon = True
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

def scan_ips():
    global destinations, num_asyncio
    for i in range(0, len(destinations), num_asyncio):
        batch = destinations[i:i + num_asyncio]
        do_fetch(batch)

def main():
    global ips, ports, destinations

    parser = argparse.ArgumentParser(description="批量TCPing工具 - 找出最快最稳定的IP:Port")
    parser.add_argument('--ipr', type=str, help='CIDR格式IP范围，例如 192.168.1.0/24')
    parser.add_argument('--ipf', type=str, help='包含IP地址的文本文件，每行一个IP或IP/Range')
    parser.add_argument('--ports', type=str, default='80', help='要扫描的端口列表，逗号分隔，默认80')
    parser.add_argument('--numasyncio', type=int, default=20, help='单次最大并发线程数，默认20')
    parser.add_argument('--retries', type=int, default=3, help='每个目标尝试次数，默认3次')
    parser.add_argument('--timeout', type=float, default=3, help='单次连接超时时间（秒），默认3秒')
    parser.add_argument('--vtimeout', type=int, default=3000, help='超时摊入平均的值')

    args = parser.parse_args()
    global num_asyncio, timeout, retries, vtimeout
    num_asyncio = args.numasyncio
    timeout = args.timeout
    retries = args.retries
    vtimeout = args.vtimeout

    ports = list(map(int, args.ports.split(',')))
    ips = []
    destinations = []

    # 解析IP来源
    if args.ipf:
        try:
            with open(args.ipf, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if '/' in line:
                        for ip in IP(line):
                            ips.append(str(ip))
                    else:
                        ips.append(line)
        except Exception as e:
            print("读取IP文件出错:", e)
            return
    elif args.ipr:
        try:
            for ip in IP(args.ipr):
                ips.append(str(ip))
        except Exception as e:
            print("解析CIDR出错:", e)
            return
    else:
        print("请提供 --ipr 或 --ipf 参数")
        return

    # 去重
    ips = list(set(ips))

    # 构造目标
    for ip in ips:
        for port in ports:
            destinations.append((ip, port))

    print(f"共 {len(ips)} 个IP，{len(ports)} 个端口，共需测试 {len(destinations)} 个目标。")

    # 开始扫描
    scan_ips()

    # 输出结果并排序
    sorted_results = sorted(results.items(), key=lambda x: x[1])

    print("\n=== 排序后的 TCPing 结果 ===")
    print("{:<15} {:<6} {:<10}".format("IP", "Port", "Avg Delay (ms)"))
    for (ip, port), delay in sorted_results:
        print("{:<15} {:<6} {:.2f} ms".format(ip, port, delay))

if __name__ == "__main__":
    main()