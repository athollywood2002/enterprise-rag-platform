"""Synthetic Docker inspection and kernel files. The tests use no daemon or model."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from search_fixture import seed, snapshot

from evaluation import campaign_resources as host


@pytest.fixture
def docker_view(tmp_path, monkeypatch):
    one, two = "a" * 64, "b" * 64
    campaign = "synthetic-pair"
    nodes, networks, namespaces = {}, {}, {}
    for i, role in enumerate(host.ROLES, 1):
        cid = f"{i:064x}"
        nets = (
            [one, two]
            if role == "ollama"
            else ([] if role == "runner" else [one if role.startswith("baseline") else two])
        )
        for net in nets:
            networks.setdefault(net, {"Id": net, "Containers": {}, "Driver": "bridge"})[
                "Containers"
            ][cid] = {"IPv4Address": f"172.20.{1 if net == one else 2}.{i}/24"}
        limit = 12 * host.GIB if role == "ollama" else (256 if role == "runner" else 512) * host.MIB
        env = {
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "2",
            "OLLAMA_URL": "http://ollama:11434",
            "QDRANT_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "rag_eval_reference",
            "OLLAMA_CHAT_MODEL": "synthetic",
            "OLLAMA_EMBED_MODEL": "synthetic-embed",
            "OLLAMA_NUM_PREDICT": "1536",
            "OLLAMA_THINK": "default",
            "API_KEY": "private-fixture-key",
        }
        source = tmp_path / role
        source.mkdir()
        dest = (
            "/data"
            if role.endswith("-api")
            else "/root/.ollama"
            if role == "ollama"
            else "/qdrant/storage"
        )
        nodes[role] = {
            "Name": "/" + role,
            "Id": cid,
            "Image": "sha256:" + "c" * 64,
            "RestartCount": 0,
            "State": {"Running": True, "OOMKilled": False, "Pid": 100000 + i},
            "Config": {
                "Env": [k + "=" + v for k, v in env.items()],
                "Labels": {host.LABEL + "campaign": campaign, host.LABEL + "role": role},
            },
            "HostConfig": {
                "Memory": limit,
                "MemorySwap": limit,
                "NanoCpus": 0,
                "CpuQuota": 0,
                "CpuPeriod": 0,
                "CpusetCpus": "0-5",
                "NetworkMode": "host" if role == "runner" else "bridge",
            },
            "NetworkSettings": {
                "Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(19100 + i)}]}
                if role.endswith("-api")
                else {},
                "Networks": {
                    n: {
                        "NetworkID": n,
                        "IPAddress": f"172.20.{1 if n == one else 2}.{i}",
                        "Aliases": [role, "qdrant" if role.endswith("-qdrant") else role],
                    }
                    for n in nets
                },
            },
            "Mounts": [{"Source": str(source), "Destination": dest}],
        }
        namespaces[f"/proc/{100000 + i}/cgroup"] = "0::/docker/" + cid

    def docker(*args):
        if args[0] == "ps":
            return ("\n".join(n["Id"] for n in nodes.values())).encode()
        if args[0] == "inspect":
            return json.dumps(list(nodes.values())).encode()
        if args[0] == "exec":
            api = next(n for n in nodes.values() if n["Id"] == args[1])
            net_id = next(iter(api["NetworkSettings"]["Networks"]))
            db = nodes[api["Config"]["Labels"][host.LABEL + "role"].replace("-api", "-qdrant")]
            return json.dumps([db["NetworkSettings"]["Networks"][net_id]["IPAddress"]]).encode()
        assert args[:2] == ("network", "inspect")
        return json.dumps(list(networks.values())).encode()

    monkeypatch.setattr(host, "docker", docker)
    read_text = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda p: namespaces[str(p)] if str(p) in namespaces else read_text(p)
    )
    protected = tmp_path / "production"
    protected.mkdir()
    data = snapshot()
    for arm in host.ARMS:
        with closing(sqlite3.connect(tmp_path / (arm + "-api") / "library.sqlite3")) as db:
            seed(db, data)
    render = {
        "name": campaign,
        "services": {
            role: {"environment": dict(v.split("=", 1) for v in n["Config"]["Env"])}
            for role, n in nodes.items()
        },
    }
    return (
        nodes,
        networks,
        lambda: host.inspect_campaign(
            campaign, [protected], json.dumps(render).encode(), json.dumps(data.manifest).encode()
        ),
    )


def test_capture_binds_exact_identities_and_drops_sensitive_environment(docker_view):
    nodes, _, capture = docker_view
    receipt = capture()
    assert "private-fixture-key" not in json.dumps(receipt)
    for arm in host.ARMS:
        api = receipt["services"][arm + "-api"]
        assert api["model_backend_id"] == nodes["ollama"]["Id"]
        assert api["qdrant_backend_id"] == nodes[arm + "-qdrant"]["Id"]


@pytest.mark.parametrize(
    "change",
    [
        lambda n, nets: n["baseline-api"]["HostConfig"].update(ExtraHosts=["ollama:192.0.2.3"]),
        lambda n, nets: n["baseline-api"]["Config"]["Env"].append(
            "HTTP_PROXY=http://unrelated.invalid"
        ),
        lambda n, nets: n["ollama"]["NetworkSettings"].update(
            Ports={"11434/tcp": [{"HostIp": "127.0.0.1", "HostPort": "11999"}]}
        ),
        lambda n, nets: n["candidate-qdrant"].update(Mounts=n["baseline-qdrant"]["Mounts"]),
        lambda n, nets: n["baseline-api"]["Config"]["Env"].append(
            "OLLAMA_URL=http://unrelated.invalid:11434"
        ),
        lambda n, nets: next(iter(nets.values()))["Containers"].update({"f" * 64: {}}),
    ],
)
def test_wrong_routes_storage_or_foreign_members_rejected(docker_view, change):
    nodes, nets, capture = docker_view
    change(nodes, nets)
    with pytest.raises(ValueError):
        capture()


def test_resource_reader_tracks_actual_runner_and_separates_paging(tmp_path):
    proc, cg = tmp_path / "proc", tmp_path / "cg"
    cid = "a" * 64
    (proc / "self").mkdir(parents=True)
    (cg / cid).mkdir(parents=True)
    (proc / "meminfo").write_text(
        "MemTotal: 32000000 kB\nMemAvailable: 20000000 kB\nSwapTotal: 4096 kB\nSwapFree: 3072 kB\n"
    )
    (proc / "vmstat").write_text("pswpin 172\npswpout 300\n")
    (proc / "self/cgroup").write_text("0::/" + cid + "\n")
    for key, val in {
        "memory.current": 10,
        "memory.peak": 20,
        "memory.max": 256 * host.MIB,
        "memory.swap.current": 0,
        "memory.swap.max": 0,
        "memory.events": "oom 0\noom_kill 0\n",
        "cgroup.events": "populated 1\n",
    }.items():
        (cg / cid / key).write_text(str(val))
    services = {"runner": {"cgroup": "/" + cid}}
    sample = host.resource_sample(services, tmp_path, proc=proc, cgroup=cg)
    assert sample["host_swap_used"] == host.MIB and sample["pswpout"] == 300
    assert sample["containers"]["runner"]["swap"] == 0
    assert sample["containers"]["runner"]["swap_peak"] is None
    (proc / "self/cgroup").write_text("0::/unrelated")
    with pytest.raises(host.ResourceStop, match="outside"):
        host.resource_sample(services, tmp_path, proc=proc, cgroup=cg)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE revisions SET state='retired' WHERE id='rev-0'",
        "UPDATE revisions SET state='staging' WHERE id='rev-0'",
        "UPDATE documents SET points='[\"other\"]' WHERE id='doc-0'",
        "UPDATE documents SET fingerprint='other' WHERE id='doc-0'",
        "UPDATE files SET job_id='outside-job' WHERE doc_id='doc-0'",
    ],
)
def test_physical_sqlite_scope_is_read_before_ownership_receipt(docker_view, sql):
    nodes, _, capture = docker_view
    root = Path(nodes["candidate-api"]["Mounts"][0]["Source"])
    with closing(sqlite3.connect(root / "library.sqlite3")) as db:
        db.execute(sql)
        db.commit()
    with pytest.raises(ValueError, match="revision|point memberships"):
        capture()


def test_namespace_dns_must_match_database_ip(docker_view, monkeypatch):
    _, _, capture = docker_view
    original = host.docker
    monkeypatch.setattr(
        host, "docker", lambda *args: b'["172.31.1.6"]' if args[0] == "exec" else original(*args)
    )
    with pytest.raises(ValueError, match="DNS"):
        capture()
