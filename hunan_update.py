# -*- coding: utf-8 -*-
"""
湖南移动 OTT 直播源更新脚本 (供 GitHub Actions 或本地运行)
1. 拉取官方频道列表接口 (getChannels.shtml?templateId=0741)
2. 逐频道轻量验证 (可选, --no-test 跳过)
3. 生成 m3u: output/hunan.m3u
用法: python hunan_update.py [--no-test]
"""
import json, sys, time, urllib.request, os

LIST_API = "http://looktvepg.yna.bcs.ottcn.com:8080/ysten-lvoms-epg/epg/getChannels.shtml?templateId=0741"
OUT = os.environ.get("OUT_FILE", "output/hunan.m3u")
TEST_EACH = "--no-test" not in sys.argv
TIMEOUT = int(os.environ.get("TEST_TIMEOUT", "6"))

def group(name: str) -> str:
    if "CCTV" in name or "CGTN" in name:
        return "央视"
    if "卫视" in name:
        return "卫视"
    return "湖南本地/其他"

def fetch_list():
    req = urllib.request.Request(LIST_API, headers={"User-Agent": "curl/8"})
    return json.load(urllib.request.urlopen(req, timeout=20))

def quick_test(url: str) -> bool:
    """只取响应头部 512 字节, 确认返回直播 m3u8 而非错误页"""
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=TIMEOUT)
        head = r.read(512).decode("utf-8", "replace")
        return "#EXTM3U" in head
    except Exception:
        return False

def main():
    data = fetch_list()
    usable = [c for c in data if c.get("usable") == 1]
    print(f"拉取频道 {len(data)} 个, usable {len(usable)} 个")
    ok, fail, untested = 0, 0, 0
    lines = ["#EXTM3U"]
    for c in sorted(usable, key=lambda x: x.get("no", 999)):
        name = c["channelName"].strip()
        url = c["livePlayUrl"].strip()
        if TEST_EACH:
            if quick_test(url):
                ok += 1
            else:
                fail += 1
                print(f"[失效] {name} {url}")
                continue
            time.sleep(0.3)  # 温和速率, 避免触发风控
        else:
            untested += 1
        g = group(name)
        lines.append(f'#EXTINF:-1 tvg-id="{c["uuid"]}" tvg-name="{name}" '
                     f'tvg-logo="{c.get("logo","")}" group-title="{g}",{name}')
        lines.append(url)
    out_dir = os.path.dirname(OUT)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"完成: 通过 {ok} / 失效剔除 {fail} / 未测试 {untested} -> {OUT}")

if __name__ == "__main__":
    main()
