import os
import requests
import zipfile
import shutil
import sys
import subprocess
from tqdm import tqdm
import configparser

# --- 全局配置与初始化 ---
GAME_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_FILE_PATH = os.path.join(GAME_DIR, "SCRIPTS", "UpdaterConfig.ini")
LOCAL_VERSION_FILE = os.path.join(GAME_DIR, "SCRIPTS", "LOC_VER.txt")
GAME_EXECUTABLE = os.path.join(GAME_DIR, "NFSC.exe") 
TEMP_DIR = os.path.join(GAME_DIR, "TEMP_UPDATE")

# 全局网络会话，提升连接复用效率
session = requests.Session()

# 核心变量
SERVER_VERSION_URL = None
UPDATE_PACKAGE_URL_TEMPLATE = None
VERSION_LIST_URL = None
CHANGELOG_FILE = None
DELETE_LIST_FILE = None
MIN_SUPPORTED_FILENAME = None
UPDATE_WARNINGS = []

# --- 辅助函数 ---

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    print("在线更新检查系统")
    print("请确保以管理员身份运行此程序以获取完整权限\n")

def add_warning(warning_message):
    UPDATE_WARNINGS.append(warning_message)
    print(f"警告：{warning_message}")

def ask_retry_or_exit(error_message):
    while True:
        choice = input(f"{error_message}，是否重新尝试？(Y/N)：").upper()
        if choice == "Y": return True
        if choice == "N": 
            print("操作取消，退出程序")
            sys.exit()
        print("无效输入")

def parse_version(version_str):
    try:
        return [int(part) for part in version_str.split('.')]
    except (ValueError, AttributeError):
        return []

def check_disk_space(required_size_mb=100):
    """检查磁盘空间是否足够（默认100MB）"""
    try:
        free_bytes = shutil.disk_usage(GAME_DIR).free
        required_bytes = required_size_mb * 1024 * 1024
        return free_bytes >= required_bytes
    except Exception:
        return True  # 检查失败时允许继续

# --- 核心功能函数 ---

def load_config():
    global SERVER_VERSION_URL, UPDATE_PACKAGE_URL_TEMPLATE, VERSION_LIST_URL
    global CHANGELOG_FILE, DELETE_LIST_FILE, MIN_SUPPORTED_FILENAME
    
    config = configparser.ConfigParser()
    try:
        if not os.path.exists(CONFIG_FILE_PATH):
            raise FileNotFoundError()
        config.read(CONFIG_FILE_PATH, encoding='utf-8')
        paths = config['Paths']
        
        SERVER_VERSION_URL = paths['server_version_url']
        UPDATE_PACKAGE_URL_TEMPLATE = paths['update_package_url_template']
        VERSION_LIST_URL = paths['version_list_url']
        CHANGELOG_FILE = paths['changelog_filename']
        DELETE_LIST_FILE = paths['delete_list_filename']
        MIN_SUPPORTED_FILENAME = paths['min_supported_filename']
        
        return True
    except Exception:
        print("错误：配置文件缺失或格式错误")
        return False

def get_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE): 
        return None
    try:
        with open(LOCAL_VERSION_FILE, "r") as f:
            return f.read().strip()
    except IOError: 
        return None

def fetch_server_data(url, description="服务器数据"):
    """通用网络请求函数"""
    try:
        print(f"正在获取{description}...")
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text.strip()
    except requests.exceptions.Timeout:
        print(f"错误：获取{description}超时")
        return None
    except requests.exceptions.RequestException:
        print(f"错误：无法获取{description}")
        return None
    except Exception as e:
        print(f"错误：获取{description}时发生异常 - {e}")
        return None

def get_server_version():
    """直接从服务器获取最新版本号"""
    return fetch_server_data(SERVER_VERSION_URL, "最新版本信息")

def get_version_list():
    """获取并排序版本列表"""
    raw_data = fetch_server_data(VERSION_LIST_URL, "版本列表")
    if raw_data is None:
        return None
    
    versions = [v.strip() for v in raw_data.split('\n') if v.strip()]
    valid_versions = [v for v in versions if parse_version(v)]
    valid_versions.sort(key=parse_version)
    return valid_versions

def get_min_supported_version():
    """获取最低支持版本"""
    return fetch_server_data(MIN_SUPPORTED_FILENAME, "最低支持版本")

def get_update_chain(current_version, target_version, all_versions):
    """获取从当前版本到目标版本需要更新的版本链"""
    current_parsed = parse_version(current_version)
    target_parsed = parse_version(target_version)
    
    if not current_parsed or not target_parsed:
        return []
    
    update_chain = []
    for v in all_versions:
        v_parsed = parse_version(v)
        if not v_parsed:
            continue
            
        if current_parsed < v_parsed <= target_parsed:
            update_chain.append(v)
    
    return update_chain

def download_update(version):
    """下载指定版本的更新包"""
    print(f"正在下载 {version} 版本的更新文件...")
    update_url = UPDATE_PACKAGE_URL_TEMPLATE.format(version=version)
    update_file = os.path.join(GAME_DIR, f"Update_{version}.zip")
    
    # 清理可能存在的残留文件
    if os.path.exists(update_file):
        try: 
            os.remove(update_file)
            print("正在清理残留文件...")
        except Exception: 
            add_warning("清理残留文件失败")
    
    try:
        # 磁盘空间检查
        if not check_disk_space(100):
            print("警告：磁盘空间不足")
            if input("是否继续下载？(Y/N)：").upper() != "Y":
                return None
        
        response = session.get(update_url, stream=True, timeout=300)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(update_file, "wb") as f, tqdm(
            desc=f"下载 {version}", 
            total=total_size, 
            unit="B", 
            unit_scale=True, 
            unit_divisor=1024
        ) as bar:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
        
        print(f"{version} 版本更新下载完成")
        return update_file
        
    except requests.exceptions.Timeout:
        print(f"错误：下载 {version} 版本更新超时")
        return None
    except requests.exceptions.RequestException:
        print(f"错误：下载 {version} 版本更新失败")
        return None
    except Exception as e:
        print(f"错误：下载 {version} 版本时发生异常 - {e}")
        return None

def apply_update(update_file, target_version):
    """解压并应用更新"""
    print(f"正在安装更新到 {target_version}...")
    
    # 备份当前版本号
    backup_version = get_local_version()
    
    try:
        # 预检ZIP有效性
        if not zipfile.is_zipfile(update_file):
            raise ValueError("更新包格式损坏或不是有效的ZIP文件")
        
        # 清理临时目录
        if os.path.exists(TEMP_DIR):
            print("正在清理临时目录...")
            shutil.rmtree(TEMP_DIR)
        
        os.makedirs(TEMP_DIR)
        
        # 解压更新包
        print("正在解压更新文件...")
        with zipfile.ZipFile(update_file, 'r') as zip_ref:
            zip_ref.extractall(TEMP_DIR)
        
        # 处理删除列表
        delete_list_path = os.path.join(TEMP_DIR, DELETE_LIST_FILE)
        if os.path.exists(delete_list_path):
            print("正在移除无用文件...")
            with open(delete_list_path, "r") as f:
                for line in f:
                    file_to_delete = line.strip()
                    if file_to_delete:
                        full_path = os.path.join(GAME_DIR, file_to_delete)
                        if os.path.exists(full_path):
                            try:
                                if os.path.isdir(full_path):
                                    shutil.rmtree(full_path)
                                else:
                                    os.remove(full_path)
                            except Exception:
                                add_warning(f"无法删除旧文件: {file_to_delete}")
            print("无用文件移除完成")
        
        # 增量复制文件（保持原版逻辑）
        print("正在复制更新文件...")
        for root, dirs, files in os.walk(TEMP_DIR):
            # 计算相对路径
            relative_path = os.path.relpath(root, TEMP_DIR)
            target_root = os.path.join(GAME_DIR, relative_path)
            
            # 跳过删除列表文件（不复制到游戏目录）
            if relative_path == '.' and DELETE_LIST_FILE in files:
                files.remove(DELETE_LIST_FILE)
            
            # 创建目标目录（如果不存在）
            if not os.path.exists(target_root):
                os.makedirs(target_root)
            
            # 复制文件（增量更新）
            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_root, file)
                
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception:
                    add_warning(f"更新文件复制失败: {os.path.join(relative_path, file)}")
        
        print("更新文件复制完成")
        
        # 更新版本号
        with open(LOCAL_VERSION_FILE, "w") as f:
            f.write(target_version)
        
        print(f"成功更新至版本 {target_version}")
        return True
        
    except Exception as e:
        print(f"错误：安装 {target_version} 版本失败 - {e}")
        
        # 失败时尝试恢复版本号
        try:
            if backup_version:
                with open(LOCAL_VERSION_FILE, "w") as f:
                    f.write(backup_version)
                print("版本信息已从上一次更新失败中恢复")
        except Exception:
            add_warning("版本信息恢复失败")
            
        return False
        
    finally:
        # 清理临时目录
        if os.path.exists(TEMP_DIR):
            try:
                print("正在清理临时文件...")
                shutil.rmtree(TEMP_DIR, ignore_errors=True)
                print("临时文件清理完成")
            except Exception:
                add_warning("临时文件清理失败")

def cleanup_update_package(update_package):
    """清理更新包文件"""
    if os.path.exists(update_package):
        print("正在清理更新文件...")
        try:
            os.remove(update_package)
            print("更新文件清理完成")
        except Exception:
            add_warning("更新文件清理失败")

def start_game():
    """启动游戏"""
    print("正在启动游戏...")
    try:
        subprocess.Popen([GAME_EXECUTABLE])
        return True
    except Exception:
        print("错误：启动游戏失败")
        return False

def show_final_summary(update_chain, final_version):
    """显示最终更新摘要"""
    clear_screen()
    print_header()
    print("本次更新摘要：")
    print()
    print(f"已成功更新至 {final_version} 版本")
    print(f"更新路径: {' → '.join(update_chain)}")
    print()
    
    if UPDATE_WARNINGS:
        print(f"更新过程中存在 {len(UPDATE_WARNINGS)} 个警告：")
        print()
        for warning in UPDATE_WARNINGS:
            print(f"- {warning}")
        print()
        print("这些警告通常不会影响游戏运行，如果存在问题请联系管理员协助")
        print()
    else:
        print("所有更新已完成")
        print()

def user_choice_and_exit(message, show_changelog=True):
    """询问用户是否启动游戏或退出"""
    if message:
        print(message)
    if show_changelog:
        print(f"您可以查阅游戏目录下的\"{CHANGELOG_FILE}\"更新日志以获取本次更新详情")
    
    while True:
        choice = input("是否启动游戏？(Y/N)：").upper()
        if choice == "Y":
            if start_game():
                sys.exit()
            else:
                if ask_retry_or_exit("启动游戏失败"):
                    continue
                else:
                    return
        elif choice == "N":
            print("操作取消，退出程序")
            sys.exit()
        else:
            print("无效输入")

# --- 主程序流程 ---

def main():
    os.system("title 在线更新检查系统")
    
    # 加载配置
    while True:
        clear_screen()
        print_header()
        if load_config():
            break
        if not ask_retry_or_exit("配置加载失败，请联系管理员协助"):
            return
    
    # 检查更新主循环
    while True:
        clear_screen()
        print_header()
        print("正在检查更新...")
        
        # 获取本地版本
        local_version_str = get_local_version()
        if local_version_str is None:
            print("错误：获取本地版本信息失败")
            if not ask_retry_or_exit("请联系管理员协助"):
                return
            continue
        
        # 获取服务器版本信息
        server_version_str = get_server_version()
        all_versions = get_version_list()
        min_supported_version = get_min_supported_version()
        
        # 检查网络请求结果
        if server_version_str is None:
            if not ask_retry_or_exit("无法获取最新版本信息"):
                return
            continue
            
        if all_versions is None:
            if not ask_retry_or_exit("无法获取版本列表信息"):
                return
            continue
        
        # 检查版本是否过低
        if min_supported_version:
            local_version_parsed = parse_version(local_version_str)
            min_version_parsed = parse_version(min_supported_version)
            
            if local_version_parsed and min_version_parsed and local_version_parsed < min_version_parsed:
                print(f"错误：当前版本 {local_version_str} 过低，最低支持版本为 {min_supported_version}")
                print("游戏版本过低无法在线更新，请联系管理员获取完整版本")
                input("按任意键退出程序...")
                sys.exit()
        elif min_supported_version is None:
            # 无法获取最低版本时的处理
            print("警告：无法获取最低支持版本信息，继续进行更新可能存在风险")
            print("请联系管理员确认当前版本是否支持在线更新")
            print()
            
            # 询问用户是否继续
            while True:
                choice = input("是否继续更新？(Y/N)：").upper()
                if choice == "Y":
                    break
                elif choice == "N":
                    print("操作取消，退出程序")
                    sys.exit()
                else:
                    print("无效输入")
        
        local_version = parse_version(local_version_str)
        server_version = parse_version(server_version_str)
        
        print(f"当前版本: {local_version_str}")
        print(f"最新版本: {server_version_str}")
        print()
        
        if not local_version or not server_version or not all_versions:
            print("错误：获取游戏版本信息失败")
            if not ask_retry_or_exit("请联系管理员协助"):
                return
            continue
        
        if local_version < server_version:
            # 获取需要更新的版本链
            update_chain = get_update_chain(local_version_str, server_version_str, all_versions)
            if not update_chain:
                print("错误：版本信息不完整，无法计算更新路径")
                if not ask_retry_or_exit("请联系管理员协助"):
                    return
                continue
            break
        else:
            user_choice_and_exit("已为最新版本，无可用的更新", show_changelog=False)
            return
    
    # 显示版本对比并询问是否下载
    clear_screen()
    print_header()
    print(f"当前版本: {local_version_str}")
    print(f"最新版本: {server_version_str}")
    print(f"需要更新的版本: {' -> '.join(update_chain)}")
    print()
    
    while True:
        choice = input("检测到新版本，是否下载安装？(Y/N)：").upper()
        if choice == "Y":
            # 清空警告信息
            global UPDATE_WARNINGS
            UPDATE_WARNINGS = []
            
            success = True
            total_versions = len(update_chain)
            
            for index, version in enumerate(update_chain, 1):
                clear_screen()
                print_header()
                print(f"更新进度: {index}/{total_versions} - 正在处理版本 {version}")
                print()
                
                update_package = download_update(version)
                if not update_package:
                    success = False
                    break
                    
                if not apply_update(update_package, version):
                    success = False
                    break
                    
                # 清理当前版本的更新包
                cleanup_update_package(update_package)
                print(f"版本 {version} 已更新完成")
                print()
            
            if success:
                # 显示最终摘要
                final_version = server_version_str
                show_final_summary(update_chain, final_version)
                user_choice_and_exit("", show_changelog=True)
            else:
                clear_screen()
                print_header()
                if not ask_retry_or_exit("更新过程失败，请联系管理员协助"):
                    return
        elif choice == "N":
            print("操作取消，退出程序")
            return
        else:
            print("无效输入")

if __name__ == "__main__":
    main()