"""
소프트콘 (softcon.ajou.ac.kr) 작품 크롤러
- 텍스트/상세정보 → output/data/project_details.json, project_links.json
- 대표 이미지      → output/images/
"""

import os
import csv
import json
import time
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# 설정
BASE_URL     = "https://softcon.ajou.ac.kr"
DELAY        = 1.0   # 요청 간 대기 시간 (초)
MAX_PROJECTS = 50    # 한 번에 크롤링할 최대 프로젝트 수
# ─────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR  = os.path.join(BASE_DIR, "output", "images")
DATA_DIR   = os.path.join(BASE_DIR, "output", "data")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

CATEGORY_MAP = {
    "S": "소프트웨어",
    "D": "디지털미디어",
    "C": "사이버보안",
    "I": "인공지능융합",
}


# 1. 목록 페이지에서 프로젝트 링크 수집

def get_project_links(list_type: str = "current", category: str = "S", term: str = None) -> list[dict]:
    # 목록 페이지에서 프로젝트 링크를 추출
    if list_type == "current":
        url = f"{BASE_URL}/works/works_list.asp?category={category}"
    else:
        if not term:
            raise ValueError("이전 작품 목록을 가져오려면 학기(term)가 필요합니다.")
        url = f"{BASE_URL}/works/works_list_prev.asp?category={category}&wTerm={term}"

    print(f"[목록] {url}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] 목록 페이지 요청 실패: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    projects = []
    seen_urls = set()

    for link in soup.select("a"):
        href = link.get("href", "")
        if ("works.asp?uid=" not in href and "works_prev.asp?uid=" not in href) or "javascript:" in href:
            continue

        # 절대 URL 변환
        if href.startswith("./") or href.startswith("/"):
            full_url = BASE_URL + href.replace("./", "/")
        elif not href.startswith("http"):
            full_url = BASE_URL + "/" + href
        else:
            full_url = href

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        uid        = full_url.split("?uid=")[1].split("&")[0] if "?uid=" in full_url else None
        term_value = full_url.split("wTerm=")[1].split("&")[0] if "wTerm=" in full_url else None

        projects.append({
            "title": link.text.strip() or "제목 없음",
            "url":   full_url,
            "uid":   uid,
            "term":  term_value,
        })

    print(f"  → {len(projects)}개 프로젝트 링크 발견")
    return projects


# 2. 프로젝트 상세 페이지 파싱

def get_project_details(project_url: str) -> dict:
    # 프로젝트 상세 페이지에서 정보를 추출
    try:
        response = requests.get(project_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        details = {"url": project_url, "uid": None, "term": None}

        # UID / 학기
        if "?uid=" in project_url:
            details["uid"] = project_url.split("?uid=")[1].split("&")[0]
        if "wTerm=" in project_url:
            details["term"] = project_url.split("wTerm=")[1].split("&")[0]

        # 제목
        title_elem = soup.select_one(".dw_title div p")
        if title_elem:
            details["title"] = title_elem.text.strip()

        # 작품 개요
        summary_elems = soup.select(".work_detail div")
        if len(summary_elems) >= 2:
            details["summary"] = summary_elems[1].text.strip()

        # 팀 정보
        team_info = {}

        registrant_section = soup.select_one(".dw_resistrant .dw_wrap:nth-of-type(1)")
        if registrant_section:
            registrant = {}
            for key, selector in [("department", ".dw3 p"), ("grade", ".dw4 p"), ("email", ".dw5 p")]:
                elem = registrant_section.select_one(selector)
                if elem:
                    registrant[key] = elem.text.strip()
            team_info["registrant"] = registrant

        members_section = soup.select_one(".dw_resistrant .dw_wrap:nth-of-type(2)")
        if members_section:
            members = []
            for row in members_section.select("ul"):
                member = {}
                for key, selector in [("role", ".dw1 span"), ("name", ".dw2"),
                                       ("department", ".dw3"), ("grade", ".dw4"), ("email", ".dw5")]:
                    elem = row.select_one(selector)
                    if elem:
                        member[key] = elem.text.strip()
                if member:
                    members.append(member)
            team_info["members"] = members

        mentor_section = soup.select_one(".dw_resistrant .dw_wrap:nth-of-type(3)")
        if mentor_section:
            mentor = {}
            for key, selector in [("name", ".dw2"), ("affiliation", ".dw3")]:
                elem = mentor_section.select_one(selector)
                if elem:
                    mentor[key] = elem.text.strip()
            if mentor:
                team_info["mentor"] = mentor

        details["teamInfo"] = team_info

        # Git 저장소
        git_section = soup.select_one(".dw_resistrant .dw_wrap:nth-of-type(4)")
        if git_section:
            git_link = git_section.select_one(".dw5 a")
            if git_link:
                details["gitRepository"] = git_link.get("href", "").strip()

        # 간략 설명
        desc_section = soup.select_one(".dw_resistrant .dw_wrap:nth-of-type(5)")
        if desc_section:
            desc_elem = desc_section.select_one(".dw5")
            if desc_elem:
                details["description"] = desc_elem.text.strip()

        # 발표 자료 URL
        pdf_iframe = soup.select_one("#pdfArea")
        if pdf_iframe:
            details["presentationUrl"] = BASE_URL + pdf_iframe.get("src", "").strip()

        # 발표 동영상 URL
        video_iframe = soup.select_one(".dw_video iframe")
        if video_iframe:
            details["videoUrl"] = video_iframe.get("src", "").strip()

        # 대표 이미지 URL
        rep_image = soup.select_one(".dw_title div img")
        if rep_image and rep_image.has_attr("src"):
            img_src = rep_image["src"]
            if img_src.startswith("./") or img_src.startswith("/"):
                img_src = BASE_URL + img_src.replace("./", "/")
            details["representativeImage"] = img_src

        return details

    except Exception as e:
        print(f"  [ERROR] {project_url} → {e}")
        return {"url": project_url, "error": str(e)}


# 3. 대표 이미지 다운로드

def download_image(img_url: str, uid: str, save_dir: str) -> str | None:
    # 대표 이미지를 다운로드하고 저장 경로를 반환
    os.makedirs(save_dir, exist_ok=True)
    ext      = os.path.splitext(img_url.split("?")[0])[-1] or ".jpg"
    filename = f"{uid}{ext}"
    filepath = os.path.join(save_dir, filename)

    try:
        resp = requests.get(img_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath
    except requests.RequestException as e:
        print(f"  [IMG ERROR] {img_url} → {e}")
        return None


# 4. CSV 저장 (텍스트 요약)

def save_csv(details_list: list[dict], path: str) -> None:
    # 주요 텍스트 필드를 CSV로 저장
    rows = []
    for d in details_list:
        registrant = d.get("teamInfo", {}).get("registrant", {})
        rows.append({
            "uid":                 d.get("uid", ""),
            "term":                d.get("term", ""),
            "title":               d.get("title", ""),
            "summary":             d.get("summary", ""),
            "description":         d.get("description", ""),
            "gitRepository":       d.get("gitRepository", ""),
            "presentationUrl":     d.get("presentationUrl", ""),
            "videoUrl":            d.get("videoUrl", ""),
            "representativeImage": d.get("representativeImage", ""),
            "registrant_dept":     registrant.get("department", ""),
            "registrant_grade":    registrant.get("grade", ""),
            "registrant_email":    registrant.get("email", ""),
            "url":                 d.get("url", ""),
        })

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] CSV 저장 → {path}")


# 메인

def main():
    print("=" * 50)
    print("  소프트콘 작품 크롤러")
    print("=" * 50)

    # 모드 선택
    print("\n1. 현재 작품 목록\n2. 이전 작품 목록 (학기별)")
    mode     = input("선택 (1 또는 2, 기본값 1): ").strip() or "1"
    category = input(f"카테고리 {list(CATEGORY_MAP.keys())} (기본값 S): ").strip().upper() or "S"
    max_n    = int(input(f"최대 프로젝트 수 (기본값 {MAX_PROJECTS}): ").strip() or MAX_PROJECTS)

    term = None
    if mode == "2":
        term = input("학기 입력 (예: 2024-1, 기본값 2024-1): ").strip() or "2024-1"

    list_type = "current" if mode == "1" else "previous"

    # 1. 링크 수집
    projects = get_project_links(list_type, category, term)
    if not projects:
        print("프로젝트 링크를 찾을 수 없습니다.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    links_path = os.path.join(DATA_DIR, "project_links.json")
    with open(links_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
    print(f"[OK] 링크 저장 → {links_path}")

    # 2. 상세 정보 수집
    targets      = projects[:min(len(projects), max_n)]
    details_list = []
    img_count    = 0

    for i, proj in enumerate(targets, start=1):
        print(f"\n[{i}/{len(targets)}] {proj['title']}")
        details = get_project_details(proj["url"])
        details_list.append(details)

        # 이미지 다운로드
        img_url = details.get("representativeImage")
        if img_url and details.get("uid"):
            saved = download_image(img_url, details["uid"], IMAGE_DIR)
            if saved:
                details["localImage"] = saved
                img_count += 1
                print(f"  이미지 저장: {os.path.basename(saved)}")

        if i < len(targets):
            time.sleep(DELAY)

    # 3. JSON 저장
    details_path = os.path.join(DATA_DIR, "project_details.json")
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details_list, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON 저장 → {details_path}")

    # 4. CSV 저장
    csv_path = os.path.join(DATA_DIR, "result.csv")
    save_csv(details_list, csv_path)

    # 결과 요약
    print("\n" + "=" * 50)
    print(f"  크롤링 완료!")
    print(f"  프로젝트: {len(details_list)}개")
    print(f"  이미지:   {img_count}개")
    print(f"  저장 위치: output/data/, output/images/")
    print("=" * 50)


if __name__ == "__main__":
    main()
