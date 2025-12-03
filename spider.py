import requests
from lxml import etree
import time
import os
import json
import subprocess # 用于执行命令行工具 yt-dlp
from http.cookiejar import MozillaCookieJar
import re # 【新增】用于从 URL 中提取 ID

def load_cookies_from_file(cookie_file='cookies.txt'):
    """
    从Netscape格式的cookies文件加载cookie
    :param cookie_file: cookie文件路径
    :return: cookiejar对象
    """
    if not os.path.exists(cookie_file):
        print(f"警告: Cookie文件 {cookie_file} 不存在。在未登录状态下，可能会错过某些歌曲或遇到验证。")
        return None
    
    try:
        # 确保文件可以被读取，并尝试加载
        cookie_jar = MozillaCookieJar(cookie_file)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        print(f"✓ 成功加载 {len(cookie_jar)} 个cookies")
        return cookie_jar
    except Exception as e:
        print(f"加载Cookie失败: {e}")
        print("请检查 cookies.txt 文件格式是否为 Netscape 格式，并且文件编码为 UTF-8。")
        return None


def crawl_music_links(playlist_id, cookie_jar=None):
    """
    爬取网易云音乐歌单中的歌曲链接
    首先尝试使用公开的API接口（/api/playlist/detail），如果失败则回退到HTML解析。
    :param playlist_id: 歌单ID
    :param cookie_jar: MozillaCookieJar对象，用于保持登录状态
    :return: 歌曲列表
    """
    # 基础URL
    BASE_URL = "https://music.163.com"
    
    # 关键：添加完整的请求头，模拟真实浏览器
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        # 重要的 Referer 头，有助于避免某些反爬策略
        'Referer': 'https://music.163.com/',
        # API调用使用更通用的 Accept
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        # 【关键修改】强制服务器返回未压缩的数据，以解决乱码和 JSONDecodeError
        'Accept-Encoding': 'identity', 
    }
    
    # 方法1：直接访问API接口（推荐）
    api_url = f'{BASE_URL}/api/playlist/detail?id={playlist_id}'
    
    # 创建session保持会话
    session = requests.Session()
    
    # 如果有cookie，添加到session
    if cookie_jar:
        # 使用 update 是为了将 CookieJar 中的所有 cookie 添加到 session 中
        session.cookies.update(cookie_jar)
    
    try:
        print(f"正在请求歌单ID: {playlist_id}")
        print(f"API URL: {api_url}\n")
        
        response = session.get(api_url, headers=headers, timeout=15)
        
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code != 200:
            print(f"API请求失败！状态码：{response.status_code}")
            # fall through to HTML crawl
        else:
            # 解析JSON数据
            try:
                data = response.json()
                
                if data.get('code') == 200 and 'result' in data and 'tracks' in data['result']:
                    tracks = data['result']['tracks']
                    print(f"✓ API 成功找到 {len(tracks)} 首歌曲\n")
                    
                    urls = []
                    for i, track in enumerate(tracks, 1):
                        song_id = track['id']
                        song_name = track['name']
                        artist = ', '.join([ar['name'] for ar in track['artists']])
                        song_url = f"{BASE_URL}/song?id={song_id}"
                        
                        song_info = {
                            'index': i,
                            'title': song_name,
                            'artist': artist,
                            'url': song_url,
                            'song_id': song_id
                        }
                        
                        urls.append(song_info)
                        
                        print(f"[{i}] {song_name} - {artist}")
                        print(f"    URL: {song_url}")
                        print(f"    ID: {song_id}")
                        print("-" * 60)
                    
                    return urls
                else:
                    print("API返回数据格式异常或权限不足 (可能需要更完整的Cookie)")
                    print(f"返回内容: {data.get('msg', '无错误信息')}")
            
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {e}")
                # 尝试使用 response.content 打印可读的乱码
                try:
                    text_preview = response.content.decode('utf-8', errors='ignore')[:500]
                except:
                    text_preview = "无法解码的二进制内容。"
                print(f"响应内容（部分）: {text_preview}")
                # fall through to HTML crawl

    except requests.RequestException as e:
        print(f"请求错误: {e}")
        # fall through to HTML crawl
        
    # 方法2：如果API失败，尝试解析HTML（备用方案）
    return crawl_from_html(playlist_id, session, headers)


def crawl_from_html(playlist_id, session, headers):
    """
    备用方案：从HTML页面解析（通过iframe内的隐藏数据）
    """
    print("\n尝试从HTML页面解析 (备用方案)...")
    
    BASE_URL = "https://music.163.com"
    # 直接访问歌单页面的URL
    url = f"{BASE_URL}/playlist?id={playlist_id}"
    
    try:
        # HTML请求也使用添加了 'Accept-Encoding': 'identity' 的 headers
        response = session.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # 确保使用正确的编码解析 HTML
            response.encoding = 'utf-8'
            tree = etree.HTML(response.text)
            
            # 尝试方法1: JSON数据
            json_data_elements = tree.xpath('//textarea[@id="song-list-pre-data"]')
            if json_data_elements and json_data_elements[0].text:
                print("✓ 通过 HTML 页面中的 JSON 数据块获取歌曲信息。")
                try:
                    data = json.loads(json_data_elements[0].text)
                    urls = []
                    for i, track in enumerate(data, 1):
                        song_id = track.get('id')
                        urls.append({
                            'index': i,
                            'title': track.get('name'),
                            'artist': ', '.join([ar['name'] for ar in track['artists']]) if 'artists' in track else '未知艺术家',
                            'url': f"{BASE_URL}/song?id={song_id}",
                            'song_id': song_id
                        })
                        print(f"[{i}] {track.get('name')} - {urls[-1]['artist']} (ID: {song_id})")
                    return urls
                except Exception as e:
                    print(f"HTML内的JSON解析失败: {e}")
            
            # 尝试方法2: 隐藏的 <ul> 链接列表
            elements = tree.xpath('//ul[@class="f-hide"]//a[@href]')
            if elements:
                print(f"✓ 通过 HTML 页面中的隐藏列表找到 {len(elements)} 个链接。")
                urls = []
                for i, elem in enumerate(elements, 1):
                    href = elem.get('href')
                    title = elem.text.strip()
                    
                    if href and '/song?id=' in href:
                        full_url = BASE_URL + href if href.startswith('/') else href
                        song_id = href.split('id=')[1].split('&')[0] if 'id=' in href else None
                        
                        urls.append({
                            'index': i,
                            'title': title,
                            'artist': '需要单独请求', # 此时HTML列表缺少艺术家信息
                            'url': full_url,
                            'song_id': song_id
                        })
                        print(f"[{i}] {title} (ID: {song_id})")

                return urls
            
            print("HTML解析失败：未能找到隐藏的歌曲数据或链接。")
            
        else:
            print(f"HTML页面请求失败！状态码：{response.status_code}")
            
        return []
        
    except requests.RequestException as e:
        print(f"HTML页面请求错误: {e}")
        return []
    except Exception as e:
        print(f"HTML解析过程中发生未知错误: {e}")
        return []


def save_to_file(urls, filename='songs.txt'):
    """保存结果到文件"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"总共找到 {len(urls)} 首歌曲\n")
            f.write("=" * 60 + "\n\n")
            
            for item in urls:
                f.write(f"[{item['index']}] {item['title']}")
                if 'artist' in item:
                    f.write(f" - {item['artist']}")
                f.write(f"\nURL: {item['url']}\n")
                if item.get('song_id'):
                    f.write(f"ID: {item['song_id']}\n")
                f.write("\n")
        
        print(f"\n✓ 已保存到 {filename} 文件")
    except Exception as e:
        print(f"保存文件失败: {e}")


def download_songs_with_ytdlp(songs, cookie_file):
    """
    使用 yt-dlp 尝试下载歌曲。
    注意：网易云音乐链接可能无法直接下载，yt-dlp 可能会尝试搜索同名歌曲。
    """
    print("\n" + "="*60)
    print("开始使用 yt-dlp 尝试下载歌曲")
    print("="*60)
    
    # 检查 yt-dlp 是否安装
    try:
        # 使用 check=True 确保如果命令失败会抛出异常
        subprocess.run(['yt-dlp', '--version'], check=True, capture_output=True)
    except FileNotFoundError:
        print("\n错误: 找不到 yt-dlp 命令。请确保您已安装 yt-dlp 并将其添加到系统路径中。")
        print("安装方法：pip install yt-dlp (推荐) 或参考官方文档。")
        return

    output_dir = "Netease_Downloads"
    os.makedirs(output_dir, exist_ok=True)
    
    # 检查 Cookie 文件是否存在，构建 --cookies 参数
    cookie_args = []
    if os.path.exists(cookie_file):
        cookie_args.extend(['--cookies', cookie_file])
        print(f"使用 Cookie 文件: {cookie_file}")
    else:
        print(f"警告: Cookie文件 {cookie_file} 不存在，下载可能受限。")

    
    for i, song in enumerate(songs, 1):
        song_url = song['url']
        song_title = song['title']
        song_artist = song['artist']
        
        # 构建输出文件名格式： 艺术家 - 标题.mp3
        output_template = os.path.join(output_dir, f"{song_artist} - {song_title}.%(ext)s")
        # 由于 yt-dlp 的元数据注入可能对 Netease 链接无效，这里直接用 Python 格式化文件名。

        # 构造 yt-dlp 命令列表
        command = [
            'yt-dlp',
            song_url, # 传入网易云音乐链接
            '-o', output_template, # 输出路径和格式
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '0', # 最佳音质
            '--retries', '5', # 增加重试次数
        ]
        
        # 添加 Cookie 参数
        command.extend(cookie_args)
        
        # 打印执行的命令（供调试参考）
        print(f"\n[{i}/{len(songs)}] 正在尝试下载: {song_title} - {song_artist}")
        print(f"执行命令: {' '.join(command)}")
        
        try:
            # 执行命令，禁用 check=True 以避免 yt-dlp 失败时程序崩溃
            result = subprocess.run(command, check=False, capture_output=True, text=True, encoding='utf-8')
            
            if result.returncode == 0:
                print(f"✓ 下载成功。文件应保存到 {output_dir} 目录。")
            else:
                print(f"✗ 下载失败或跳过 (错误码: {result.returncode})。")
                if "ERROR: This URL is not supported" in result.stderr:
                    print("提示: yt-dlp 不直接支持此网易云链接。")
                elif "WARNING: [netease]" in result.stderr:
                    print("警告: yt-dlp 无法获取音频流，可能因为加密或版权限制。")
                
        except Exception as e:
            print(f"执行 yt-dlp 时发生错误: {e}")
            
        # 简短等待，避免对服务器造成过大压力
        time.sleep(0.5) 


if __name__ == "__main__":
    # --- 配置区域 ---
    # Cookie文件路径 (可选，用于获取会员专属或完整列表)
    cookie_file = "cookies.txt"
    # --- 配置区域结束 ---
    
    print("="*60)
    print("网易云音乐歌单爬虫")
    print("="*60)
    
    # 引导用户输入完整的 URL 或纯 ID
    input_value = input("请输入网易云音乐歌单的完整 URL : )
    
    playlist_id = None
    
    # 尝试从 URL 中提取歌单 ID
    # 歌单ID通常出现在 'id=' 后面
    match = re.search(r'id=(\d+)', input_value)
    
    if match:
        playlist_id = match.group(1)
    elif input_value.isdigit():
        # 如果输入的只是纯数字，则认为是歌单 ID
        playlist_id = input_value
    
    if not playlist_id or not playlist_id.isdigit():
        print("\n错误：未能从输入中提取有效的歌单 ID。请检查 URL 或 ID 格式是否正确。")
        # 退出程序
        exit() 

    print(f"解析得到的歌单ID: {playlist_id}")
    print("-" * 60)
    
    # 提示用户如何获取Cookie
    if not os.path.exists(cookie_file):
        print("\n【注意】: cookies.txt 文件未找到，将以游客身份尝试爬取。")
        print("如果您需要爬取私密或需要登录才能查看的歌单，请创建该文件并登录网易云音乐后导出Cookie。")
        print("【cookies.txt 格式示例】:")
        print("# Netscape HTTP Cookie File")
        print(".music.163.com\tTRUE\t/\tFALSE\t0\tMUSIC_U\tyour_value_here")
        print("-" * 60 + "\n")
    
    # 加载Cookie
    cookie_jar = load_cookies_from_file(cookie_file)
    
    # 爬取链接
    songs = crawl_music_links(playlist_id, cookie_jar)
    
    # 打印统计
    print(f"\n{'='*60}")
    print(f"总共找到 {len(songs)} 首歌曲")
    print(f"{'='*60}\n")
    
    # 保存到文件
    if songs:
        save_to_file(songs)
        
        # 【新增功能调用】询问用户是否下载
        print("【yt-dlp 下载功能提示】")
        print("此功能需要您的系统安装了 'yt-dlp' 命令。")
        
        user_choice = input("\n是否立即使用 yt-dlp 尝试下载所有歌曲? (y/n): ")
        if user_choice.lower() == 'y':
            download_songs_with_ytdlp(songs, cookie_file)
    else:
        print("\n【爬取失败建议】:")
        print("1. 确保歌单ID正确。")
        print("2. 如果歌单是私密的，请确保 cookies.txt 存在且包含有效的登录信息 (MUSIC_U)。")
        print("3. 检查您的网络连接或尝试等待一段时间再试。")
