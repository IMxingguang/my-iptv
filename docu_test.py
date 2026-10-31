# -*- coding: utf-8 -*-
"""
纪录片频道列表测速分拣 v2:
  解析 HLS 主清单取最高分辨率 -> 下载真实视频分片测速 -> 按清晰度+速度排序
用法: python docu_test.py [输入m3u] [输出m3u] [并发数]
"""
import sys, re, time, json, os
from concurrent.futures import ThreadPoolExecutor
import urllib.request

IN  = sys.argv[1] if len(sys.argv) > 1 else "docu_raw.m3u"
OUT = sys.argv[2] if len(sys.argv) > 2 else "纪录片测速结果.m3u"
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 10
UA = {"User-Agent": "Mozilla/5.0 (SmartTV)"}
SPEED_BYTES = 2 * 1024 * 1024
SPEED_TIME = 14
RETRIES = 2

def http(url, timeout=14):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)

def abs_url(base, path):
    if path.startswith("http"):
        return path
    from urllib.parse import urljoin
    return urljoin(base, path)

def get_variant(url):
    """返回 (best_variant_url, p值, bandwidth)，失败抛异常"""
    txt = http(url, timeout=12).read(65536).decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" not in txt:
        return url, 0, 0
    best = (None, 0, 0)
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            m_w = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
            m_b = re.search(r"BANDWIDTH=(\d+)", line)
            p = int(m_w.group(2)) if m_w else 0
            bw = int(m_b.group(1)) if m_b else 0
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt and not nxt.startswith("#") and p >= best[1]:
                best = (abs_url(url, nxt), p, bw)
    if best[0]:
        return best[0], best[1], best[2]
    raise RuntimeError("master清单无可用variant")

def get_segment(media_url):
    txt = http(media_url, timeout=12).read(65536).decode("utf-8", "replace")
    for line in txt.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return abs_url(media_url, line)
    raise RuntimeError("媒体清单无分片")

def speed_test(seg_url):
    r = http(seg_url, timeout=SPEED_TIME)
    t0 = time.time()
    total = 0
    while total < SPEED_BYTES:
        chunk = r.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if time.time() - t0 > SPEED_TIME:
            break
    dt = time.time() - t0
    if total == 0:
        raise RuntimeError("分片0字节")
    return total / max(dt, 0.2)

def label_res(name):
    m = re.search(r"\((\d{3,4})[pi]\)", name)
    return int(m.group(1)) if m else 0

def test_one(entry):
    name, attrs, url = entry
    last_err = ""
    for att in range(RETRIES):
        try:
            variant, p, bw = get_variant(url)
            if not p:
                p = label_res(name)
            seg = get_segment(variant)
            spd = speed_test(seg)
            return {"name": name, "attrs": attrs, "url": url, "res": p,
                    "bw": bw, "speed": spd}
        except Exception as e:
            last_err = repr(e)[:80]
            time.sleep(1)
    return {"name": name, "attrs": attrs, "url": url, "res": label_res(name),
            "bw": 0, "speed": 0, "err": last_err}

def parse_m3u(path):
    entries = []
    attrs = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("#EXTINF"):
            attrs = line
        elif line and not line.startswith("#") and attrs:
            name = attrs.rsplit(",", 1)[1].strip()
            entries.append((name, attrs, line))
            attrs = None
    return entries

def main():
    entries = parse_m3u(IN)
    print(f"待测频道: {len(entries)}, 并发 {WORKERS}")
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, r in enumerate(ex.map(test_one, entries)):
            results.append(r)
            if (i + 1) % 50 == 0:
                print(f"  进度 {i+1}/{len(entries)}  耗时 {time.time()-t0:.0f}s")
    alive = [r for r in results if r["speed"] > 20_000]
    dead = [r for r in results if r["speed"] <= 20_000]
    alive.sort(key=lambda r: (-r["res"], -r["speed"]))
    lines = ["#EXTM3U"]
    for r in alive:
        res_tag = f"{r['res']}p" if r["res"] else "?"
        spd_tag = (f"{r['speed']/1_048_576:.1f}MB/s" if r["speed"] >= 1_048_576
                   else f"{r['speed']/1024:.0f}KB/s")
        nm = re.sub(r"\s*\(\d{3,4}[pi]\)", "", r["name"])
        new_attr = r["attrs"].split(",", 1)[0]
        lines.append(f"{new_attr}, {nm} [{res_tag}|{spd_tag}]")
        lines.append(r["url"])
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    json.dump(results, open(OUT + ".json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"完成: 存活 {len(alive)} / 失效 {len(dead)}, 结果 -> {OUT}")
    print("Top12:")
    for r in alive[:12]:
        print(f"  {r['res'] or '?'}p  {r['speed']/1_048_576:.2f}MB/s  {r['name']}")

if __name__ == "__main__":
    main()
