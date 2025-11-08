import threading
import ssl
from IPy import IP
import socket
import argparse
import time
import os
import csv
from hashlib import md5
import base64  # 添加base64用于WebSocket密钥

# 全局变量
HTTP_proxy = None
ips = []
ports = [443]
num_asyncio = 20
url = "https://www.baidu.com"
destinations = []
my_timeout = 5  # 连接和握手超时
ignore_cert = False
do_check200 = False
check30x = False
speedtest_enabled = False
speedtest_max_time = 10.0  # 测速最大时间，默认10秒
logpath = ""
csvfile = None
csv_writer = None
lock = threading.Lock()
is_wss = False  # 标记是否使用WSS协议
is_https = False  # 标记是否使用HTTPS协议

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
                row.append("")  # 如果没有速度信息或未测速，则该列留空
        # 写入CSV行
        if csvfile and not csvfile.closed:  # 检查文件是否有效
            csv_writer.writerow(row)
            csvfile.flush()  # 确保数据写入磁盘
        # 同时打印到控制台
        speed_str = f" ({speed_kbs:.2f} KB/s)" if speed_kbs is not None else ""
        print(f"{ip}:{port}--------{status}--------{message}{speed_str}")
    except Exception as e:  # 捕获 fprint 内部可能的错误
        # 即使日志记录本身出错，也尽量打印到控制台
        print(f"LOGGING ERROR for {ip}:{port} - {e}")
    finally:
        lock.release()

def fetch_with_ip(url, ip, port):
    """核心请求函数，处理单个IP和端口的请求"""
    global HTTP_proxy, my_timeout, ignore_cert, do_check200, check30x, speedtest_enabled, speedtest_max_time, logpath
    global is_wss, is_https
    sock = None
    ssl_sock = None
    status_code = "INIT"  # 用于记录最终状态到CSV
    message = ""
    speed_kbs = None
    headers_received = False
    response_code = None  # 从HTTP响应中解析出的状态码 (e.g., "200", "404")
    logged = False  # 标志位，防止重复记录
    handshake_completed = False  # TLS握手是否完成
    ws_handshake_completed = False  # WebSocket握手是否完成

    try:
        # --- 连接阶段 ---
        host = url.split('/')[0]
        path = "/" + url.split('/', 1)[1] if '/' in url else "/"
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(my_timeout)  # 使用连接超时
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
        
        # --- TLS/SSL握手阶段 ---
        ssl_context = ssl.create_default_context()
        if ignore_cert:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        try:
            ssl_sock = ssl_context.wrap_socket(sock, server_hostname=host)
            handshake_completed = True  # TLS握手成功
        except ssl.SSLError as e:
            # TLS握手失败
            status_code = "TLS_HANDSHAKE_FAILED"
            message = f"SSL handshake failed: {str(e)}"
            fprint(ip, port, status_code, message)
            logged = True
            return
        except Exception as e:
            status_code = "TLS_HANDSHAKE_ERROR"
            message = f"SSL handshake error: {str(e)}"
            fprint(ip, port, status_code, message)
            logged = True
            return

        # --- 发送请求 ---
        if is_wss:
            # 生成随机WebSocket密钥
            ws_key = base64.b64encode(os.urandom(16)).decode('utf-8')
            http_request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {ws_key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "User-Agent: Mozilla/5.0\r\n\r\n"
            )
        else:
            http_request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "Connection: close\r\n"
                "User-Agent: Mozilla/5.0\r\n\r\n"
            )
        ssl_sock.sendall(http_request.encode('utf-8'))
        
        # --- 处理响应 ---
        if is_wss:
            # 尝试接收WebSocket握手响应
            try:
                # 读取响应头
                response_data = b""
                while b'\r\n\r\n' not in response_data:
                    chunk = ssl_sock.recv(1024)
                    if not chunk:
                        break
                    response_data += chunk
                    if len(response_data) > 4096:  # 防止无限接收
                        break
                
                response_str = response_data.decode('utf-8', errors='replace')
                if "HTTP/1.1 101" in response_str and "Upgrade: websocket" in response_str:
                    ws_handshake_completed = True
                    status_code = "WSS_SUCCESS"
                    message = "WebSocket handshake successful"
                    
                    # 尝试发送ping帧验证连接
                    try:
                        # 发送ping帧 (unmasked)
                        ssl_sock.sendall(b'\x89\x00')
                        ssl_sock.settimeout(2)
                        pong = ssl_sock.recv(1024)
                        if pong and len(pong) > 0 and pong[0] == 0x8A:  # Pong opcode (0x8A)
                            message = "WebSocket handshake and ping successful"
                        else:
                            message = "WebSocket handshake successful but no pong response"
                    except Exception as e:
                        message = f"WS handshake ok but ping failed: {str(e)}"
                    
                    # WSS不需要继续接收数据，直接记录结果
                    fprint(ip, port, status_code, message)
                    logged = True
                    return
                else:
                    status_code = "WSS_HANDSHAKE_FAILED"
                    message = f"Handshake failed: {response_str.splitlines()[0] if response_str else 'No response'}"
                    fprint(ip, port, status_code, message)
                    logged = True
                    return
            except Exception as e:
                status_code = "WSS_HANDSHAKE_ERROR"
                message = str(e)
                fprint(ip, port, status_code, message)
                logged = True
                return
        else:
            # --- HTTP响应处理 ---
            response_data = b""
            headers_data = b""
            body_bytes_received = 0
            speedtest_start_time = None
            start_time = time.time()  # 记录开始接收数据的时间

            while True:
                # 设置读取超时
                ssl_sock.settimeout(my_timeout)

                try:
                    data = ssl_sock.recv(16384)
                    if not data:
                        break
                except socket.timeout:
                    break

                # --- 解析HTTP头 ---
                if not headers_received:
                    headers_data += data
                    header_end_index = headers_data.find(b'\r\n\r\n')
                    if header_end_index != -1:
                        headers_received = True
                        # 提取头部
                        try:
                            status_line = headers_data.split(b'\r\n', 1)[0].decode('utf-8', errors='replace')
                            response_code = status_line.split(' ', 2)[1] if len(status_line.split(' ', 2)) >= 2 else "PARSE_ERROR"
                            status_code = response_code  # 将HTTP状态码作为CSV状态
                        except Exception as e:
                            status_code = "HEADER_PARSE_ERROR"
                            message = f"Error parsing headers: {e}"
                            fprint(ip, port, status_code, message)
                            logged = True
                            return

                        # 处理状态码
                        if speedtest_enabled and response_code == '200':
                            speedtest_start_time = time.time()
                            body_bytes_received += len(data) - (header_end_index + 4)
                        if (do_check200 and response_code == '200') or (check30x and response_code.startswith('3')):
                            response_data = headers_data

                else:
                    # --- 处理HTTP体 ---
                    if speedtest_enabled and speedtest_start_time is not None and response_code == '200':
                        body_bytes_received += len(data)
                        elapsed = time.time() - speedtest_start_time
                        if elapsed >= speedtest_max_time:
                            # 测速结束
                            if elapsed > 0:
                                speed_kbs = (body_bytes_received / 1024.0) / elapsed
                            status_code = f"{response_code}_SPEED"
                            message = f"{speedtest_max_time}s test completed"
                            fprint(ip, port, status_code, message, speed_kbs)
                            logged = True
                            break

                    # 保存模式累积数据
                    if (do_check200 and response_code == '200') or (check30x and response_code.startswith('3')):
                        response_data += data

            # --- 循环结束后的处理 ---
            if not logged:
                # 如果测速开始但未完成
                if speedtest_enabled and speedtest_start_time is not None and response_code == '200':
                    elapsed_final = time.time() - speedtest_start_time
                    if elapsed_final > 0:
                        speed_kbs = (body_bytes_received / 1024.0) / elapsed_final
                    status_code = response_code
                    message = "Connection closed before test time"
                    fprint(ip, port, status_code, message, speed_kbs)
                    logged = True
                elif headers_received:
                    status_code = response_code if response_code else "UNKNOWN"
                    # 保存响应内容
                    if not speedtest_enabled:
                        if do_check200 and status_code == '200':
                            try:
                                safe_ip = ip.replace(':', '.')
                                output_dir = os.path.join(logpath, status_code)
                                os.makedirs(output_dir, exist_ok=True)
                                output_file = os.path.join(output_dir, f"{safe_ip}_{port}.rsp")
                                with open(output_file, 'wb') as f:
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
                else:
                    status_code = "NO_HEADERS"
                    message = "Connection closed before headers received"
                    fprint(ip, port, status_code, message)
                    logged = True

    except socket.timeout as e:
        if not handshake_completed:
            status_code = "CONN_TIMEOUT"
            message = "Connection or TLS handshake timeout"
        elif is_wss and not ws_handshake_completed:
            status_code = "WS_HANDSHAKE_TIMEOUT"
            message = "WebSocket handshake timeout"
        else:
            status_code = "READ_TIMEOUT"
            message = "Response read timeout"
        fprint(ip, port, status_code, message)
        logged = True
    except ssl.SSLError as e:
        if not handshake_completed:
            status_code = "TLS_HANDSHAKE_FAILED"
            message = f"SSL handshake failed: {str(e)}"
        else:
            status_code = "SSL_ERROR"
            message = str(e)
        fprint(ip, port, status_code, message)
        logged = True
    except socket.error as e:
        status_code = "SOCKET_ERROR"
        fprint(ip, port, status_code, str(e), speed_kbs)
        logged = True
    except Exception as e:
        status_code = "INTERNAL_ERROR"
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
        # *** 兜底记录 ***
        if not logged:
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
    global is_wss, is_https
    
    parser = argparse.ArgumentParser(description='IP Direct Connection Scanner (Thread Version)')
    parser.add_argument('--proxy', type=str, help='HTTP proxy (e.g., 127.0.0.1:8080)')
    parser.add_argument('--url', type=str, required=True, help='Target URL (e.g., https://www.baidu.com or wss://example.com)')
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
    parser.add_argument('--speedtest', action='store_true', help='Perform download speed test for 200 responses')
    parser.add_argument('--maxtime', type=float, default=10.0, help='Max download time for speed test in seconds (default 10.0s, requires --speedtest)')
    parser.add_argument('--check30x', action='store_true', help='Check for 3xx redirects and save them')
    args = parser.parse_args()
    
    # 处理URL
    if args.url.startswith('wss://'):
        is_wss = True
        is_https = False
        url = args.url[6:]
    elif args.url.startswith('ws://'):
        print("Warning: ws:// (non-secure WebSocket) is not supported. Only wss:// is supported.")
        is_wss = True
        is_https = False
        url = args.url[5:]
    elif args.url.startswith('https://'):
        is_wss = False
        is_https = True
        url = args.url[8:]
    elif args.url.startswith('http://'):
        print("Warning: http:// is not supported for this scanner. Only https:// or wss:// is supported.")
        is_wss = False
        is_https = False
        url = args.url[7:]
    else:
        print("Error: URL must start with https:// or wss://")
        return

    # 处理其他参数
    if args.proxy:
        HTTP_proxy = args.proxy
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
    if args.speedtest:
        speedtest_enabled = True
        speedtest_max_time = args.maxtime
    # 检查 --maxtime 是否在 --speedtest 未启用时被使用
    if args.maxtime != 10.0 and not args.speedtest:
        parser.error("--maxtime requires --speedtest.")
    
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
        csvfile = None  # 确保 csvfile 为 None，fprint 不会尝试写入
    
    # 开始扫描
    try:
        if is_wss:
            mode_str = "WSS"
        else:
            mode_str = "Speedtest" if speedtest_enabled else ("Check200" if do_check200 else ("Check30x" if check30x else "Basic"))
        print(f"Starting {mode_str} scan for {args.url}...")
        scan_ips()
    except KeyboardInterrupt:
        print("\nScan interrupted by user.")
    finally:
        if csvfile and not csvfile.closed:
            csvfile.close()
    print(f"Scan finished. Results saved in CSV: {csv_filename}")

if __name__ == "__main__":
    main()