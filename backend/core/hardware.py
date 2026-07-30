"""
nexus — Inventario de hardware del equipo.

Reúne todo lo que se puede: CPU, RAM, disco, GPU, placa base, audio, red, SO.
Windows: usa PowerShell/CIM para GPU, placa base y audio (psutil no los da).
Cachea el inventario "estático" (no cambia) y refresca solo lo dinámico.
"""
from __future__ import annotations

import platform
import subprocess

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_static_cache: dict | None = None


def _cpu_temp():
    """Temperatura de CPU en °C (int) o None. Windows no la da por psutil → probamos
    LibreHardwareMonitor/OpenHardwareMonitor por WMI y, si no, la zona térmica ACPI."""
    if HAS_PSUTIL:
        try:
            sensors = psutil.sensors_temperatures() or {}
            for key in ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal"):
                if sensors.get(key):
                    return round(max(s.current for s in sensors[key] if s.current))
            for arr in sensors.values():
                if arr and arr[0].current:
                    return round(arr[0].current)
        except Exception:
            pass
    if platform.system() != "Windows":
        return None
    try:
        import wmi
        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            try:
                w = wmi.WMI(namespace=ns)
                temps = [s for s in w.Sensor() if getattr(s, "SensorType", "") == "Temperature"]
                cpu = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")
                       and any(k in (s.Name or "") for k in ("Package", "Core", "CCD", "Tctl"))]
                if cpu:
                    return round(max(cpu))
                cpu_any = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")]
                if cpu_any:
                    return round(max(cpu_any))
            except Exception:
                continue
    except Exception:
        pass
    try:
        import wmi
        vals = [z.CurrentTemperature for z in
                wmi.WMI(namespace="root\\wmi").MSAcpi_ThermalZoneTemperature()]
        if vals:
            return round((min(vals) / 10.0) - 273.15)
    except Exception:
        pass
    return None


def _gpu_dynamic() -> list[dict]:
    """Temp/uso/VRAM en vivo de las GPU NVIDIA (nvidia-smi). [] si no hay NVIDIA."""
    gpus = []
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (out.stdout or "").strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 5:
                try:
                    gpus.append({"name": p[0], "temp_c": round(float(p[1])),
                                 "util": round(float(p[2])),
                                 "mem_used_mb": round(float(p[3])),
                                 "mem_total_mb": round(float(p[4]))})
                except ValueError:
                    continue
    except Exception:
        pass
    return gpus


def _ps(query: str) -> list[dict]:
    """Ejecuta una consulta CIM por PowerShell y devuelve lista de dicts."""
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"{query} | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import json
        data = json.loads(out.stdout or "[]")
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def _static() -> dict:
    global _static_cache
    if _static_cache is not None:
        return _static_cache
    info: dict = {"os": {}, "cpu": {}, "gpu": [], "board": {}, "audio": [], "ram_slots": []}

    # SO
    info["os"] = {"system": platform.system(), "release": platform.release(),
                  "version": platform.version(), "machine": platform.machine(),
                  "node": platform.node()}

    # CPU
    cpu_name = platform.processor()
    if HAS_PSUTIL:
        freq = psutil.cpu_freq()
        info["cpu"] = {"name": cpu_name or "?",
                       "cores_fisicos": psutil.cpu_count(logical=False),
                       "cores_logicos": psutil.cpu_count(logical=True),
                       "freq_max_mhz": round(freq.max) if freq else None}

    if platform.system() == "Windows":
        cpus = _ps("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed")
        if cpus:
            c = cpus[0]
            info["cpu"]["name"] = c.get("Name", info["cpu"].get("name"))
            info["cpu"].setdefault("cores_fisicos", c.get("NumberOfCores"))
            info["cpu"].setdefault("cores_logicos", c.get("NumberOfLogicalProcessors"))
        # VRAM real: nvidia-smi es fiable (AdapterRAM de WMI se corta a ~4 GB por bug de 32 bits)
        nvidia_vram = {}
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in out.stdout.strip().splitlines():
                if "," in line:
                    nm, mem = line.rsplit(",", 1)
                    nvidia_vram[nm.strip().lower()] = round(int(mem.strip()) / 1024, 0)
        except Exception:
            pass
        for g in _ps("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion"):
            name = g.get("Name", "?")
            # 1) nvidia-smi (real) → 2) registro qwMemorySize → 3) AdapterRAM (poco fiable)
            vram = None
            for k, v in nvidia_vram.items():
                if k in name.lower() or name.lower() in k:
                    vram = v
                    break
            if vram is None:
                ram = g.get("AdapterRAM") or 0
                vram = round(ram / 2**30, 1) if ram else None
            info["gpu"].append({"name": name, "vram_gb": vram, "driver": g.get("DriverVersion")})
        # Registro: VRAM real de 64 bits (respaldo si no hay nvidia-smi)
        if any(x.get("vram_gb") in (None, 4.0) for x in info["gpu"]):
            reg = _ps("Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -Name HardwareInformation.qwMemorySize -EA SilentlyContinue | Select-Object HardwareInformation.qwMemorySize")
            for r in reg:
                q = r.get("HardwareInformation.qwMemorySize")
                if q and info["gpu"]:
                    info["gpu"][0]["vram_gb"] = round(int(q) / 2**30, 1)
                    break
        boards = _ps("Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product")
        if boards:
            info["board"] = {"fabricante": boards[0].get("Manufacturer"),
                             "modelo": boards[0].get("Product")}
        bios = _ps("Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion")
        if bios:
            info["board"]["bios"] = bios[0].get("SMBIOSBIOSVersion")
        for a in _ps("Get-CimInstance Win32_SoundDevice | Select-Object Name"):
            if a.get("Name"):
                info["audio"].append(a["Name"])
        for m in _ps("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,Manufacturer"):
            cap = m.get("Capacity") or 0
            info["ram_slots"].append({"gb": round(int(cap) / 2**30) if cap else "?",
                                      "speed": m.get("Speed"), "marca": m.get("Manufacturer")})
    _static_cache = info
    return info


def _dynamic() -> dict:
    d: dict = {}
    if HAS_PSUTIL:
        vm = psutil.virtual_memory()
        d["cpu_percent"] = psutil.cpu_percent(interval=None)
        d["cpu_per_core"] = psutil.cpu_percent(interval=None, percpu=True)
        d["ram"] = {"total_gb": round(vm.total / 2**30, 1),
                    "usado_gb": round(vm.used / 2**30, 1), "percent": vm.percent}
        # TODOS los discos/particiones montados (C:, D:, E:...)
        d["discos"] = []
        try:
            for part in psutil.disk_partitions(all=False):
                if "cdrom" in part.opts or part.fstype == "":
                    continue
                try:
                    u = psutil.disk_usage(part.mountpoint)
                except Exception:
                    continue
                d["discos"].append({
                    "unidad": part.device.replace("\\", ""),
                    "total_gb": round(u.total / 2**30, 1),
                    "usado_gb": round(u.used / 2**30, 1),
                    "libre_gb": round(u.free / 2**30, 1),
                    "percent": u.percent})
        except Exception:
            pass
        # resumen (compat: primer disco)
        d["disco"] = d["discos"][0] if d["discos"] else {}
        # Temperatura REAL de CPU (WMI/LibreHardwareMonitor) — psutil no la da en Windows
        ct = _cpu_temp()
        if ct is not None:
            d["cpu_temp_c"] = ct
            d["temp_c"] = ct                 # compat con el campo antiguo
        # Temp/uso/VRAM en vivo de la GPU (estilo MSI Afterburner)
        d["gpus"] = _gpu_dynamic()
        try:
            bat = psutil.sensors_battery()
            if bat:
                d["bateria"] = {"percent": round(bat.percent), "enchufado": bat.power_plugged}
        except Exception:
            pass
        net = psutil.net_io_counters()
        d["red"] = {"enviado_mb": round(net.bytes_sent / 2**20),
                    "recibido_mb": round(net.bytes_recv / 2**20)}
        d["procesos"] = len(psutil.pids())
    return d


def hardware_report() -> dict:
    return {"static": _static(), "dynamic": _dynamic()}
