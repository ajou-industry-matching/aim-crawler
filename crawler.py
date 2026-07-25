"""
소프트콘 (softcon.ajou.ac.kr) 작품 크롤러
- 텍스트/상세정보 → output/data/project_details.json, project_links.json
- 대표 이미지      → output/images/
"""

import os
import csv
import hashlib
import json
import re
import time

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

def get_project_links(list_type: str = "current", category: str = "S", term: str = None) -> list[dict]:
    # 목록 페이지에서 프로젝트 링크를 추출
    import requests
    from bs4 import BeautifulSoup

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


# 메인

def main():
    print("=" * 50)
    print("  소프트콘 작품 크롤러")
    print("=" * 50)

    # 모드 선택
    # 환경변수에서 설정값을 읽어옴 (Cloud Run용)
    # 로컬 실행 시 터미널에서 직접 지정: LIST_TYPE=current CATEGORY=S python3 crawler.py
    mode      = os.environ.get("LIST_TYPE", "current")          # current / previous
    category  = os.environ.get("CATEGORY", "S").upper()         # S / D / C / I
    max_n     = int(os.environ.get("MAX_PROJECTS", MAX_PROJECTS))
    term      = os.environ.get("TERM", "2024-1") if mode == "previous" else None

    list_type = mode  # current / previous

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

    # 5. DB 저장
    save_to_db(details_list)

    # 결과 요약
    print("\n" + "=" * 50)
    print(f"  크롤링 완료!")
    print(f"  프로젝트: {len(details_list)}개")
    print(f"  이미지:   {img_count}개")
    print(f"  저장 위치: output/data/, output/images/")
    print("=" * 50)


if __name__ == "__main__":
    main()
