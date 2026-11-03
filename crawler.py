"""
소프트콘 (softcon.ajou.ac.kr) 작품 크롤러
- 텍스트/상세정보 → output/data/project_details.json, project_links.json
- 대표 이미지      → output/images/
"""

import os
import copy
import csv
import hashlib
import json
import re
import sys
import time
from datetime import date
from urllib.parse import urljoin

# ─────────────────────────────────────────────
# 설정
BASE_URL     = "https://softcon.ajou.ac.kr"
DELAY        = 1.0   # 요청 간 대기 시간 (초)
MAX_PROJECTS = None  # 한 번에 크롤링할 최대 프로젝트 수 (None이면 무제한)

# 수집 소스 선택: "softcon"(기본) 또는 "paran"(대학혁신단 파란학기제).
# 둘 다 동일한 백엔드 API 싱크(post_to_api)로 보낸다.
CRAWL_SOURCE = os.environ.get("CRAWL_SOURCE", "softcon").strip().lower()

# 파란학기제: 학기별 페이지에 프로젝트가 표로 인라인(상세 페이지 없음, JS 아님).
PARAN_BASE     = "https://www.ajou.ac.kr"
PARAN_LIST_URL = PARAN_BASE + "/ace/paran/{term}.do"
PARAN_SEED     = "2025-1"       # 학기 목록 자동 추출용 시드(모든 학기 링크가 nav에 있음)
PARAN_CATEGORY = "파란학기제"   # 소프트콘 단일문자 코드와 구분되는 소스 라벨
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
    "S": "SW캡스톤디자인",
    "I": "AI융합 캡스톤디자인",
    "D": "사이버보안캡스톤디자인",
    "M": "자기주도연구",
    "P": "자기주도 프로젝트",
    "R": "미디어 프로젝트",
    "W": "SW기초교육",
    "E": "기타활동",
    "A": "AI집중교육",
    "T": "SWeat 온라인 튜터링",
    "C": "국방ICT프로젝트",
}

FALSE_VALUES = {"0", "false", "no", "off"}
DB_ENV_KEYS = (
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "DB_UNIX_SOCKET",
    "DB_SOCKET",
    "CLOUD_SQL_CONNECTION_NAME",
    "CRAWLER_USER_ID",
    "DB_AUTO_CREATE_CRAWLER_USER",
    "CRAWLER_USER_EMAIL",
    "CRAWLER_USER_FIREBASE_UID",
    "CRAWLER_USER_NAME",
)
MAX_VARCHAR_LENGTH = 255


# 1. 목록 페이지에서 프로젝트 링크 수집

def get_all_project_links() -> list[dict]:
    # 모든 학기 및 카테고리의 프로젝트 링크를 추출 (AJAX 페이징 활용)
    import requests
    from bs4 import BeautifulSoup

    projects = []
    seen_uids = set()

    print("[목록] 학기(terms) 추출 중...")
    try:
        url_terms = f"{BASE_URL}/works/works_list_prev.asp?category=S&wTerm=2024-2"
        res_terms = requests.get(url_terms, headers=HEADERS, timeout=10)
        res_terms.raise_for_status()
        terms = sorted(set(re.findall(r"wTerm=(\d{4}-\d)", res_terms.text)))
    except Exception as e:
        print(f"[ERROR] 학기 추출 실패: {e}")
        terms = []
    
    if not terms:
        # 폴백: 정기 실행 중 추출이 실패해도 크롤링을 통째로 중단하지 않는다.
        # 고정 목록 대신 현재 연도까지 동적으로 생성해 이후 학기 누락을 막는다.
        cur_year = date.today().year
        terms = [f"{y}-{s}" for y in range(2020, cur_year + 1) for s in (1, 2)]
        print(f"[경고] 학기 목록 추출 실패로 폴백합니다. 범위: {terms[0]} ~ {terms[-1]}")

    print(f"  → 학기 목록: {terms}")

    # 사이트의 모든 카테고리를 순회한다(데이터 없는 조합은 skip). 일부만 하드코딩하면 M/P/R/E/T 등이 누락된다.
    categories = list(CATEGORY_MAP.keys())
    
    ajax_url = f"{BASE_URL}/common/ajax_file/work_list_ajax.asp"
    ajax_headers = dict(HEADERS)
    ajax_headers["X-Requested-With"] = "XMLHttpRequest"

    for term_val in terms:
        for cat in categories:
            page = 1
            while True:
                data = {"page": page, "category": cat, "wTerm": term_val}
                res = None
                for attempt in range(3):
                    try:
                        res = requests.post(ajax_url, headers=ajax_headers, data=data, timeout=10)
                        res.raise_for_status()
                        break
                    except requests.RequestException as e:
                        if attempt == 2:
                            # 재시도 후에도 실패하면 조용히 성공 처리하지 않고 경고로 드러낸다(부분 수집).
                            print(f"[경고] AJAX 3회 실패, 부분 수집 ({term_val}, {cat}, page={page}): {e}")
                        else:
                            time.sleep(DELAY)
                if res is None:
                    break

                text = res.text.strip()
                if text == "F" or not text:
                    break
                
                soup = BeautifulSoup(text, "html.parser")
                links = soup.select("a")
                
                page_new = 0
                for link in links:
                    href = link.get("href", "")
                    if "uid=" not in href or "javascript:" in href:
                        continue
                    

                    full_url = urljoin(BASE_URL, href)
                    uid = full_url.split("uid=")[1].split("&")[0] if "uid=" in full_url else None
                    if not uid or uid in seen_uids:
                        continue
                        
                    seen_uids.add(uid)
                    page_new += 1
                    projects.append({
                        "title": link.text.strip() or "제목 없음",
                        "url": full_url,
                        "uid": uid,
                        "term": term_val,
                        "category": cat,
                    })
                
                # 새 uid가 없으면(빈 페이지 또는 전부 중복) 종료해 무한 루프를 막는다.
                if page_new == 0:
                    break
                
                page += 1
                time.sleep(DELAY)
            # F/빈 응답/새 uid 0건으로 끝난 조합 뒤에도 쉬어 연속 요청을 막는다.
            time.sleep(DELAY)

    print(f"  → 총 {len(projects)}개 프로젝트 링크 발견")
    return projects


# 2. 프로젝트 상세 페이지 파싱

def get_project_details(project_url: str) -> dict:
    # 프로젝트 상세 페이지에서 정보를 추출
    import requests
    from bs4 import BeautifulSoup

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
        rep_image = soup.select_one(".countsort img")
        if rep_image and rep_image.has_attr("src"):
            img_src = rep_image["src"]
            if "no_registrant" not in img_src and "movie_noimg" not in img_src:
                # 기존처럼 사이트 루트 기준으로 풀되, ./ 나 / 로 시작하지 않는 상대경로도 절대 URL로 만든다.
                details["representativeImage"] = urljoin(BASE_URL + "/", img_src)

        return details

    except Exception as e:
        print(f"  [ERROR] {project_url} → {e}")
        return {"url": project_url, "error": str(e)}


# 2-b. 파란학기제(대학혁신단) 수집
#   - 학기 페이지(/ace/paran/{term}.do)에 프로젝트가 표로 전부 인라인된다.
#   - 상세 페이지/이미지/깃·영상 링크가 없으므로 목록 파싱이 곧 상세 수집이다.
#   - 소프트콘과 동일한 details 스키마(uid/term/title/category/content...)로 맞춰
#     기존 post_to_api / save_to_db / save_csv 를 그대로 재사용한다.

def paran_source_uid(no: str, team: str) -> str:
    # 파란엔 고정 id가 없다. 팀명을 소스 키로 쓰되 소프트콘 숫자 uid와 겹치지 않게
    # "paran-"로 네임스페이싱한다(백엔드 dedup 키는 (source_uid, term)).
    # ponytail: 한 학기 내 팀명이 유일하다고 가정. 중복 시 뒷 행이 덮어씀 — 실제로 거의 없음.
    key = " ".join((team or "").split()) or f"no{no}"
    uid = f"paran-{key}"
    if len(uid) > 100:  # source_uid 컬럼 길이(100) 초과 방지
        uid = "paran-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return uid


def get_paran_terms() -> list[str]:
    # 학기 목록. 보정 노브: CRAWL_TERMS 로 수동 지정 가능(예: "2024-1,2024-2").
    import requests

    env = os.environ.get("CRAWL_TERMS")
    if env:
        return [t.strip() for t in env.split(",") if t.strip()]

    terms = []
    try:
        res = requests.get(PARAN_LIST_URL.format(term=PARAN_SEED), headers=HEADERS, timeout=10)
        res.raise_for_status()
        terms = sorted(set(re.findall(r"/ace/paran/(\d{4}-\d)\.do", res.text)))
    except Exception as e:
        print(f"[ERROR] 파란 학기 추출 실패: {e}")

    if not terms:
        # 소프트콘과 동일 철학: 추출 실패해도 중단하지 않고 범위를 동적 생성한다.
        cur_year = date.today().year
        terms = [f"{y}-{s}" for y in range(2016, cur_year + 1) for s in (1, 2)]
        print(f"[경고] 파란 학기 목록 추출 실패로 폴백합니다. 범위: {terms[0]} ~ {terms[-1]}")
    return terms


def parse_paran_term(term: str) -> list[dict]:
    # 한 학기 페이지를 받아 표를 details 목록으로 변환.
    import requests

    url = PARAN_LIST_URL.format(term=term)
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"  [경고] {term} 요청 실패: {e}")
        return []
    return parse_paran_rows(term, url, res.text)


def parse_paran_rows(term: str, url: str, html: str) -> list[dict]:
    # 네트워크와 분리된 순수 파서(테스트 가능). 표 행 → details 목록.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()

    table = soup.select_one(".content table") or soup.find("table")
    rows = []
    if table:
        rows = table.select("tbody tr") or [r for r in table.select("tr") if r.find("td")]

    if not rows:
        # 방화벽/구조 변경 등으로 표가 없으면 0건 조용히 성공시키지 않고 경고로 드러낸다.
        print(f"  [경고] {term}: 프로젝트 표를 찾지 못했습니다(구조 변경/차단 가능).")
        return []

    projects = []
    for r in rows:
        cells = [c.get_text(" ", strip=True) for c in r.find_all("td")]
        if len(cells) < 3:
            continue
        no, team, title = cells[0], cells[1], cells[2].strip()
        headcount = cells[3] if len(cells) > 3 else ""
        if not title:  # 제목 없는 행은 건너뛴다("제목 없음" 쓰레기 방지)
            continue

        content_lines = []
        if team:
            content_lines.append(f"팀명: {team}")
        if headcount:
            content_lines.append(f"인원수: {headcount}")
        content_lines.append(f"원본 URL: {url}")
        content_lines.append(f"학기: {term}")

        projects.append({
            "uid": paran_source_uid(no, team),
            "term": term,
            "title": title,
            "summary": "",
            "description": "",
            "content": "\n".join(content_lines),
            "url": url,
            "category": PARAN_CATEGORY,
            "teamInfo": {},   # 파란엔 개별 멤버 정보가 없음 → members 빈 배열
        })
    return projects


def collect_paran() -> list[dict]:
    terms = get_paran_terms()
    print(f"  → 파란 학기 목록: {terms}")
    details_list = []
    for i, term in enumerate(terms):
        items = parse_paran_term(term)
        print(f"[{term}] {len(items)}개")
        details_list.extend(items)
        if i < len(terms) - 1:
            time.sleep(DELAY)
    print(f"  → 총 {len(details_list)}개 파란학기제 프로젝트 수집")
    return details_list


# 3. 대표 이미지 다운로드

def download_image(img_url: str, uid: str, save_dir: str) -> str | None:
    # 대표 이미지를 다운로드하고 저장 경로를 반환
    import requests

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


# 4. MySQL 저장

def is_enabled_env(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in FALSE_VALUES


def quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", identifier):
        raise RuntimeError(f"허용되지 않는 DB 식별자입니다: {identifier}")
    return f"`{identifier}`"


def get_optional_db_config() -> dict | None:
    """환경변수에서 DB 설정을 읽습니다. 설정이 전혀 없으면 DB 저장을 건너뜁니다."""
    if not is_enabled_env("DB_SAVE_ENABLED", True):
        return None

    if not any(os.environ.get(key) for key in DB_ENV_KEYS):
        return None

    unix_socket = os.environ.get("DB_UNIX_SOCKET") or os.environ.get("DB_SOCKET")
    cloud_sql_connection_name = os.environ.get("CLOUD_SQL_CONNECTION_NAME")
    if not unix_socket and cloud_sql_connection_name:
        unix_socket = f"/cloudsql/{cloud_sql_connection_name}"

    missing = []
    if not unix_socket and not os.environ.get("DB_HOST"):
        missing.append("DB_HOST 또는 DB_UNIX_SOCKET/CLOUD_SQL_CONNECTION_NAME")
    auto_create_crawler_user = is_enabled_env("DB_AUTO_CREATE_CRAWLER_USER", False)
    for key in ("DB_USER", "DB_PASSWORD", "DB_NAME"):
        if not os.environ.get(key):
            missing.append(key)
    if not os.environ.get("CRAWLER_USER_ID") and not auto_create_crawler_user:
        missing.append("CRAWLER_USER_ID 또는 DB_AUTO_CREATE_CRAWLER_USER=true")
    if missing:
        raise RuntimeError("DB 설정 누락: " + ", ".join(missing))

    try:
        port = int(os.environ.get("DB_PORT", 3306))
        crawler_user_id = int(os.environ["CRAWLER_USER_ID"]) if os.environ.get("CRAWLER_USER_ID") else None
    except ValueError as exc:
        raise RuntimeError("DB_PORT와 CRAWLER_USER_ID는 정수여야 합니다.") from exc
    if crawler_user_id is not None and crawler_user_id <= 0:
        raise RuntimeError("CRAWLER_USER_ID는 양수여야 합니다.")

    post_table = os.environ.get("DB_POST_TABLE", "posts").strip()
    user_table = os.environ.get("DB_USER_TABLE", "users").strip()
    quote_identifier(post_table)
    quote_identifier(user_table)

    return {
        "host": os.environ.get("DB_HOST"),
        "port": port,
        "unix_socket": unix_socket,
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
        "crawler_user_id": crawler_user_id,
        "post_table": post_table,
        "user_table": user_table,
        "auto_create_crawler_user": auto_create_crawler_user,
        "crawler_user_email": os.environ.get("CRAWLER_USER_EMAIL", "softcon-crawler@aim.local"),
        "crawler_user_firebase_uid": os.environ.get("CRAWLER_USER_FIREBASE_UID", "softcon-crawler"),
        "crawler_user_name": os.environ.get("CRAWLER_USER_NAME", "Softcon Crawler"),
    }


def get_db_connection(config: dict):
    """환경변수에서 DB 접속 정보를 읽어 연결을 반환합니다."""
    import pymysql

    connect_args = {
        "user": config["user"],
        "password": config["password"],
        "database": config["database"],
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }
    if config.get("unix_socket"):
        connect_args["unix_socket"] = config["unix_socket"]
    else:
        connect_args["host"] = config["host"]
        connect_args["port"] = config["port"]
    return pymysql.connect(**connect_args)


def trim_text(value: str | None, limit: int = MAX_VARCHAR_LENGTH) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_source_key(details: dict) -> str:
    term = (details.get("term") or "current").strip()
    source = str(details.get("uid") or details.get("url") or details.get("title") or "").strip()
    source = " ".join(source.split())
    if len(source) > 120:
        source = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return trim_text(f"softcon:{term}:{source}")


def build_post_content(details: dict) -> str:
    lines = []
    for label, key in [
        ("작품 개요", "summary"),
        ("발표 자료", "presentationUrl"),
        ("원본 URL", "url"),
        ("학기", "term"),
        ("소프트콘 UID", "uid"),
    ]:
        value = details.get(key)
        if value:
            lines.append(f"{label}: {value}")

    team_info = details.get("teamInfo")
    if team_info:
        lines.append("팀 정보:")
        lines.append(json.dumps(team_info, ensure_ascii=False, indent=2))

    return "\n\n".join(lines)


def build_post_row(details: dict, crawler_user_id: int) -> dict:
    title = trim_text(details.get("title") or "제목 없음")
    description = trim_text(details.get("description") or details.get("summary") or title)
    return {
        "user_id": crawler_user_id,
        "board_type": "CRAWLED_PROJECT",
        "title": title,
        "description": description,
        "content": build_post_content(details),
        "thumbnail_image": details.get("representativeImage") or None,
        "thumbnail_storage_key": build_source_key(details),
        "video_link": details.get("videoUrl") or None,
        "github_link": details.get("gitRepository") or None,
        "visibility": "PUBLIC",
    }


def build_db_statements(post_table: str) -> tuple[str, str, str]:
    table = quote_identifier(post_table)
    select_sql = f"""
        SELECT post_id
          FROM {table}
         WHERE board_type = %s
           AND thumbnail_storage_key = %s
         LIMIT 1
    """
    insert_sql = f"""
        INSERT INTO {table} (
            user_id, board_type, title, description, content,
            thumbnail_image, thumbnail_storage_key, video_link, github_link,
            visibility, view_count, like_count, comment_count,
            created_at, updated_at
        ) VALUES (
            %(user_id)s, %(board_type)s, %(title)s, %(description)s, %(content)s,
            %(thumbnail_image)s, %(thumbnail_storage_key)s, %(video_link)s, %(github_link)s,
            %(visibility)s, 0, 0, 0, NOW(), NOW()
        )
    """
    update_sql = f"""
        UPDATE {table}
           SET title = %(title)s,
               description = %(description)s,
               content = %(content)s,
               thumbnail_image = %(thumbnail_image)s,
               video_link = %(video_link)s,
               github_link = %(github_link)s,
               visibility = %(visibility)s,
               updated_at = NOW()
         WHERE post_id = %(post_id)s
    """
    return select_sql, insert_sql, update_sql


def resolve_crawler_user_id(cursor, config: dict) -> int:
    if config.get("crawler_user_id"):
        return config["crawler_user_id"]

    user_table = quote_identifier(config["user_table"])
    cursor.execute(
        f"""
        SELECT user_id
          FROM {user_table}
         WHERE firebase_uid = %s
            OR email = %s
         LIMIT 1
        """,
        (config["crawler_user_firebase_uid"], config["crawler_user_email"]),
    )
    existing = cursor.fetchone()
    if existing:
        return int(existing["user_id"])

    if not config.get("auto_create_crawler_user"):
        raise RuntimeError("CRAWLER_USER_ID가 없고 DB_AUTO_CREATE_CRAWLER_USER가 꺼져 있습니다.")

    # admin_role은 백엔드 AdminRole enum(NONE/ADMIN/SUPER_ADMIN) 문자열 값으로 저장한다.
    # (백엔드 User.userRole/userStatus와 동일하게 @Enumerated(STRING) 매핑을 전제.
    #  크롤러 유저는 콘텐츠 작성용 시스템 계정이라 관리자 권한이 없는 NONE으로 둔다.)
    cursor.execute(
        f"""
        INSERT INTO {user_table} (
            admin_role, created_at, updated_at,
            department, email, firebase_uid, name,
            provider, user_role, user_status
        ) VALUES (
            %s, NOW(), NOW(),
            %s, %s, %s, %s,
            %s, %s, %s
        )
        """,
        (
            "NONE",
            "AIM",
            config["crawler_user_email"],
            config["crawler_user_firebase_uid"],
            config["crawler_user_name"],
            "SYSTEM",
            "PROFESSOR",
            "ACTIVE",
        ),
    )
    return int(cursor.lastrowid)


def save_to_db(details_list: list[dict]) -> None:
    """크롤링 결과를 AIM 백엔드 posts 테이블에 저장합니다."""
    if not details_list:
        return

    try:
        config = get_optional_db_config()
        if config is None:
            print("[DB] DB 환경변수가 없어 저장을 건너뜁니다.")
            return

        select_sql, insert_sql, update_sql = build_db_statements(config["post_table"])
        conn = get_db_connection(config)
        inserted = 0
        updated = 0

        with conn:
            with conn.cursor() as cursor:
                crawler_user_id = resolve_crawler_user_id(cursor, config)
                for d in details_list:
                    row = build_post_row(d, crawler_user_id)
                    cursor.execute(select_sql, ("CRAWLED_PROJECT", row["thumbnail_storage_key"]))
                    existing = cursor.fetchone()
                    if existing:
                        row["post_id"] = existing["post_id"]
                        cursor.execute(update_sql, row)
                        updated += 1
                    else:
                        cursor.execute(insert_sql, row)
                        inserted += 1
            conn.commit()
        print(f"[OK] DB 저장 완료 (insert {inserted}건, update {updated}건)")
    except Exception as e:
        print(f"[DB ERROR] {e}")
        raise


# 5. CSV 저장 (텍스트 요약)

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
    if not rows:
        print(f"[CSV] 저장할 행이 없어 건너뜁니다: {path}")
        return

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] CSV 저장 → {path}")



# 6. API 전송

def mask_email(raw: str | None) -> str | None:
    # 이메일 로컬 파트를 가린다. 콤마로 여러 주소가 올 수 있어 각각 처리하고,
    # 짧은 로컬(1자 이하)은 원문 문자를 남기지 않는다.
    raw = (raw or "").strip()
    if not raw:
        return None
    masked = []
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        if "@" not in part:
            masked.append("***")
            continue
        local, domain = part.split("@", 1)
        if len(local) > 3:
            prefix = local[:3]
        elif len(local) > 1:
            prefix = local[:1]
        else:
            prefix = ""
        masked.append(f"{prefix}**@{domain}")
    return ", ".join(masked) if masked else None


def post_to_api(details_list: list[dict]) -> int:
    import requests

    api_base = os.environ.get("BACKEND_API_BASE_URL")
    api_token = os.environ.get("CRAWLER_API_TOKEN")
    if not api_base or not api_token:
        return 0
    if not api_base.startswith("https://"):
        # 설정 오류는 조용히 넘기지 않고 명확히 실패시킨다(키 평문 전송 방지).
        raise ValueError(f"BACKEND_API_BASE_URL은 https여야 합니다: {api_base}")

    url = f"{api_base.rstrip('/')}/api/crawled-projects/crawler"
    # 백엔드와 합의한 크롤러 전용 헤더다. Authorization 을 쓰면 백엔드의
    # FirebaseAuthenticationFilter 가 Bearer 토큰을 Firebase ID 토큰으로 검증하려 들어
    # 반드시 실패한다. 전용 헤더라 그 필터가 반응하지 않는다.
    headers = {
        "X-Crawler-Key": api_token,
        "Content-Type": "application/json",
    }
    category = os.environ.get("CATEGORY", "S").upper()

    success, fail = 0, 0
    for d in details_list:
        members = []
        for m in d.get("teamInfo", {}).get("members", []):
            members.append({
                "role": m.get("role", ""),
                "name": m.get("name", ""),
                "maskedEmail": mask_email(m.get("email")),
                "department": m.get("department", ""),
                "grade": m.get("grade", "")
            })

        # content에는 teamInfo를 유지하되(등록자/멘토 정보 보존) 이메일만 마스킹해 원문 유출을 막는다.
        masked_team = copy.deepcopy(d.get("teamInfo") or {})
        reg = masked_team.get("registrant")
        if isinstance(reg, dict) and reg.get("email"):
            reg["email"] = mask_email(reg["email"])
        for mm in masked_team.get("members", []):
            if mm.get("email"):
                mm["email"] = mask_email(mm["email"])
        content_source = {**d, "teamInfo": masked_team}

        payload = {
            "uid": d.get("uid"),
            "term": d.get("term"),
            "title": d.get("title") or "제목 없음",
            "summary": d.get("summary", ""),
            "description": d.get("description", ""),
            "content": d.get("content") or build_post_content(content_source),
            "url": d.get("url"),
            "presentationUrl": d.get("presentationUrl"),
            "videoUrl": d.get("videoUrl"),
            "gitRepository": d.get("gitRepository"),
            "representativeImage": d.get("representativeImage"),
            "category": d.get("category") or category,
            "members": members
        }

        sent = False
        for attempt in range(3):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=10, allow_redirects=False)
                # 리다이렉트(로그인 페이지 등)를 성공으로 집계하지 않도록 2xx만 성공 처리.
                if not (200 <= resp.status_code < 300):
                    raise requests.HTTPError(f"unexpected status {resp.status_code}")
                sent = True
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [API ERROR] UID {d.get('uid')} 전송 실패: {e}")
                else:
                    time.sleep(DELAY)
        if sent:
            success += 1
            print(f"  [API OK] UID {d.get('uid')}")
        else:
            fail += 1

    if fail:
        print(f"[경고] API 전송 {fail}건 실패 (성공 {success}건)")
    else:
        print(f"[OK] API 전송 완료 (성공 {success}건)")
    return fail


# 메인

def collect_softcon(max_n) -> tuple[list[dict], int]:
    # 소프트콘: 목록(AJAX) 수집 → 상세 페이지 파싱 → 대표 이미지 다운로드.
    projects = get_all_project_links()
    if not projects:
        print("프로젝트 링크를 찾을 수 없습니다.")
        return [], 0

    os.makedirs(DATA_DIR, exist_ok=True)
    links_path = os.path.join(DATA_DIR, "project_links.json")
    with open(links_path, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)
    print(f"[OK] 링크 저장 → {links_path}")

    targets      = projects[:max_n] if max_n is not None else projects
    details_list = []
    img_count    = 0

    for i, proj in enumerate(targets, start=1):
        print(f"\n[{i}/{len(targets)}] {proj['title']}")
        details = get_project_details(proj["url"])
        # 상세 요청이 실패하면 uid 없는 "제목 없음" 건이 적재되므로 건너뛴다.
        if details.get("error"):
            print("  [SKIP] 상세 수집 실패")
            continue
        details["category"] = proj.get("category")
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

    return details_list, img_count


def main():
    print("=" * 50)
    print(f"  AIM 크롤러 (source={CRAWL_SOURCE})")
    print("=" * 50)

    # 환경변수에서 설정값을 읽어옴 (Cloud Run용)
    max_n_env = os.environ.get("MAX_PROJECTS")
    max_n = int(max_n_env) if max_n_env else MAX_PROJECTS

    # 1~2. 소스별 수집 (둘 다 아래 동일 싱크로 흐른다)
    if CRAWL_SOURCE == "paran":
        details_list = collect_paran()
        if max_n is not None:
            details_list = details_list[:max_n]
        img_count = 0
    else:
        details_list, img_count = collect_softcon(max_n)

    if not details_list:
        print("수집된 프로젝트가 없습니다.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    # 3. JSON 저장
    details_path = os.path.join(DATA_DIR, "project_details.json")
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details_list, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON 저장 → {details_path}")

    # 4. CSV 저장
    csv_path = os.path.join(DATA_DIR, "result.csv")
    save_csv(details_list, csv_path)


    # 5. DB 저장 또는 API 전송
    failures = 0
    if os.environ.get("BACKEND_API_BASE_URL") and os.environ.get("CRAWLER_API_TOKEN"):
        failures = post_to_api(details_list)
    else:
        save_to_db(details_list)

    # 결과 요약
    print("\n" + "=" * 50)
    print(f"  크롤링 완료!")
    print(f"  프로젝트: {len(details_list)}개")
    print(f"  이미지:   {img_count}개")
    print(f"  저장 위치: output/data/, output/images/")
    print("=" * 50)

    # 정기 실행에서 실패를 감지할 수 있도록 전송 실패가 있으면 비정상 종료한다.
    if failures:
        print(f"[경고] 전송 실패 {failures}건. 비정상 종료(exit 1).")
        sys.exit(1)


if __name__ == "__main__":
    main()
