import platform
import subprocess
import socket
import re
from concurrent.futures import ThreadPoolExecutor

def _ping_ip(ip: str):
    """Посылает короткий пакет на порт устройства, чтобы ОС добавила его в ARP."""
    try:
        # Пробуем стукнуться в miio порт 54321 или yeelight 55443
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.1)
            s.sendto(b"", (ip, 54321))
    except Exception:
        pass

def warm_up_arp(subnet_prefix="192.168.0"):
    """Параллельно опрашивает всю подсеть за 1 секунду."""
    ips = [f"{subnet_prefix}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(_ping_ip, ips)

def get_ip_by_mac(target_mac: str, subnet_prefix="192.168.0") -> str | None:
    # Приводим искомый MAC к единому виду: строчные буквы, без ведущих нулей в октетах (на Windows)
    clean_target = target_mac.lower().replace("-", ":")
    
    # 1. Прогреваем ARP-кэш
    warm_up_arp(subnet_prefix)

    # 2. Читаем кэш ОС
    system = platform.system()
    
    # Для Linux (парсинг напрямую из ядра)
    if system == "Linux":
        try:
            with open("/proc/net/arp", "r") as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip, mac = parts[0], parts[3].lower()
                        if mac == clean_target:
                            return ip
        except Exception:
            pass

    # Для Windows / фолбэк для Linux
    try:
        output = subprocess.check_output("arp -a", shell=True, text=True)
        for line in output.splitlines():
            # Заменяем дефисы на двоеточия для сравнения
            normalized_line = line.lower().replace("-", ":")
            if clean_target in normalized_line:
                match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                if match:
                    return match.group(1)
    except Exception as e:
        print(f"[!] Ошибка вызова arp: {e}")

    return None

# Пример проверки
if __name__ == "__main__":
    # Укажите MAC лампы из token_extractor (например "04:cf:8c:12:34:56")
    TEST_MAC = "7C:C2:94:6D:EA:D7" 
    
    print(f"Поиск IP для MAC {TEST_MAC}...")
    ip = get_ip_by_mac(TEST_MAC, subnet_prefix="192.168.0")
    print(f"Результат: {ip}")