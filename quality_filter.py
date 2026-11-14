#!/usr/bin/env python3
"""Rank nodes by static purity and measured reachability, keeping top N per category."""
from __future__ import annotations

import argparse
import base64
import csv
import ipaddress
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

STRONG_NAME_PENALTIES = {
    "广告": 8,
    "推广": 8,
    "邀请": 8,
    "返利": 8,
    "注册": 7,
    "官网": 7,
    "付费": 7,
    "vip": 7,
    "机场": 7,
    "群": 5,
    "免费": 4,
    "白嫖": 5,
    "测试": 4,
    "测速": 4,
    "过期": 5,
    "到期": 5,
}
DEFAULT_UUID = "8" * 8 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 4 + "-" + "8" * 12
UDP_TYPES = {"hysteria", "hysteria2", "tuic"}
SECURE_TYPES = {"trojan", "hysteria2", "tuic"}


def purity_score(node: dict[str, Any]) -> tuple[int, list[str]]:
    score = 70
    notes: list[str] = []
    typ = str(node.get("type", "")).lower()
    name = str(node.get("name", ""))
    server = str(node.get("server", "")).strip("[]")
    port = int(node.get("port", 0) or 0)

    try:
        ip = ipaddress.ip_address(server)
    except ValueError:
        ip = None
    if not server:
        score -= 40
        notes.append("服务器为空")
    if ip is not None and not ip.is_global:
        score -= 45
        notes.append("非公网IP")
    if not (1 <= port <= 65535):
        score -= 30
        notes.append("端口异常")

    if typ in {"http", "socks5"}:
        score -= 15
        notes.append("明文/代理协议风险")
    elif typ in {"trojan", "hysteria2", "tuic"}:
        score += 10
    elif typ == "vless" and node.get("reality-opts"):
        score += 15
    elif typ in {"vless", "vmess"} and node.get("tls"):
        score += 7
    elif typ in {"ss", "ssr"}:
        score += 1

    if node.get("skip-cert-verify") is True:
        score -= 9
        notes.append("跳过证书校验")
    if typ not in SECURE_TYPES and typ not in {"vless", "vmess"}:
        pass
    elif not node.get("tls") and typ not in SECURE_TYPES and not node.get("reality-opts"):
        score -= 6
        notes.append("未启用TLS")

    sni = str(node.get("sni") or node.get("servername") or "")
    if sni:
        if re.search(r"(^|[/.@])(t\.me|telegram)", sni, re.I):
            score -= 8
            notes.append("SNI含推广标识")
        elif not re.fullmatch(r"[0-9.]+", sni):
            score += 3
    elif typ in SECURE_TYPES:
        score -= 3
        notes.append("缺少SNI")

    network = str(node.get("network", ""))
    if network in {"ws", "grpc", "h2"}:
        score += 2

    uuid = str(node.get("uuid", ""))
    password = str(node.get("password", ""))
    if uuid and uuid.lower() == DEFAULT_UUID:
        score -= 28
        notes.append("默认UUID")
    if password:
        if len(password) < 6:
            score -= 7
            notes.append("密码过短")
        if re.search(r"123456|password|qwerty", password, re.I):
            score -= 14
            notes.append("弱密码特征")

    if re.search(r"https?://|www\.", name, re.I):
        score -= 8
        notes.append("名称含网址")
    lowered = name.lower()
    seen_penalty = False
    for keyword, penalty in STRONG_NAME_PENALTIES.items():
        if keyword in lowered:
            score -= penalty
            seen_penalty = True
    if seen_penalty:
        notes.append("名称含推广/营销词")
    if re.search(r"telegram|t\.me|@", name, re.I):
        score -= 5
        notes.append("名称含推广渠道")
    if re.search(r"未命名|unknown|^node$|^proxy$|^test$", name, re.I):
        score -= 8
        notes.append("名称过于泛化")

    return max(1, min(100, score)), notes


def endpoint_key(node: dict[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(node.get("type", "")).lower(),
        str(node.get("server", "")).strip().lower(),
        int(node.get("port", 0) or 0),
        str(node.get("sni") or node.get("servername") or ""),
    )


def test_endpoint(node: dict[str, Any], timeout: float) -> dict[str, Any]:
    typ = str(node.get("type", "")).lower()
    server = str(node.get("server", "")).strip("[]")
    port = int(node.get("port", 0) or 0)
    result: dict[str, Any] = {
        "reachable": False,
        "latency_ms": None,
        "availability": 0,
        "status": "未测试",
    }

    if not server or not (1 <= port <= 65535):
        result["status"] = "地址异常"
        return result

    try:
        ip = ipaddress.ip_address(server)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        result["status"] = "非公网地址"
        return result

    if typ in UDP_TYPES:
        try:
            infos = socket.getaddrinfo(server, port, type=socket.SOCK_DGRAM)
        except OSError as exc:
            result["status"] = f"UDP解析失败:{exc.__class__.__name__}"
            return result
        if infos:
            result.update(reachable=True, availability=48, status="UDP已解析未端到端验证")
        return result

    best_latency: float | None = None
    last_error = ""
    for _ in range(2):
        started = time.perf_counter()
        try:
            with socket.create_connection((server, port), timeout=timeout):
                latency = (time.perf_counter() - started) * 1000
                if best_latency is None or latency < best_latency:
                    best_latency = latency
        except OSError as exc:
            last_error = exc.__class__.__name__

    if best_latency is None:
        result["status"] = f"TCP连接失败:{last_error or 'unknown'}"
        return result

    if best_latency <= 80:
        availability = 100
    elif best_latency <= 150:
        availability = 93
    elif best_latency <= 300:
        availability = 84
    elif best_latency <= 600:
        availability = 72
    elif best_latency <= 1000:
        availability = 58
    elif best_latency <= 2000:
        availability = 40
    else:
        availability = 25
    result.update(
        reachable=True,
        latency_ms=round(best_latency, 1),
        availability=availability,
        status="TCP可用",
    )
    return result


def unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def process_profile(
    source_name: str,
    output_name: str,
    snippet_name: str,
    category_groups: list[str],
    endpoint_results: dict[tuple[str, str, int, str], dict[str, Any]],
    limit: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    profile = yaml.safe_load(Path(source_name).read_text(encoding="utf-8"))
    proxies = profile.get("proxies", [])
    groups = profile.get("proxy-groups", [])
    node_by_name = {str(node.get("name", "")): node for node in proxies}
    group_by_name = {str(group.get("name", "")): group for group in groups}
    rankings: list[dict[str, Any]] = []
    selected_names: list[str] = []
    selected_set: set[str] = set()

    for category in category_groups:
        group = group_by_name.get(category)
        if not group:
            continue
        candidates: list[tuple[float, dict[str, Any]]] = []
        for name in group.get("proxies", []):
            name = str(name)
            node = node_by_name.get(name)
            if not node:
                continue
            test = endpoint_results[endpoint_key(node)]
            if not test["reachable"]:
                continue
            pure, pure_notes = purity_score(node)
            availability = int(test["availability"])
            overall = round(availability * 0.65 + pure * 0.35, 2)
            candidates.append(
                (
                    overall,
                    {
                        "profile": "meta" if "meta" in source_name else "clash",
                        "category": category,
                        "name": name,
                        "type": node.get("type", ""),
                        "server": node.get("server", ""),
                        "port": node.get("port", ""),
                        "availability": availability,
                        "purity": pure,
                        "overall": overall,
                        "latency_ms": test["latency_ms"] if test["latency_ms"] is not None else "",
                        "status": test["status"],
                        "purity_notes": ";".join(pure_notes),
                    },
                )
            )

        candidates.sort(
            key=lambda item: (
                item[1]["overall"],
                item[1]["purity"],
                item[1]["availability"],
                -(item[1]["latency_ms"] if isinstance(item[1]["latency_ms"], (int, float)) else 999999),
            ),
            reverse=True,
        )
        for rank, (_, row) in enumerate(candidates[:limit], start=1):
            row["rank"] = rank
            rankings.append(row)
            name = row["name"]
            if name not in selected_set:
                selected_set.add(name)
                selected_names.append(name)

    all_group_names = set(group_by_name)
    builtins = {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}
    for group in groups:
        if "proxies" not in group:
            continue
        filtered = unique_keep_order(
            [
                str(item)
                for item in group.get("proxies", [])
                if str(item) in selected_set or str(item) in all_group_names or str(item) in builtins
            ]
        )
        group["proxies"] = filtered or ["REJECT"]

    profile["proxies"] = [node for node in proxies if str(node.get("name", "")) in selected_set]
    header = (
        "# Best10: static purity + measured reachability; "
        "public nodes cannot be privacy-audited\n"
    )
    Path(output_name).write_text(
        header + yaml.safe_dump(profile, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    Path(snippet_name).write_text(
        yaml.safe_dump({"proxies": profile["proxies"]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return selected_names, rankings


def write_best_base64(selected_names: list[str], source: str = "list_raw.txt", output: str = "list.best.txt") -> int:
    wanted = set(selected_names)
    lines: list[str] = []
    path = Path(source)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            name = unquote(line.rsplit("#", 1)[1]) if "#" in line else ""
            if name in wanted:
                lines.append(line)
    encoded = base64.b64encode(("\n".join(lines) + ("\n" if lines else "")).encode()).decode()
    Path(output).write_text(encoded, encoding="utf-8")
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()

    meta = yaml.safe_load(Path("list.meta.yml").read_text(encoding="utf-8"))
    clash = yaml.safe_load(Path("list.yml").read_text(encoding="utf-8"))
    config = yaml.safe_load(Path("fetch_config.yml").read_text(encoding="utf-8"))
    category_groups = list(config.get("categories_disp", {}).values())

    unique_nodes: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for node in list(meta.get("proxies", [])) + list(clash.get("proxies", [])):
        unique_nodes.setdefault(endpoint_key(node), node)

    print(f"正在测试 {len(unique_nodes)} 个唯一节点的可达性与延迟...")
    endpoint_results: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(test_endpoint, node, args.timeout): key
            for key, node in unique_nodes.items()
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            key = future_map[future]
            try:
                endpoint_results[key] = future.result()
            except Exception as exc:
                endpoint_results[key] = {
                    "reachable": False,
                    "latency_ms": None,
                    "availability": 0,
                    "status": f"测试异常:{exc.__class__.__name__}",
                }
            if index % 50 == 0 or index == len(future_map):
                print(f"  已完成 {index}/{len(future_map)}")

    meta_selected, meta_rows = process_profile(
        "list.meta.yml",
        "list.best.meta.yml",
        "snippets/nodes.best.meta.yml",
        category_groups,
        endpoint_results,
        args.limit,
    )
    _, clash_rows = process_profile(
        "list.yml",
        "list.best.yml",
        "snippets/nodes.best.yml",
        category_groups,
        endpoint_results,
        args.limit,
    )
    raw_count = write_best_base64(meta_selected)

    rows = meta_rows + clash_rows
    with Path("list_best_report.csv").open("w", encoding="utf-8", newline="") as file:
        fields = [
            "profile", "category", "rank", "name", "type", "server", "port",
            "availability", "purity", "overall", "latency_ms", "status", "purity_notes",
        ]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    meta_counts: dict[str, int] = {}
    for row in meta_rows:
        meta_counts[row["category"]] = meta_counts.get(row["category"], 0) + 1
    print("精选完成：")
    for category in category_groups:
        print(f"  {category}: Meta {meta_counts.get(category, 0)} 个")
    print(f"  Meta 精选节点: {len(meta_selected)}")
    print(f"  Base64 精选节点: {raw_count}")
    print("输出: list.best.meta.yml, list.best.yml, list.best.txt, list_best_report.csv")


if __name__ == "__main__":
    main()
