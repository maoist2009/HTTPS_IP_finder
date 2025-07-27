import threading
import ssl
from IPy import IP
import socket
import argparse
import time
import os
import csv
from hashlib import md5

# 全局变量
HTTP_proxy = None
ips = []
ports = [443]
num_asyncio = 20
url = "https://www.baidu.com"
destinations = []
my_timeout = 5 # 连接和握手超时
ignore_cert = False
do_check200 = False
check30x = False
speedtest_enabled = False
speedtest_max_time = 10.0 # 测速最大时间，默认10秒
logpath = ""
csvfile = None
csv_writer = None
lock = threading.Lock()

def fprint(ip, port, status, message="", speed_kbs=None):
    """线程安全记录日志到CSV和控制台"""
    lock.acquire()
    try:
        # 准备CSV行数据
        row = [ip, port, status, message]
        # 只有在启用测速时才添加速度列
        if speedtest_enabled:
            if speed_kbs is not None:
                row.append(f"{speed_kbs:.2f} KB/s")
            else:
                row.append("") # 如果没有速度信息或未测速，则该列留空
        # 写入CSV行
        if csvfile and not csvfile.closed: # 检查文件是否有效
            csv_writer.writerow(row)
            csvfile.flush()  # 确保数据写入磁盘
        # 同时打印到控制台
        speed_str = f" ({speed_kbs:.2f} KB/s)" if speed_kbs is not None else ""
        print(f"{ip}:{port}--------{status}--------{message}{speed_str}")
    except Exception as e: # 捕获 fprint 内部可能的错误
        # 即使日志记录本身出错，也尽量打印到控制台
        print(f"LOGGING ERROR for {ip}:{port} - {e}")
    finally:
        lock.release()

def fetch_with_ip(url, ip, port):
    """核心请求函数，处理单个IP和端口的请求"""
    global HTTP_proxy, my_timeout, ignore_cert, do_check200, check30x, speedtest_enabled, speedtest_max_time, logpath
    sock = None
    ssl_sock = None
    status_code = "INIT" # 用于记录最终状态到CSV
    message = ""
    speed_kbs = None
    headers_received = False
    response_code = None # 从HTTP响应中解析出的状态码 (e.g., "200", "404")
    logged = False # 标志位，防止重复记录
    try:
        # --- 连接阶段 ---
        host = url.split('//')[1].split('/')[0]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(my_timeout) # 使用连接超时
        if HTTP_proxy:
            phost, pport = HTTP_proxy.split(':')
            pport = int(pport)
            sock.connect((phost, pport))
            connect_request = (
                f"CONNECT {ip}:{port} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Proxy-Connection: Keep-Alive\r\n"
                "User-Agent: Python-Thread\r\n\r\n"
            )
            sock.sendall(connect_request.encode('utf-8'))
            response = sock.recv(1024).decode('utf-8', errors='replace')
            if not response.startswith("HTTP/1.1 200"):
                status_code = "PROXY_ERROR"
                message = f"Proxy CONNECT failed: {response.split()[1] if len(response.split()) > 1 else 'Unknown'}"
                fprint(ip, port, status_code, message)
                logged = True
                return
        else:
            sock.connect((ip, port))
        # --- SSL握手阶段 ---
        ssl_context = ssl.create_default_context()
        if ignore_cert:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        ssl_sock = ssl_context.wrap_socket(sock, server_hostname=host)
        # --- 发送HTTP请求 ---
        path = "/" + url.split('//')[1].split('/', 1)[1] if len(url.split('//')[1].split('/', 1)) > 1 else "/"
        http_request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Connection: close\r\n"
            "User-Agent: Mozilla/5.0\r\n\r\n"
        )
        ssl_sock.sendall(http_request.encode('utf-8'))
        # --- 接收响应 ---
        response_data = b""
        headers_data = b""
        body_bytes_received = 0
        speedtest_start_time = None
        start_time = time.time() # 记录开始接收数据的时间

        while True:
            # 设置读取超时。使用 my_timeout 作为 recv 的超时，这比原来的固定 1.0s 更合理。
            # 在测速模式下，我们依赖循环内部的计时逻辑来控制，而不是 recv 的超时。
            ssl_sock.settimeout(my_timeout)

            data = ssl_sock.recv(16384)
            # 修复语法错误：补全 if not 语句
            if not data:
                break

            # --- 解析HTTP头 ---
            if not headers_received:
                headers_data += data
                header_end_index = headers_data.find(b'\r\n\r\n')
                if header_end_index != -1:
                    headers_received = True
                    # 提取头部和可能的初始body数据
                    header_bytes = header_end_index + 4 # 包括 \r\n\r\n
                    body_data = headers_data[header_bytes:] + (data[header_bytes:] if len(data) > header_bytes else b'')
                    # 解析HTTP状态码
                    try:
                        status_line = headers_data.split(b'\r\n', 1)[0].decode('utf-8', errors='replace')
                        response_code = status_line.split(' ', 2)[1] if len(status_line.split(' ', 2)) >= 2 else "PARSE_ERROR"
                        status_code = response_code # 将HTTP状态码作为CSV状态
                    except Exception as e:
                        status_code = "HEADER_PARSE_ERROR"
                        message = f"Error parsing headers: {e}"
                        fprint(ip, port, status_code, message)
                        logged = True
                        return # 头部解析失败，无法继续

                    # 如果是测速模式且响应是200，开始计时和累积数据
                    if speedtest_enabled and response_code == '200':
                        speedtest_start_time = time.time()
                        body_bytes_received += len(body_data)
                    # 如果是保存模式且响应是200/3xx，累积数据
                    if (do_check200 and response_code == '200') or (check30x and response_code.startswith('3')):
                        response_data = headers_data + body_data # 保存完整响应用于保存

            else:
                # --- 处理HTTP体 ---
                body_data = data
                # 测速逻辑
                if speedtest_enabled and speedtest_start_time is not None and response_code == '200':
                    body_bytes_received += len(body_data)
                    elapsed = time.time() - speedtest_start_time
                    # 使用 speedtest_max_time 变量
                    if elapsed >= speedtest_max_time:
                        # 测速结束
                        if elapsed > 0:
                            speed_kbs = (body_bytes_received / 1024.0) / elapsed
                        status_code = f"{response_code}_SPEED" # 特殊状态表示测速完成
                        message = f"{speedtest_max_time}s test completed"
                        fprint(ip, port, status_code, message, speed_kbs)
                        logged = True
                        break # 停止接收

                # 保存模式累积数据
                if (do_check200 and response_code == '200') or (check30x and response_code.startswith('3')):
                    response_data += body_data

                # 可选：添加一个总超时检查，防止无限循环（虽然不太可能发生）
                # total_elapsed = time.time() - start_time
                # if total_elapsed > my_timeout * 5: # 例如，如果总时间超过连接超时的5倍，则停止
                #     # print(f"Warning: Total read time for {ip}:{port} seems excessive ({total_elapsed:.2f}s), stopping.")
                #     break

        # --- 循环结束后的处理 --- (修复缩进)
        # 如果是因为连接关闭而退出循环
        if not logged: # 只有在没有因为测速完成而记录过时才执行
            # 如果测速开始但未完成（连接提前关闭）
            if speedtest_enabled and speedtest_start_time is not None and response_code == '200':
                elapsed_final = time.time() - speedtest_start_time
                if elapsed_final > 0:
                    speed_kbs = (body_bytes_received / 1024.0) / elapsed_final
                status_code = response_code
                message = "Connection closed before test time"
                fprint(ip, port, status_code, message, speed_kbs)
                logged = True
            elif headers_received: # 正常接收完头部（可能还有body）
                status_code = response_code if response_code else "UNKNOWN"
                # 保存响应内容（非测速模式）
                if not speedtest_enabled:
                    if do_check200 and status_code == '200':
                        try:
                            safe_ip = ip.replace(':', '.')
                            output_dir = os.path.join(logpath, status_code)
                            os.makedirs(output_dir, exist_ok=True)
                            output_file = os.path.join(output_dir, f"{safe_ip}_{port}.rsp")
                            with open(output_file, 'wb') as f: # 以二进制写入，避免编码问题
                                f.write(response_data)
                            message = f"Saved to {output_file}"
                        except Exception as e:
                            status_code = "SAVE_ERROR"
                            message = str(e)
                    elif check30x and status_code.startswith('3'):
                         try:
                             safe_ip = ip.replace(':', '.')
                             output_dir = os.path.join(logpath, status_code)
                             os.makedirs(output_dir, exist_ok=True)
                             output_file = os.path.join(output_dir, f"{safe_ip}_{port}.rsp")
                             with open(output_file, 'wb') as f:
                                 f.write(response_data)
                             message = f"Saved to {output_file}"
                         except Exception as e:
                             status_code = "SAVE_3XX_ERROR"
                             message = str(e)
                fprint(ip, port, status_code, message, speed_kbs)
                logged = True
            else: # 没有接收到完整的头部
                status_code = "NO_HEADERS"
                message = "Connection closed before headers received"
                fprint(ip, port, status_code, message)
                logged = True

    except socket.timeout:
        # 尝试区分是连接/握手超时还是读取超时
        if not headers_received:
            status_code = "CONN_TIMEOUT"
        else:
            status_code = "READ_TIMEOUT"
        fprint(ip, port, status_code, "", speed_kbs)
        logged = True
    except ssl.SSLError as e:
        status_code = "SSL_ERROR"
        fprint(ip, port, status_code, str(e), speed_kbs)
        logged = True
    except socket.error as e:
        status_code = "SOCKET_ERROR"
        fprint(ip, port, status_code, str(e), speed_kbs)
        logged = True
    except Exception as e:
        # 捕获所有其他未预期的内部错误
        status_code = "INTERNAL_ERROR" # 使用明确的内部错误代码
        message = str(e)
        fprint(ip, port, status_code, message, speed_kbs)
        logged = True
    finally:
        # 确保资源关闭
        try:
            if ssl_sock:
                ssl_sock.close()
        except:
            pass
        try:
            if sock:
                sock.close()
        except:
            pass
        # *** 关键修改：兜底记录 ***
        # 如果因为任何原因（例如 fprint 本身出错）没有记录，则在这里强制记录一次
        # 这能最大程度保证每个目标都有对应的CSV记录
        if not logged:
            # 如果 status_code 仍然是 "INIT"，说明可能在 very early stage 就出错了
            final_status = status_code if status_code != "INIT" else "UNRECORDED"
            final_message = message if message else "Function exited without explicit record"
            fprint(ip, port, final_status, final_message, speed_kbs)

def do_fetch(url, destinations_batch):
    """执行一批请求的多线程处理"""
    threads = []
    for ip, port in destinations_batch:
        thread = threading.Thread(target=fetch_with_ip, args=(url, ip, port))
        threads.append(thread)
        thread.daemon = True
        thread.start()
    for thread in threads:
        thread.join()

def scan_ips():
    """主扫描逻辑，分批处理所有目标"""
    global url, destinations, num_asyncio
    print(f"Starting scan for {url} with {len(destinations)} targets...")
    for i in range(0, len(destinations), num_asyncio):
        batch = destinations[i:i + num_asyncio]
        do_fetch(url, batch)

def main():
    """主函数，负责参数解析和初始化"""
    global HTTP_proxy, ips, ports, num_asyncio, url, destinations, my_timeout
    global ignore_cert, do_check200, check30x, speedtest_enabled, speedtest_max_time, logpath, csvfile, csv_writer
    parser = argparse.ArgumentParser(description='IP Direct Connection Scanner (Thread Version)')
    parser.add_argument('--proxy', type=str, help='HTTP proxy (e.g., 127.0.0.1:8080)')
    parser.add_argument('--url', type=str, help='Target URL')
    parser.add_argument('--ipr', type=str, help='IP range (e.g., 10.0.0.0/24)')
    parser.add_argument('--ipf', type=str, help='File with IPs or IP ranges (one per line)')
    parser.add_argument('--ports', type=str, default="443", help='Port or start port (default 443)')
    parser.add_argument('--portt', type=str, help='End port (exclusive)')
    parser.add_argument('--numasyncio', type=int, help='Max threads per batch (default 20)')
    parser.add_argument('--timeout', type=int, help='Connection/Handshake timeout (default 5s)')
    parser.add_argument('--ignore-cert', action='store_true', help='Ignore SSL certificate errors')
    # 添加互斥组
    mutex_group = parser.add_mutually_exclusive_group()
    mutex_group.add_argument('--check200', action='store_true', help='Save 200 OK responses to files')
    # speedtest_group = mutex_group.add_argument_group() # 创建一个子组来关联 --speedtest 和 --maxtime
    # 实际上 argparse 的互斥组和参数组用法需要调整，直接将 --maxtime 与 --speedtest 绑定更清晰
    # 我们先按原互斥组定义，然后在解析后检查 --maxtime 的依赖关系
    parser.add_argument('--speedtest', action='store_true', help='Perform download speed test for 200 responses')
    parser.add_argument('--maxtime', type=float, default=10.0, help='Max download time for speed test in seconds (default 10.0s, requires --speedtest)')
    parser.add_argument('--check30x', action='store_true', help='Check for 3xx redirects and save them')
    args = parser.parse_args()
    # 处理参数
    if args.proxy:
        HTTP_proxy = args.proxy
    if args.url:
        url = args.url
    if args.ipr:
        try:
            temp_ips = IP(args.ipr)
            for ip in temp_ips:
                ips.append(str(ip))
        except Exception as e:
            print(f"Error parsing IP range '{args.ipr}': {e}")
    if args.ipf:
        try:
            with open(args.ipf, 'r') as f:
                for line in f:
                    temp_ip = line.strip()
                    if not temp_ip:
                        continue
                    if '/' in temp_ip:
                        try:
                            temp_ips = IP(temp_ip)
                            for ip in temp_ips:
                                ips.append(str(ip))
                        except Exception as e:
                             print(f"Warning: Skipping invalid IP range '{temp_ip}' in file: {e}")
                    else:
                        try:
                            IP(temp_ip)
                            ips.append(temp_ip)
                        except:
                            print(f"Warning: Skipping invalid IP '{temp_ip}' in file")
        except Exception as e:
             print(f"Error reading IP file '{args.ipf}': {e}")
    if args.ports:
        try:
            start_port = int(args.ports)
            if args.portt:
                try:
                    ports = list(range(start_port, int(args.portt)))
                except ValueError:
                    print(f"Invalid end port '{args.portt}', using default port 443")
                    ports = [start_port]
            else:
                ports = [start_port]
        except ValueError:
            print(f"Invalid start port '{args.ports}', using default port 443")
            ports = [443]
    if args.numasyncio:
        try:
            num_asyncio = int(args.numasyncio)
        except ValueError:
            print(f"Invalid numasyncio '{args.numasyncio}', using default 20")
    if args.timeout:
        try:
            my_timeout = int(args.timeout)
        except ValueError:
            print(f"Invalid timeout '{args.timeout}', using default 5")
    if args.ignore_cert:
        ignore_cert = True
    if args.check200:
        do_check200 = True
    if args.check30x:
        check30x = True
    # 处理 --speedtest 和 --maxtime
    # 检查 --maxtime 是否在 --speedtest 未启用时被使用
    if args.maxtime != 10.0 and not args.speedtest:
        parser.error("--maxtime requires --speedtest.")
    if args.speedtest:
        speedtest_enabled = True
        speedtest_max_time = args.maxtime # 使用用户提供的值或默认值
    # 去重IP
    seen_ips = set()
    unique_ips = [ip for ip in ips if not (ip in seen_ips or seen_ips.add(ip))]
    # 构建目标列表
    for ip in unique_ips:
        for port in ports:
            destinations.append((ip, port))
    print(f"Total unique targets: {len(destinations)}")
    if speedtest_enabled:
        print(f"Speedtest enabled with max time: {speedtest_max_time}s")
    # 设置日志路径
    logpath = os.path.join("rsp", md5((url + str(time.time())).encode()).hexdigest())
    os.makedirs(logpath, exist_ok=True)
    print(f"Log path: {logpath}")
    # 打开CSV文件并写入表头
    csv_filename = os.path.join(logpath, "results.csv")
    try:
        csvfile = open(csv_filename, "w", newline='', encoding='utf-8')
        csv_writer = csv.writer(csvfile)
        csv_header = ["IP", "Port", "Status", "Message"]
        if speedtest_enabled:
            csv_header.append("Speed")
        csv_writer.writerow(csv_header)
    except Exception as e:
        print(f"Failed to create CSV log file '{csv_filename}': {e}")
        csvfile = None # 确保 csvfile 为 None，fprint 不会尝试写入
    # 开始扫描
    try:
        mode_str = "Speedtest" if speedtest_enabled else ("Check200" if do_check200 else ("Check30x" if check30x else "Basic"))
        print(f"Starting {mode_str} scan...")
        scan_ips()
    except KeyboardInterrupt:
        print("\nScan interrupted by user.")
    finally:
        if csvfile and not csvfile.closed:
            csvfile.close()
    print(f"Scan finished. Results saved in CSV: {csv_filename}")

if __name__ == "__main__":
    main()