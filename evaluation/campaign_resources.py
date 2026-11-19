"""Read-only Docker ownership inspection and cgroup-v2 monitoring for one comparison."""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ARMS = ("baseline", "candidate")
ROLES = ("baseline-api", "baseline-qdrant", "candidate-api", "candidate-qdrant", "ollama", "runner")
LABEL = "org.enterprise-rag.eval."
MIB = 1024**2
GIB = 1024**3
SAMPLE_SECONDS = 5


class ResourceStop(ValueError):
    """A controlled stop reason suitable for private evidence."""


def full_id(value):
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", value))
        and int(value, 16) != 0
    )


def loopback_url(address, port):
    if address not in {"127.0.0.1", "::1"} or not str(port).isascii() or not str(port).isdigit():
        raise ValueError("API binding must be a numeric loopback address and port")
    port = int(port)
    if not 1 <= port <= 65535 or port == 18000:
        raise ValueError("Invalid or deployed API port")
    host = "[::1]" if address == "::1" else address
    return f"http://{host}:{port}"


def resolve_backend(api, endpoint, port, containers):
    """Resolve an API's actual service URL within its Docker network memberships."""
    url = urlsplit(endpoint)
    if (
        url.scheme != "http"
        or not url.hostname
        or url.port != port
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("Unexpected internal backend URL")
    for entry in api["HostConfig"].get("ExtraHosts") or ():
        if re.split(r"[:=]", entry, maxsplit=1)[0].lower() == url.hostname:
            raise ValueError("API backend resolution is overridden by extra_hosts")
    env = dict(item.split("=", 1) for item in api["Config"]["Env"] if "=" in item)
    if any(value for key, value in env.items() if key.lower() in {"http_proxy", "all_proxy"}):
        bypass = env.get("no_proxy", env.get("NO_PROXY", "")).lower().split(",")
        if not any(v.strip() in {"*", url.hostname, f"{url.hostname}:{port}"} for v in bypass):
            raise ValueError("Require direct NO_PROXY routing to experiment backends")
    networks = {n["NetworkID"] for n in api["NetworkSettings"]["Networks"].values()}
    matches = set()
    for node in containers:
        for net in node["NetworkSettings"]["Networks"].values():
            if net["NetworkID"] not in networks:
                continue
            names = {node["Name"].lstrip("/"), net.get("IPAddress"), net.get("GlobalIPv6Address")}
            names.update(net.get("Aliases") or [])
            names.update(net.get("DNSNames") or [])
            if url.hostname in names:
                matches.add(node["Id"])
    if len(matches) != 1:
        raise ValueError("Internal backend URL must resolve to one inspected container")
    return matches.pop()


def validate_ownership(campaign, receipt, targets=None):
    if not isinstance(campaign, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", campaign):
        raise ValueError("Invalid campaign ID")
    if (
        receipt.get("campaign_id") != campaign
        or receipt.get("backend_mode") != "campaign-only-shared-ollama"
    ):
        raise ValueError("Require the named campaign's dedicated experimental Ollama")
    services = receipt["services"]
    if set(services) != set(ROLES):
        raise ValueError("Require two API/Qdrant pairs, one Ollama and one runner")
    ids = set()
    for role, node in services.items():
        cid = node["id"]
        if (
            not full_id(cid)
            or cid in ids
            or node["campaign_label"] != campaign
            or node["role_label"] != role
            or not full_id(node["image_id"])
        ):
            raise ValueError("Container identity, campaign ownership or role mismatch")
        ids.add(cid)
        cg = Path(node["cgroup"])
        if not cg.is_absolute() or ".." in cg.parts or cg.name not in {cid, f"docker-{cid}.scope"}:
            raise ValueError("Invalid full-ID cgroup binding")
        limit = node["memory_bytes"]
        if type(limit) is not int or (
            limit < 12 * GIB
            if role == "ollama"
            else limit != (256 if role == "runner" else 512) * MIB
        ):
            raise ValueError("Unexpected experimental container memory limit")
    model = services["ollama"]
    if (
        model["memory_swap_bytes"] != model["memory_bytes"]
        or model["loading"]["OLLAMA_NUM_PARALLEL"] != "1"
        or int(model["loading"]["OLLAMA_MAX_LOADED_MODELS"] or 0) < 2
    ):
        raise ValueError("Require unswappable Ollama with one request and capacity for both models")
    networks = receipt["networks"]
    if not networks or any(
        not full_id(net) or not members or not set(members) <= ids
        for net, members in networks.items()
    ):
        raise ValueError("Experiment bridge has unknown owner or unrelated member")
    members = {cid for group in networks.values() for cid in group}
    if members != ids - {services["runner"]["id"]}:
        raise ValueError("Require exclusive service bridges and a host-network runner")
    endpoints = set()
    for arm in ARMS:
        api, db = services[f"{arm}-api"], services[f"{arm}-qdrant"]
        if (
            api["model_backend_id"] != model["id"]
            or api["qdrant_backend_id"] != db["id"]
            or any(
                not any({api["id"], other} <= set(group) for group in networks.values())
                for other in (model["id"], db["id"])
            )
        ):
            raise ValueError("API routing must use its own Qdrant and the single campaign Ollama")
        endpoint = loopback_url(api["bind_ip"], api["bind_port"])
        if endpoint in endpoints or (targets is not None and endpoint != targets[arm]["url"]):
            raise ValueError("Plan API endpoint differs from the inspected published binding")
        endpoints.add(endpoint)
    for kind in ("api", "qdrant"):
        if (
            services[f"baseline-{kind}"]["cpu_limits"]
            != services[f"candidate-{kind}"]["cpu_limits"]
        ):
            raise ValueError("Unequal experimental CPU limits")
    roots = receipt["storage"]
    if set(roots) != set(ROLES) - {"runner"} or not receipt["protected_storage"]:
        raise ValueError("Require separate data roots and a protected production storage inventory")
    for role, root in roots.items():
        path = Path(root["path"])
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("Require canonical storage roots")
        others = [v for k, v in roots.items() if k != role] + receipt["protected_storage"]
        for other in others:
            other_path = Path(other["path"])
            if (
                root["inode"] == other["inode"]
                or path.is_relative_to(other_path)
                or other_path.is_relative_to(path)
            ):
                raise ValueError("Experiment data roots overlap one another or protected storage")


def docker(*args):
    return subprocess.check_output(["docker", *args], timeout=30)


def storage_root(path):
    real = Path(path).resolve(strict=True)
    stat = real.stat()
    return {"path": str(real), "inode": [stat.st_dev, stat.st_ino]}


def inspect_campaign(campaign, protected_roots):
    """Inspect only the labeled containers and their attached bridges. Never serialize raw env."""
    ids = (
        docker("ps", "-q", "--no-trunc", "--filter", f"label={LABEL}campaign={campaign}")
        .decode()
        .split()
    )
    if len(ids) != len(ROLES) or not all(full_id(cid) for cid in ids):
        raise ValueError("Expected six running containers labeled for this campaign")
    nodes = json.loads(docker("inspect", "--type=container", *ids))
    services, bridges, storage = {}, set(), {}
    for node in nodes:
        labels = node["Config"]["Labels"]
        role = labels.get(LABEL + "role")
        if (
            role not in ROLES
            or role in services
            or not node["State"]["Running"]
            or node["State"]["OOMKilled"]
        ):
            raise ValueError("Missing, duplicate or unhealthy experiment role")
        host = node["HostConfig"]
        cgroup_lines = Path(f"/proc/{int(node['State']['Pid'])}/cgroup").read_text().splitlines()
        paths = [line[3:] for line in cgroup_lines if line.startswith("0::")]
        if len(paths) != 1:
            raise ValueError("Host cgroup v2 inspection is required")
        record = services[role] = {
            "id": node["Id"],
            "image_id": node["Image"].removeprefix("sha256:"),
            "campaign_label": labels.get(LABEL + "campaign"),
            "role_label": role,
            "cgroup": paths[0],
            "memory_bytes": host["Memory"],
            "memory_swap_bytes": host["MemorySwap"],
            "cpu_limits": [host[k] for k in ("NanoCpus", "CpuQuota", "CpuPeriod", "CpusetCpus")],
            "restart_count": node["RestartCount"],
        }
        if role == "runner":
            if host["NetworkMode"] != "host":
                raise ValueError("Run the client on the test host's numeric loopback")
            continue
        bridges.update(n["NetworkID"] for n in node["NetworkSettings"]["Networks"].values())
        env = dict(item.split("=", 1) for item in node["Config"]["Env"] if "=" in item)
        destination = (
            env.get("INGEST_DATA_DIR", "/data")
            if role.endswith("-api")
            else "/root/.ollama"
            if role == "ollama"
            else "/qdrant/storage"
        )
        mounts = [m["Source"] for m in node["Mounts"] if m["Destination"] == destination]
        if len(mounts) != 1:
            raise ValueError(f"Missing dedicated storage mount for {role}")
        storage[role] = storage_root(mounts[0])
        ports = {k: v for k, v in (node["NetworkSettings"]["Ports"] or {}).items() if v}
        if role.endswith("-api"):
            if set(ports) != {"8000/tcp"} or len(ports["8000/tcp"]) != 1:
                raise ValueError("Require a single published API binding")
            binding = ports["8000/tcp"][0]
            record.update(
                bind_ip=binding["HostIp"],
                bind_port=binding["HostPort"],
                model_backend_id=resolve_backend(node, env["OLLAMA_URL"], 11434, nodes),
                qdrant_backend_id=resolve_backend(node, env["QDRANT_URL"], 6333, nodes),
            )
            record["model_settings"] = {
                "chat_model": env["OLLAMA_CHAT_MODEL"],
                "embed_model": env["OLLAMA_EMBED_MODEL"],
                "num_predict": int(env["OLLAMA_NUM_PREDICT"]),
                "think": env.get("OLLAMA_THINK", "default"),
            }
        elif ports:
            raise ValueError("Experimental database and model services must be private")
        if role == "ollama":
            record["loading"] = {
                key: env.get(key)
                for key in (
                    "OLLAMA_NUM_PARALLEL",
                    "OLLAMA_MAX_LOADED_MODELS",
                    "OLLAMA_KEEP_ALIVE",
                    "OLLAMA_CONTEXT_LENGTH",
                )
            }
    if not bridges or not all(full_id(net) for net in bridges):
        raise ValueError("Missing experiment network IDs")
    nets = json.loads(docker("network", "inspect", *sorted(bridges)))
    if any(n["Driver"] != "bridge" for n in nets):
        raise ValueError("Expected experiment-only bridge networks")
    receipt = {
        "campaign_id": campaign,
        "backend_mode": "campaign-only-shared-ollama",
        "observed_at": datetime.now(UTC).isoformat(),
        "services": services,
        "networks": {n["Id"]: sorted(n["Containers"]) for n in nets},
        "storage": storage,
        "protected_storage": [storage_root(root) for root in protected_roots],
    }
    validate_ownership(campaign, receipt)
    return receipt


def counters(path):
    return {
        name.rstrip(":"): int(value)
        for name, value, *_ in (line.split() for line in path.read_text().splitlines())
    }


def resource_sample(services, disk_path, *, proc=Path("/proc"), cgroup=Path("/sys/fs/cgroup")):
    mem, vm = counters(proc / "meminfo"), counters(proc / "vmstat")
    if not any(
        line.startswith("0::") and Path(line[3:]).is_relative_to(services["runner"]["cgroup"])
        for line in (proc / "self/cgroup").read_text().splitlines()
    ):
        raise ResourceStop("Runner process is outside its inspected cgroup")
    containers = {}
    for role, node in services.items():
        root = cgroup / node["cgroup"].lstrip("/")
        containers[role] = {
            "inode": root.stat().st_ino,
            "current": int((root / "memory.current").read_text()),
            "peak": int((root / "memory.peak").read_text()),
            "limit": int((root / "memory.max").read_text()),
            "swap": int((root / "memory.swap.current").read_text()),
            "swap_limit": (root / "memory.swap.max").read_text().strip(),
            "swap_peak": int((root / "memory.swap.peak").read_text())
            if (root / "memory.swap.peak").exists()
            else None,
            "events": counters(root / "memory.events"),
            "populated": counters(root / "cgroup.events")["populated"],
        }
    return {
        "utc": datetime.now(UTC).isoformat(),
        "disk_free": shutil.disk_usage(disk_path).free,
        "mem_total": mem["MemTotal"] * 1024,
        "mem_available": mem["MemAvailable"] * 1024,
        "host_swap_used": (mem["SwapTotal"] - mem["SwapFree"]) * 1024,
        "pswpin": vm["pswpin"],
        "pswpout": vm["pswpout"],
        "containers": containers,
    }


class Monitor:
    def __init__(self, services, output, disk_path, reader=resource_sample):
        self.services, self.output, self.disk_path, self.reader = (
            services,
            output,
            disk_path,
            reader,
        )
        self.baseline = None

    def check(self):
        try:
            sample = self.reader(self.services, self.disk_path)
        except ResourceStop:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise ResourceStop("resource-monitor-unavailable") from exc
        if self.baseline is None:
            self.baseline = sample
        for counter in ("pswpin", "pswpout"):
            sample[counter + "_delta"] = sample[counter] - self.baseline[counter]
        if self.output is not None:
            with open(self.output, "a", encoding="utf-8", opener=private_open) as stream:
                stream.write(json.dumps(sample, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        if sample["disk_free"] < 4 * GIB:
            raise ResourceStop("disk-below-4-GiB")
        for role, current in sample["containers"].items():
            original = self.baseline["containers"][role]
            if (
                not current["populated"]
                or current["inode"] != original["inode"]
                or current["limit"] != self.services[role]["memory_bytes"]
            ):
                raise ResourceStop(f"container-identity-or-limit-changed:{role}")
            if current["swap"] or current["swap_peak"]:
                raise ResourceStop(f"experiment-swap:{role}")
            if current["swap_limit"] != "0" and (current["swap_peak"] is None or role == "ollama"):
                raise ResourceStop(f"unverified-experiment-swap-limit:{role}")
            if current["events"]["oom"] or current["events"]["oom_kill"]:
                raise ResourceStop(f"experiment-oom:{role}")
        return sample

    async def supervise(self, work):
        self.check()
        task = asyncio.create_task(work())
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=SAMPLE_SECONDS)
                self.check()
            return await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def private_open(path, flags):
    return os.open(path, flags, 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument(
        "--protect",
        action="append",
        required=True,
        type=Path,
        help="Original production storage source root; repeat for each volume/bind",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = inspect_campaign(args.campaign, args.protect)
    with open(args.output, "x", encoding="utf-8", opener=private_open) as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
