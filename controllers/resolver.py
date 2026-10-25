import json
import os
import subprocess
import socket
import re
from concurrent.futures import ThreadPoolExecutor
import time

CACHE_FILE = os.path.join(os.path.dirname(__file__), "ip_cache.json")

def _ping_ip(ip: str, timeout: float = 0.08):
    """Посылает короткий пакет на порт устройства, чтобы ОС добавила его в ARP."""
    try:
        # Пробуем стукнуться в miio порт 54321 или yeelight 55443
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout) # Ждем всего 0.1 секунды
            s.sendto(b"", (ip, 54321))
    except Exception:
        pass

def _load_cache() -> dict:
    """Считывает сохраненные связки {mac: ip} из ip_cache.json."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_cache(cache: dict):
    """Сохраняет актуальные связки {mac: ip} в ip_cache.json."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[!] Не удалось сохранить кэш IP: {e}")

def warm_up_arp(subnet_prefix="192.168.0"):
    """Параллельно опрашивает всю подсеть за 1 секунду."""
    ips = [f"{subnet_prefix}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(_ping_ip, ips)
    # Дать ОС 0.6 секунды, чтобы собрать запоздавшие ARP-ответы в кэш
    time.sleep(0.6)

def _get_arp_table() -> dict[str, str]:
    """Читает системную таблицу Windows (arp -a) и возвращает словарь {mac: ip}."""
    mac_to_ip = {}
    try:
        output = subprocess.check_output("arp -a", shell=True, text=True)
        for line in output.splitlines():
            line_norm = line.lower().replace("-", ":")
            match_mac = re.search(r"([0-9a-f]{2}(?::[0-9a-f]{2}){5})", line_norm)
            match_ip = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line_norm)
            if match_mac and match_ip:
                mac_to_ip[match_mac.group(1)] = match_ip.group(1)
    except Exception as e:
        print(f"[!] Ошибка вызова arp: {e}")

    return mac_to_ip

def resolve_all_ips(target_macs: list[str], subnet_prefix="192.168.0") -> dict[str, str]:
    """
    Принимает список MAC-адресов всех ламп.
    Возвращает словарь {mac: найденный_ip}.
    """
    clean_macs = [m.lower().replace("-", ":") for m in target_macs]
    cache = _load_cache()
    resolved = {}
    missing_macs = []

    # 1. Проверяем кэш для каждого MAC
    for mac in clean_macs:
        cached_ip = cache.get(mac)
        if cached_ip:
            # Быстро пингуем старый IP
            _ping_ip(cached_ip, timeout=0.05)
            resolved[mac] = cached_ip
        else:
            missing_macs.append(mac)

    # ДАЁМ WINDOWS 200 МС, ЧТОБЫ ПРИНЯТЬ ОТВЕТЫ ОТ ВСЕХ 4 ЛАМП:
    if resolved:
        time.sleep(0.2)

    # 2. Сверяем с текущим ARP-кэшем
    arp_now = _get_arp_table()
    for mac in list(resolved.keys()):
        # Если в ARP лампа не подтвердилась по старому IP — отправляем на общий скан
        if arp_now.get(mac) != resolved[mac]:
            del resolved[mac]
            missing_macs.append(mac)

    # 3. Если хоть одна лампа не нашлась по кэшу — делаем ОДИН общий прогрев
    if missing_macs:
        print("[*] Поиск новых или изменившихся IP в сети...")
        warm_up_arp(subnet_prefix)
        arp_full = _get_arp_table()

        for mac in missing_macs:
            ip = arp_full.get(mac)
            if ip:
                resolved[mac] = ip
                cache[mac] = ip

        _save_cache(cache)

    return resolved
# Пример проверки
if __name__ == "__main__":
    # Укажите MAC лампы из token_extractor (например "04:cf:8c:12:34:56")
    TEST_MAC = "7C:C2:94:6D:EA:D7" 
    
    print(f"Поиск IP для MAC {TEST_MAC}...")
    ip = resolve_all_ips([TEST_MAC], subnet_prefix="192.168.0")
    print(f"Результат: {ip}")